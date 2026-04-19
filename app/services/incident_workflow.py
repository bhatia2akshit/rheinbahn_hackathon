import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.schemas import ActionType
from app.services.classifier import detect_category_keys
from app.services.router import find_police_department_by_postal_code, select_action
from app.services.script_generator import build_summary, generate_police_script


FALLBACK_CATEGORY_LABEL = "Unklare Störung"


@dataclass
class IncidentWorkflowResult:
    raw_text: str
    postal_code: str
    category_keys: list[str]
    selected_categories: list[str]
    selected_action: ActionType
    police_department: models.PoliceDepartment | None
    summary: str
    generated_script: str


def analyze_incident_workflow(
    db: Session,
    raw_text: str,
    postal_code: str,
) -> IncidentWorkflowResult:
    category_keys = detect_category_keys(raw_text)
    categories = db.scalars(
        select(models.Category).where(models.Category.internal_key.in_(category_keys))
    ).all()

    category_lookup = {category.internal_key: category.label_de for category in categories}
    selected_labels = [category_lookup.get(key, FALLBACK_CATEGORY_LABEL) for key in category_keys]

    action = select_action(category_keys)
    department = find_police_department_by_postal_code(db, postal_code)
    summary = build_summary(raw_text, selected_labels)
    script = generate_police_script(
        raw_text=raw_text,
        postal_code=postal_code,
        categories=selected_labels,
        department=department,
    )
    return IncidentWorkflowResult(
        raw_text=raw_text,
        postal_code=postal_code,
        category_keys=category_keys,
        selected_categories=selected_labels,
        selected_action=action,
        police_department=department,
        summary=summary,
        generated_script=script,
    )


def persist_incident(db: Session, result: IncidentWorkflowResult) -> models.Incident:
    incident = models.Incident(
        raw_text=result.raw_text,
        postal_code=result.postal_code,
        detected_categories=json.dumps(result.selected_categories, ensure_ascii=False),
        selected_action=result.selected_action.value,
        police_department_id=result.police_department.id if result.police_department else None,
        generated_script=result.generated_script,
    )
    db.add(incident)
    db.commit()
    db.refresh(incident)
    return incident


def persist_incident_and_event(
    db: Session,
    result: IncidentWorkflowResult,
    *,
    vehicle_number: str | None,
    location: str | None,
    description: str | None,
    driver_name: str = "Voice Bot",
) -> tuple[models.Incident, models.Event]:
    incident = models.Incident(
        raw_text=result.raw_text,
        postal_code=result.postal_code,
        detected_categories=json.dumps(result.selected_categories, ensure_ascii=False),
        selected_action=result.selected_action.value,
        police_department_id=result.police_department.id if result.police_department else None,
        generated_script=result.generated_script,
    )
    event = models.Event(
        train_bus_number=(vehicle_number or "Unknown Vehicle").strip(),
        location=(location or "Unknown Location").strip(),
        description=(description or result.summary).strip(),
        status="created",
        driver_name=driver_name,
    )
    db.add(incident)
    db.add(event)
    db.commit()
    db.refresh(incident)
    db.refresh(event)
    return incident, event


def parse_detected_categories(raw_value: str) -> list[str]:
    try:
        categories = json.loads(raw_value)
        if isinstance(categories, list) and all(isinstance(item, str) for item in categories):
            return categories
    except json.JSONDecodeError:
        pass
    return [FALLBACK_CATEGORY_LABEL]
