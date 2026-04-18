# Public Transport Incident Reporting Simulator (MVP)

Small local simulation web app for an ÖPNV driver incident-reporting workflow.

## Features

- Free-text incident input + German 5-digit postal code input
- Deterministic rule-based incident classification (no external LLMs)
- Action routing (currently only `call_police`)
- Police department lookup by postal code range
- German police-call script generation
- Voice pipeline via Pipecat + WebRTC
- STT via Deepgram
- TTS via Deepgram
- Optional LLM script polishing via Hugging Face Router OpenAI-compatible API
- Incident persistence in SQLite
- Simple Jinja2 + vanilla JS frontend

## Tech Stack

- `FastAPI`
- `SQLAlchemy ORM`
- `SQLite`
- `Jinja2` templates + vanilla JS/CSS
- `Pipecat` (SmallWebRTC transport)
- `deepgram-sdk`
- Hugging Face Router (`https://router.huggingface.co/v1`) for LLM

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
    incident_workflow.py
    router.py
    script_generator.py
  voice/
    config.py
    hf_llm.py
    hf_services.py
    processor.py
    runtime.py
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

## Voice Mode Setup (Pipecat + WebRTC)

Set required env vars before running:

```bash
export DEEPGRAM_API_KEY="your_deepgram_api_key"
```

You can also put the same values in a `.env` file at the project root.
The app now auto-loads `.env` on startup.
`DEEPGRAM_API_KEY` is required for voice mode.

Optional:

```bash
export VOICE_DEFAULT_POSTAL_CODE="10115"
export DEEPGRAM_STT_MODEL="nova-3-general"
export DEEPGRAM_STT_LANGUAGE="de"

export DEEPGRAM_TTS_MODEL="aura-2-helena-en"
export DEEPGRAM_TTS_VOICE="aura-2-helena-en"
export DEEPGRAM_TTS_ENCODING="linear16"
export DEEPGRAM_TTS_SAMPLE_RATE="24000"

# Optional HF token for LLM polishing only.
export HF_TOKEN="your_huggingface_token"
export HF_LLM_MODEL="meta-llama/Llama-3.1-8B-Instruct:hf-inference"
export HF_LLM_TEMPERATURE="0.2"
export HF_LLM_MAX_TOKENS="220"
```

Then open:

- [http://127.0.0.1:8000/voice/client/](http://127.0.0.1:8000/voice/client/)

Voice flow:

1. Browser microphone stream via WebRTC to Pipecat transport.
2. STT transcription by Deepgram.
3. Incident workflow classification + police lookup in local app logic.
4. Optional script polishing through Hugging Face Router chat completion.
5. Final script spoken through Deepgram TTS.

## API Endpoints

- `GET /` -> Frontend page
- `POST /analyze` -> Analyze incident input
- `GET /api/categories` -> List seeded categories
- `GET /api/police-departments` -> List seeded police departments
- `GET /api/incidents` -> List saved incidents
- `GET /api/voice/status` -> Voice configuration/runtime status
- `POST /api/offer` -> WebRTC offer signaling (Pipecat SmallWebRTC)
- `PATCH /api/offer` -> ICE candidate signaling
- `POST /start` and `sessions/{session_id}/...` -> session-style signaling compatibility

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
