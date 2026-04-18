from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.seed import SAMPLE_TEST_INCIDENTS, seed_all
from app.services.incident_workflow import (
    analyze_incident_workflow,
    parse_detected_categories,
    persist_incident,
)
from app.voice.config import load_voice_settings
from app.voice.conversation_store import conversation_store
from app.voice.runtime import VoiceRuntimeManager


BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

# Load local .env automatically for local development.
load_dotenv(PROJECT_ROOT / ".env")

app = FastAPI(
    title="Public Transport Incident Reporting Simulator",
    version="0.1.0",
)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

voice_manager = VoiceRuntimeManager(load_voice_settings())

prebuilt_ui_available = False
try:
    from pipecat_ai_small_webrtc_prebuilt.frontend import SmallWebRTCPrebuiltUI

    app.mount("/voice/client", SmallWebRTCPrebuiltUI)
    prebuilt_ui_available = True
except Exception:
    prebuilt_ui_available = False


@app.on_event("startup")
async def on_startup() -> None:
    seed_all()
    await voice_manager.prewarm()


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await voice_manager.shutdown()


@app.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    departments = db.scalars(
        select(models.PoliceDepartment).order_by(models.PoliceDepartment.postal_code_start.asc())
    ).all()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "departments": departments,
            "sample_incidents": SAMPLE_TEST_INCIDENTS,
            "voice_status": voice_manager.status(),
            "prebuilt_ui_available": prebuilt_ui_available,
        },
    )


@app.post("/analyze", response_model=schemas.AnalyzeResponse)
def analyze_incident(
    payload: schemas.IncidentAnalyzeRequest,
    db: Session = Depends(get_db),
) -> schemas.AnalyzeResponse:
    result = analyze_incident_workflow(
        db=db,
        raw_text=payload.raw_text,
        postal_code=payload.postal_code,
    )
    persist_incident(db, result)

    return schemas.AnalyzeResponse(
        original_input=payload.raw_text,
        postal_code=payload.postal_code,
        selected_categories=result.selected_categories,
        selected_action=result.selected_action.value,
        police_department=result.police_department,
        police_phone_number=result.police_department.phone_number if result.police_department else None,
        summary=result.summary,
        generated_script=result.generated_script,
    )


@app.get("/api/categories", response_model=list[schemas.CategoryOut])
def list_categories(db: Session = Depends(get_db)) -> list[models.Category]:
    return db.scalars(select(models.Category).order_by(models.Category.id.asc())).all()


@app.get("/api/police-departments", response_model=list[schemas.PoliceDepartmentOut])
def list_police_departments(db: Session = Depends(get_db)) -> list[models.PoliceDepartment]:
    return db.scalars(
        select(models.PoliceDepartment).order_by(models.PoliceDepartment.postal_code_start.asc())
    ).all()


@app.get("/api/incidents", response_model=list[schemas.IncidentOut])
def list_incidents(db: Session = Depends(get_db)) -> list[schemas.IncidentOut]:
    incidents = db.scalars(select(models.Incident).order_by(models.Incident.created_at.desc())).all()
    result: list[schemas.IncidentOut] = []
    for incident in incidents:
        categories = parse_detected_categories(incident.detected_categories)

        department = None
        if incident.police_department_id:
            department = db.get(models.PoliceDepartment, incident.police_department_id)
            if department is None:
                raise HTTPException(status_code=500, detail="Invalid police department reference")

        result.append(
            schemas.IncidentOut(
                id=incident.id,
                raw_text=incident.raw_text,
                postal_code=incident.postal_code,
                detected_categories=categories,
                selected_action=incident.selected_action,
                police_department=department,
                generated_script=incident.generated_script,
                created_at=incident.created_at,
            )
        )
    return result


@app.get("/voice")
def open_voice_client() -> Response:
    if prebuilt_ui_available:
        return RedirectResponse(url="/voice/client/")
    return Response(
        content=(
            "Pipecat prebuilt WebRTC client is not installed. "
            "Install dependency: pipecat-ai-small-webrtc-prebuilt"
        ),
        status_code=503,
    )


@app.get("/api/voice/status")
def voice_status() -> dict:
    return {
        **voice_manager.status(),
        "prebuilt_ui_available": prebuilt_ui_available,
    }


@app.get("/api/voice/conversation")
def voice_conversation() -> dict:
    return conversation_store.get_latest_snapshot()


@app.post("/api/offer")
async def create_offer(request: Request) -> dict:
    payload = await request.json()
    return await voice_manager.handle_offer_payload(payload)


@app.patch("/api/offer")
async def patch_offer(request: Request) -> dict:
    payload = await request.json()
    return await voice_manager.handle_patch_payload(payload)


@app.post("/start")
async def start_voice_session(request: Request) -> dict:
    payload = await request.json()
    session_body = payload.get("body", {})
    enable_default_ice_servers = bool(payload.get("enableDefaultIceServers"))
    return voice_manager.create_session(
        body=session_body,
        enable_default_ice_servers=enable_default_ice_servers,
    )


@app.api_route(
    "/sessions/{session_id}/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    response_model=None,
)
async def voice_session_proxy(session_id: str, path: str, request: Request):
    session_body = voice_manager.get_session_body(session_id)
    if session_body is None:
        return Response(content="Invalid or not-yet-ready session_id", status_code=404)

    if path.endswith("api/offer"):
        payload = await request.json()
        if request.method == "POST":
            return await voice_manager.handle_offer_payload(
                payload=payload,
                fallback_request_data=session_body,
            )
        if request.method == "PATCH":
            return await voice_manager.handle_patch_payload(payload)
        return Response(content="Method not allowed", status_code=405)

    return Response(status_code=200)
