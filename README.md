# Public Transport Incident Reporting Simulator (MVP)

Small local simulation web app for an ÖPNV driver incident-reporting workflow.

## Features

- Free-text incident input + German 5-digit postal code input
- Deterministic rule-based incident classification (no external LLMs)
- Action routing (currently only `call_police`)
- Police department lookup by postal code range
- German police-call script generation
- Incident persistence in SQLite
- Simple Jinja2 + vanilla JS frontend

## Tech Stack

- `FastAPI`
- `SQLAlchemy ORM`
- `SQLite`
- `Jinja2` templates + vanilla JS/CSS

## Project Structure

```text
app/
  main.py
  database.py
  models.py
  schemas.py
  seed.py
  services/
    classifier.py
    router.py
    script_generator.py
  templates/
    index.html
  static/
    styles.css
    app.js
requirements.txt
README.md
```

## Database Schema

- `categories`
  - `id`
  - `internal_key` (unique)
  - `label_de`
  - `description`
- `police_departments`
  - `id`
  - `name`
  - `city`
  - `postal_code_start`
  - `postal_code_end`
  - `phone_number`
- `incidents`
  - `id`
  - `raw_text`
  - `postal_code`
  - `detected_categories` (JSON string list)
  - `selected_action`
  - `police_department_id` (nullable FK)
  - `generated_script`
  - `created_at`

## Setup

1. Create and activate virtualenv:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Initialize and seed the database:

```bash
python -m app.seed
```

4. Run the app locally:

```bash
uvicorn app.main:app --reload
```

5. Open in browser:

- [http://127.0.0.1:8000](http://127.0.0.1:8000)

## API Endpoints

- `GET /` -> Frontend page
- `POST /analyze` -> Analyze incident input
- `GET /api/categories` -> List seeded categories
- `GET /api/police-departments` -> List seeded police departments
- `GET /api/incidents` -> List saved incidents

## Notes on Behavior

- Postal code validation requires exactly 5 digits.
- Category detection is deterministic and keyword/scoring-based.
- Multiple categories are allowed.
- If no category matches, fallback is `Unklare Störung`.
- If no police department matches a postal code range, response includes a graceful fallback.

## Sample Test Data (Manual Testing)

The app seeds these five example incidents:

1. `An der Haltestelle gab es einen Unfall, ein Auto ist in die Tramspur gefahren.` (PLZ `10115`)
2. `Ein Fahrzeug ist falsch geparkt und blockiert die Weiterfahrt unseres Busses.` (PLZ `20095`)
3. `Zwei Personen prügeln sich im hinteren Bereich der Bahn und bedrohen Fahrgäste.` (PLZ `60311`)
4. `Ein Fahrgast ist bewusstlos und verletzt, wir benötigen dringend Hilfe.` (PLZ `80331`)
5. `Mehrere Personen schreien herum, verursachen eine Störung, aber die Lage ist unklar.` (PLZ `50667`)

You can also use these from the UI sample list with one click.

## Extensibility

Action routing is isolated in `app/services/router.py` and currently returns only:

- `call_police`

You can later add additional actions such as:

- `call_ambulance`
- `notify_control_center`
- `send_sms`
- `create_internal_ticket`

