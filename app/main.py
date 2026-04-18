import json
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.seed import SAMPLE_TEST_INCIDENTS, seed_all
from app.services.classifier import detect_category_keys
from app.services.router import find_police_department_by_postal_code, select_action
from app.services.script_generator import build_summary, generate_police_script

from .speech import save_temp_file, transcribe_audio

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(
    title="Public Transport Incident Reporting Simulator",
    version="0.1.0",
)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@app.on_event("startup")
def on_startup() -> None:
    seed_all()


@app.post("/analyze", response_model=schemas.AnalyzeResponse)
def analyze_incident(
    payload: schemas.IncidentAnalyzeRequest,
    db: Session = Depends(get_db),
) -> schemas.AnalyzeResponse:
    category_keys = detect_category_keys(payload.raw_text)
    categories = db.scalars(
        select(models.Category).where(models.Category.internal_key.in_(category_keys))
    ).all()
    category_lookup = {category.internal_key: category.label_de for category in categories}
    selected_labels = [category_lookup.get(key, "Unklare Störung") for key in category_keys]

    action = select_action(category_keys)
    department = find_police_department_by_postal_code(db, payload.postal_code)
    summary = build_summary(payload.raw_text, selected_labels)
    script = generate_police_script(
        raw_text=payload.raw_text,
        postal_code=payload.postal_code,
        categories=selected_labels,
        department=department,
    )

    incident = models.Incident(
        raw_text=payload.raw_text,
        postal_code=payload.postal_code,
        detected_categories=json.dumps(selected_labels, ensure_ascii=False),
        selected_action=action.value,
        police_department_id=department.id if department else None,
        generated_script=script,
    )
    db.add(incident)
    db.commit()

    return schemas.AnalyzeResponse(
        original_input=payload.raw_text,
        postal_code=payload.postal_code,
        selected_categories=selected_labels,
        selected_action=action.value,
        police_department=department,
        police_phone_number=department.phone_number if department else None,
        summary=summary,
        generated_script=script,
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
        try:
            categories = json.loads(incident.detected_categories)
            if not isinstance(categories, list):
                categories = ["Unklare Störung"]
        except json.JSONDecodeError:
            categories = ["Unklare Störung"]

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

@app.post("/speech-to-text")
async def speech_to_text(file: UploadFile):
    temp_path = save_temp_file(file)
    text = transcribe_audio(temp_path)
    return {"text": text}

@app.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    departments = db.scalars(
        select(models.PoliceDepartment).order_by(models.PoliceDepartment.postal_code_start.asc())
    ).all()
    events = db.scalars(select(models.Event).order_by(models.Event.timestamp.desc())).all()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "departments": departments,
            "sample_incidents": SAMPLE_TEST_INCIDENTS,
            "events": events
        },
    )

@app.get("/event/{event_id}", response_class=HTMLResponse)
def incident_details(event_id: int, request: Request, db: Session = Depends(get_db)):
    event = db.get(models.Event, event_id)

    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    return templates.TemplateResponse(
        request=request,
        name="event_details.html",
        context={
            "request": request,
            "event": event,
        },
    )
