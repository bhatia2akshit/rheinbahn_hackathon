import json
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.database import Base, SessionLocal, engine
from app.models import Category, Event, Incident, PoliceDepartment
from app.schemas import ActionType
from app.services.classifier import detect_category_keys
from app.services.router import find_police_department_by_postal_code, select_action
from app.services.script_generator import generate_police_script


CATEGORY_SEED = [
    {"internal_key": "traffic_accident", "label_de": "Verkehrsunfall"},
    {"internal_key": "illegal_parking_blocking", "label_de": "Falschparker / Blockierung"},
    {"internal_key": "physical_altercation", "label_de": "Körperliche Auseinandersetzung"},
    {"internal_key": "harassment", "label_de": "Belästigung"},
    {"internal_key": "vandalism", "label_de": "Vandalismus"},
    {"internal_key": "medical_emergency", "label_de": "Medizinischer Notfall"},
    {"internal_key": "threat", "label_de": "Bedrohung"},
    {"internal_key": "property_damage", "label_de": "Sachbeschädigung"},
    {"internal_key": "theft", "label_de": "Diebstahl"},
    {"internal_key": "operational_disruption", "label_de": "Störung des Betriebsablaufs"},
    {"internal_key": "unclear_disruption", "label_de": "Unklare Störung"},
]


POLICE_DEPARTMENT_SEED = [
    {
        "name": "Polizei Berlin Mitte",
        "city": "Berlin",
        "postal_code_start": 10100,
        "postal_code_end": 10999,
        "phone_number": "+49 30 4664 111111",
    },
    {
        "name": "Polizei Hamburg Zentrum",
        "city": "Hamburg",
        "postal_code_start": 20000,
        "postal_code_end": 20999,
        "phone_number": "+49 40 4286 222222",
    },
    {
        "name": "Polizei Bremen City",
        "city": "Bremen",
        "postal_code_start": 28195,
        "postal_code_end": 28779,
        "phone_number": "+49 421 362 333333",
    },
    {
        "name": "Polizei Hannover Innenstadt",
        "city": "Hannover",
        "postal_code_start": 30000,
        "postal_code_end": 30699,
        "phone_number": "+49 511 109 444444",
    },
    {
        "name": "Polizei Düsseldorf Zentrum",
        "city": "Düsseldorf",
        "postal_code_start": 40000,
        "postal_code_end": 40599,
        "phone_number": "+49 211 870 555555",
    },
    {
        "name": "Polizei Köln Innenstadt",
        "city": "Köln",
        "postal_code_start": 50000,
        "postal_code_end": 51149,
        "phone_number": "+49 221 229 666666",
    },
    {
        "name": "Polizei Frankfurt am Main",
        "city": "Frankfurt",
        "postal_code_start": 60300,
        "postal_code_end": 60599,
        "phone_number": "+49 69 755 777777",
    },
    {
        "name": "Polizei Stuttgart Zentrum",
        "city": "Stuttgart",
        "postal_code_start": 70000,
        "postal_code_end": 70699,
        "phone_number": "+49 711 8990 888888",
    },
    {
        "name": "Polizei München Innenstadt",
        "city": "München",
        "postal_code_start": 80000,
        "postal_code_end": 81999,
        "phone_number": "+49 89 2910 999999",
    },
    {
        "name": "Polizei Dresden Altstadt",
        "city": "Dresden",
        "postal_code_start": 1000,
        "postal_code_end": 1999,
        "phone_number": "+49 351 483 101010",
    },
    {
        "name": "Polizei Leipzig Zentrum",
        "city": "Leipzig",
        "postal_code_start": 4100,
        "postal_code_end": 4499,
        "phone_number": "+49 341 966 111212",
    },
    {
        "name": "Polizei Nürnberg Mitte",
        "city": "Nürnberg",
        "postal_code_start": 90400,
        "postal_code_end": 90799,
        "phone_number": "+49 911 2112 131313",
    },
]


SAMPLE_TEST_INCIDENTS = [
    {
        "raw_text": "An der Haltestelle gab es einen Unfall, ein Auto ist in die Tramspur gefahren.",
        "postal_code": "10115",
    },
    {
        "raw_text": "Ein Fahrzeug ist falsch geparkt und blockiert die Weiterfahrt unseres Busses.",
        "postal_code": "20095",
    },
    {
        "raw_text": "Zwei Personen prügeln sich im hinteren Bereich der Bahn und bedrohen Fahrgäste.",
        "postal_code": "60311",
    },
    {
        "raw_text": "Ein Fahrgast ist bewusstlos und verletzt, wir benötigen dringend Hilfe.",
        "postal_code": "80331",
    },
    {
        "raw_text": "Mehrere Personen schreien herum, verursachen eine Störung, aber die Lage ist unklar.",
        "postal_code": "50667",
    },
]


SAMPLE_EVENTS = [
    {
        "driver_name": "Lukas Schneider",
        "train_bus_number": "Bus 42",
        "timestamp": datetime(2025, 1, 10, 8, 15, 0),
        "location": "Heinrich-Heine-Allee, Dusseldorf",
        "description": "Passenger altercation reported near front door.",
        "status": "created",
    },
    {
        "driver_name": "Anna Weber",
        "train_bus_number": "Train U7",
        "timestamp": datetime(2025, 1, 10, 9, 30, 0),
        "location": "Dusseldorf Central Station",
        "description": "Medical assistance requested for one passenger.",
        "status": "in progress",
    },
    {
        "driver_name": "Mehmet Kaya",
        "train_bus_number": "Bus 125",
        "timestamp": datetime(2025, 1, 10, 10, 5, 0),
        "location": "Bilk S-Bahn Station, Dusseldorf",
        "description": "Illegal parking blocking bus lane.",
        "status": "pending",
    },
    {
        "driver_name": "Sophie Brandt",
        "train_bus_number": "Tram 703",
        "timestamp": datetime(2025, 1, 10, 11, 20, 0),
        "location": "Konigsallee, Dusseldorf",
        "description": "Suspicious package checked and cleared by authorities.",
        "status": "resolved",
    },
    {
        "driver_name": "David Fischer",
        "train_bus_number": "Train S8",
        "timestamp": datetime(2025, 1, 10, 12, 45, 0),
        "location": "Dusseldorf Flughafen Terminal",
        "description": "Signal issue causing temporary delay.",
        "status": "in progress",
    },
]


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def ensure_event_schema() -> None:
    with engine.begin() as conn:
        event_columns = conn.execute(text("PRAGMA table_info(events)")).fetchall()
        if not event_columns:
            return

        existing_names = {column[1] for column in event_columns}
        if "driver_name" not in existing_names:
            conn.execute(text("ALTER TABLE events ADD COLUMN driver_name VARCHAR(120)"))
        if "location" not in existing_names:
            conn.execute(text("ALTER TABLE events ADD COLUMN location VARCHAR(255)"))
        if "description" not in existing_names:
            conn.execute(text("ALTER TABLE events ADD COLUMN description TEXT"))
        if "status" not in existing_names:
            conn.execute(text("ALTER TABLE events ADD COLUMN status VARCHAR(30)"))

        conn.execute(
            text(
                "UPDATE events "
                "SET driver_name = 'Unknown Driver' "
                "WHERE driver_name IS NULL OR TRIM(driver_name) = ''"
            )
        )
        conn.execute(
            text(
                "UPDATE events "
                "SET location = 'Unknown Location' "
                "WHERE location IS NULL OR TRIM(location) = ''"
            )
        )
        conn.execute(
            text(
                "UPDATE events "
                "SET description = 'No description available.' "
                "WHERE description IS NULL OR TRIM(description) = ''"
            )
        )
        conn.execute(text("UPDATE events SET status = LOWER(status) WHERE status IS NOT NULL"))
        conn.execute(text("UPDATE events SET status = REPLACE(status, '_', ' ') WHERE status IS NOT NULL"))
        conn.execute(
            text(
                "UPDATE events "
                "SET status = 'created' "
                "WHERE status IS NULL "
                "OR TRIM(status) = '' "
                "OR status NOT IN ('created', 'in progress', 'resolved', 'pending', 'open')"
            )
        )
        conn.execute(
            text(
                "UPDATE events "
                "SET driver_name = CASE vehicle_number "
                "WHEN 'Bus 42' THEN 'Lukas Schneider' "
                "WHEN 'Train U7' THEN 'Anna Weber' "
                "WHEN 'Bus 125' THEN 'Mehmet Kaya' "
                "WHEN 'Tram 703' THEN 'Sophie Brandt' "
                "WHEN 'Train S8' THEN 'David Fischer' "
                "ELSE driver_name END, "
                "location = CASE vehicle_number "
                "WHEN 'Bus 42' THEN 'Heinrich-Heine-Allee, Dusseldorf' "
                "WHEN 'Train U7' THEN 'Dusseldorf Central Station' "
                "WHEN 'Bus 125' THEN 'Bilk S-Bahn Station, Dusseldorf' "
                "WHEN 'Tram 703' THEN 'Konigsallee, Dusseldorf' "
                "WHEN 'Train S8' THEN 'Dusseldorf Flughafen Terminal' "
                "ELSE location END, "
                "description = CASE vehicle_number "
                "WHEN 'Bus 42' THEN 'Passenger altercation reported near front door.' "
                "WHEN 'Train U7' THEN 'Medical assistance requested for one passenger.' "
                "WHEN 'Bus 125' THEN 'Illegal parking blocking bus lane.' "
                "WHEN 'Tram 703' THEN 'Suspicious package checked and cleared by authorities.' "
                "WHEN 'Train S8' THEN 'Signal issue causing temporary delay.' "
                "ELSE description END, "
                "status = CASE vehicle_number "
                "WHEN 'Bus 42' THEN 'created' "
                "WHEN 'Train U7' THEN 'in progress' "
                "WHEN 'Bus 125' THEN 'pending' "
                "WHEN 'Tram 703' THEN 'resolved' "
                "WHEN 'Train S8' THEN 'in progress' "
                "ELSE status END "
                "WHERE driver_name = 'Unknown Driver' OR location = 'Unknown Location'"
            )
        )


def seed_categories(db: Session) -> None:
    existing_keys = set(db.scalars(select(Category.internal_key)).all())
    missing = [item for item in CATEGORY_SEED if item["internal_key"] not in existing_keys]
    for item in missing:
        db.add(
            Category(
                internal_key=item["internal_key"],
                label_de=item["label_de"],
                description=f"Automatisch klassifizierte Kategorie: {item['label_de']}",
            )
        )


def seed_police_departments(db: Session) -> None:
    existing_names = set(db.scalars(select(PoliceDepartment.name)).all())
    missing = [item for item in POLICE_DEPARTMENT_SEED if item["name"] not in existing_names]
    for item in missing:
        db.add(PoliceDepartment(**item))


def seed_sample_incidents(db: Session) -> None:
    if db.scalar(select(Incident.id).limit(1)) is not None:
        return

    category_lookup = {
        item.internal_key: item.label_de for item in db.scalars(select(Category)).all()
    }
    for sample in SAMPLE_TEST_INCIDENTS:
        category_keys = detect_category_keys(sample["raw_text"])
        labels = [category_lookup.get(key, "Unklare Störung") for key in category_keys]
        action = select_action(category_keys)
        department = find_police_department_by_postal_code(db, sample["postal_code"])
        script = generate_police_script(
            raw_text=sample["raw_text"],
            postal_code=sample["postal_code"],
            categories=labels,
            department=department,
        )
        db.add(
            Incident(
                raw_text=sample["raw_text"],
                postal_code=sample["postal_code"],
                detected_categories=json.dumps(labels, ensure_ascii=False),
                selected_action=action.value,
                police_department_id=department.id if department else None,
                generated_script=script,
                created_at=datetime.now(timezone.utc),
            )
        )


def seed_sample_events(db: Session) -> None:
    if db.scalar(select(Event.id).limit(1)) is not None:
        return

    for sample in SAMPLE_EVENTS:
        db.add(
            Event(
                driver_name=sample["driver_name"],
                train_bus_number=sample["train_bus_number"],
                timestamp=sample["timestamp"],
                location=sample["location"],
                description=sample["description"],
                status=sample["status"],
            )
        )


def seed_all() -> None:
    init_db()
    ensure_event_schema()
    with SessionLocal() as db:
        seed_categories(db)
        seed_police_departments(db)
        db.commit()
        seed_sample_incidents(db)
        seed_sample_events(db)
        db.commit()


if __name__ == "__main__":
    seed_all()
    print("Database initialized and seeded.")
