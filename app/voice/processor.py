import re
import time
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger
from pipecat.frames.frames import Frame, TTSSpeakFrame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from sqlalchemy.orm import Session

from app.services.incident_workflow import analyze_incident_workflow, persist_incident
from app.voice.conversation_store import conversation_store


class IncidentSpeechProcessor(FrameProcessor):
    """Runs a simple German multi-turn dialog and creates an incident event at the end."""

    _postal_code_pattern = re.compile(r"\b\d{5}\b")
    _vehicle_pattern = re.compile(
        r"\b(?:linie|bus|tram|straßenbahn|strassenbahn|bahn|zug)\s*([a-zA-Z]?\d{1,4})\b",
        re.IGNORECASE,
    )
    _vehicle_pattern_with_filler = re.compile(
        r"\b(?:linie|line|bus|tram|straßenbahn|strassenbahn|bahn|zug)"
        r"(?:\s+(?:nummer|number|nr\.?|no\.?|ist|is|fahrzeug|fahrzeugnummer|heißt|heisst)){0,5}"
        r"\s+([a-zA-Z]?\d{1,4})\b",
        re.IGNORECASE,
    )
    _vehicle_number_keyword_pattern = re.compile(
        r"\b(?:fahrzeugnummer|wagennummer|fahrzeug)\s*(?:ist|is|nr\.?|nummer|no\.?)?\s*([a-zA-Z]?\d{1,4})\b",
        re.IGNORECASE,
    )
    _vehicle_only_pattern = re.compile(r"^\s*([a-zA-Z]?\d{1,4})\s*$")
    _location_between_pattern = re.compile(
        r"\bzwischen\s+([A-Za-zÄÖÜäöüß0-9 .\-]{2,50}?)\s+und\s+([A-Za-zÄÖÜäöüß0-9 .\-]{2,50})\b",
        re.IGNORECASE,
    )

    def __init__(
        self,
        session_id: str,
        db_session_factory: Callable[[], Session],
        default_postal_code: str,
        script_refiner: Callable[..., Awaitable[str]] | None = None,
    ):
        super().__init__()
        self._session_id = session_id
        self._db_session_factory = db_session_factory
        self._default_postal_code = default_postal_code
        self._script_refiner = script_refiner
        self._last_transcript = ""
        self._last_transcript_at = 0.0
        self._dialog_finished = False
        self._slots: dict[str, Any] = {
            "vehicle_number": None,
            "location_between_stops": None,
            "postal_code": default_postal_code,
            "description": None,
            "injured": None,
            "repair_or_blocked": None,
            "logistics": None,
        }
        self._postal_user_provided = False

        conversation_store.start_session(session_id)
        conversation_store.update_slots(session_id, self._slots)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)

        if direction != FrameDirection.DOWNSTREAM:
            return
        if not isinstance(frame, TranscriptionFrame):
            return

        transcript = frame.text.strip()
        if not transcript:
            return

        normalized = " ".join(transcript.lower().split())
        now = time.monotonic()
        if normalized == self._last_transcript and now - self._last_transcript_at < 2.0:
            return

        self._last_transcript = normalized
        self._last_transcript_at = now

        conversation_store.add_message(self._session_id, "driver", transcript)

        if self._dialog_finished:
            await self._speak(
                "Die Meldung wurde bereits erstellt. Für einen neuen Vorfall starten Sie bitte eine neue Sitzung."
            )
            return

        slot_updates = self._extract_slot_updates(transcript)
        if slot_updates:
            self._slots.update(slot_updates)
            conversation_store.update_slots(self._session_id, slot_updates)

        if not self._is_dialog_complete():
            next_question = self._next_question()
            await self._speak(next_question)
            return

        combined_text = self._build_combined_raw_text()
        postal_code = self._slots.get("postal_code") or self._default_postal_code
        try:
            with self._db_session_factory() as db:
                result = analyze_incident_workflow(
                    db=db,
                    raw_text=combined_text,
                    postal_code=postal_code,
                )
                if self._script_refiner:
                    try:
                        refined = await self._script_refiner(
                            transcript=combined_text,
                            postal_code=postal_code,
                            categories=result.selected_categories,
                            deterministic_script=result.generated_script,
                        )
                        result.generated_script = refined
                    except Exception as llm_exc:
                        logger.warning(f"HF LLM polish failed, using deterministic script: {llm_exc}")
                incident = persist_incident(db, result)
        except Exception as exc:
            logger.exception(f"Voice incident workflow failed: {exc}")
            await self._speak(
                "Die automatische Auswertung konnte nicht abgeschlossen werden. "
                "Bitte melden Sie den Vorfall noch einmal."
            )
            return

        self._dialog_finished = True
        conversation_store.set_event(
            self._session_id,
            {
                "incident_id": incident.id,
                "vehicle_number": self._slots["vehicle_number"],
                "location_between_stops": self._slots["location_between_stops"],
                "postal_code": postal_code,
                "description": self._slots["description"],
                "logistics": self._slots["logistics"],
                "injured": self._slots["injured"],
                "repair_or_blocked": self._slots["repair_or_blocked"],
                "selected_categories": result.selected_categories,
                "action_required": result.selected_action.value,
                "police_department": (
                    f"{result.police_department.name} ({result.police_department.city})"
                    if result.police_department
                    else None
                ),
                "police_phone_number": (
                    result.police_department.phone_number if result.police_department else None
                ),
                "summary": result.summary,
                "generated_script": result.generated_script,
            },
        )

        completion_message = (
            f"Danke. Meldung erstellt für Linie {self._slots['vehicle_number']}, "
            f"Abschnitt {self._slots['location_between_stops']}. "
            f"Einstufung: {', '.join(result.selected_categories)}. "
            "Ich lese jetzt die Meldung für die Polizei vor. "
            f"{result.generated_script}"
        )
        await self._speak(completion_message)

    def _extract_postal_code(self, transcript: str) -> str:
        match = self._postal_code_pattern.search(transcript)
        if match:
            return match.group(0)
        return self._default_postal_code

    async def _speak(self, message: str) -> None:
        conversation_store.add_message(self._session_id, "ai", message)
        await self.push_frame(TTSSpeakFrame(message), FrameDirection.DOWNSTREAM)

    def _extract_slot_updates(self, transcript: str) -> dict[str, Any]:
        lower = transcript.lower()
        updates: dict[str, Any] = {}

        postal_code = self._extract_postal_code(transcript)
        if postal_code and postal_code != self._default_postal_code:
            updates["postal_code"] = postal_code
            self._postal_user_provided = True
        elif "postleitzahl" in lower and any(token in lower for token in ["unbekannt", "weiß nicht", "weiss nicht"]):
            self._postal_user_provided = True

        vehicle_number = self._extract_vehicle_number(transcript)
        if vehicle_number:
            updates["vehicle_number"] = vehicle_number

        location_match = self._location_between_pattern.search(transcript)
        if location_match:
            station_a = location_match.group(1).strip(" ,.")
            station_b = location_match.group(2).strip(" ,.")
            updates["location_between_stops"] = f"zwischen {station_a} und {station_b}"

        if updates.get("description") is None and self._slots.get("description") is None:
            if self._looks_like_description(transcript):
                updates["description"] = transcript

        injured = self._parse_yes_no(
            lower=lower,
            yes_tokens=["verletzt", "blutet", "bewusstlos", "medizinischer notfall", "ja"],
            no_tokens=["niemand verletzt", "keiner verletzt", "keine verletzten", "nein"],
        )
        if injured is not None:
            updates["injured"] = injured

        blocked = self._parse_yes_no(
            lower=lower,
            yes_tokens=[
                "blockiert",
                "steht still",
                "weiterfahrt nicht möglich",
                "defekt",
                "reparatur",
                "kaputt",
            ],
            no_tokens=["nicht blockiert", "fahrt möglich", "kein defekt", "nein"],
        )
        if blocked is not None:
            updates["repair_or_blocked"] = blocked

        if any(
            token in lower
            for token in ["abschlepp", "werkstatt", "ersatzbus", "sicherheitsdienst", "technik", "reparaturteam"]
        ):
            updates["logistics"] = transcript

        return updates

    def _extract_vehicle_number(self, transcript: str) -> str | None:
        # Direct patterns: "Linie 1234", "Bus 81", etc.
        strict = self._vehicle_pattern.search(transcript)
        if strict:
            return strict.group(1).upper()

        # Filler-word patterns: "Linie Nummer ist 1234", "Fahrzeugnummer ist 81".
        filler = self._vehicle_pattern_with_filler.search(transcript)
        if filler:
            return filler.group(1).upper()

        keyword = self._vehicle_number_keyword_pattern.search(transcript)
        if keyword:
            return keyword.group(1).upper()

        # Short answer after question: "1234"
        if not self._slots.get("vehicle_number"):
            only = self._vehicle_only_pattern.fullmatch(transcript)
            if only:
                return only.group(1).upper()

        return None

    def _is_dialog_complete(self) -> bool:
        return all(
            [
                self._slots.get("description"),
                self._slots.get("vehicle_number"),
                self._slots.get("location_between_stops"),
                self._slots.get("injured") is not None,
                self._slots.get("repair_or_blocked") is not None,
            ]
        )

    def _next_question(self) -> str:
        if not self._slots.get("description"):
            return "Bitte schildern Sie kurz das Problem mit Bus oder Tram."
        if not self._slots.get("vehicle_number"):
            return "Welche Linie oder Fahrzeugnummer betrifft den Vorfall?"
        if not self._slots.get("location_between_stops"):
            return (
                "Wo genau ist der Vorfall? Bitte nennen Sie den Abschnitt zwischen zwei "
                "Haltestellen in Düsseldorf."
            )
        if self._slots.get("injured") is None:
            return "Gibt es verletzte Personen oder einen medizinischen Notfall?"
        if self._slots.get("repair_or_blocked") is None:
            return "Ist die Strecke blockiert oder wird technischer Reparaturdienst benötigt?"
        return "Danke, ich prüfe die Angaben."

    def _looks_like_description(self, transcript: str) -> bool:
        lower = transcript.lower().strip()
        if len(lower) < 12:
            return False
        if self._postal_code_pattern.fullmatch(lower):
            return False
        simple_answers = {"ja", "nein", "unbekannt", "weiß nicht", "weiss nicht"}
        if lower in simple_answers:
            return False
        return True

    @staticmethod
    def _parse_yes_no(lower: str, yes_tokens: list[str], no_tokens: list[str]) -> bool | None:
        if any(token in lower for token in no_tokens):
            return False
        if any(token in lower for token in yes_tokens):
            return True
        return None

    def _build_combined_raw_text(self) -> str:
        parts = [
            f"Linie/Fahrzeug: {self._slots.get('vehicle_number')}.",
            f"Ort: {self._slots.get('location_between_stops')}.",
            f"Beschreibung: {self._slots.get('description')}.",
            (
                "Verletzte: ja."
                if self._slots.get("injured") is True
                else "Verletzte: nein."
            ),
            (
                "Betriebsbeeinträchtigung/Reparaturbedarf: ja."
                if self._slots.get("repair_or_blocked") is True
                else "Betriebsbeeinträchtigung/Reparaturbedarf: nein."
            ),
        ]
        if self._slots.get("logistics"):
            parts.append(f"Logistik: {self._slots['logistics']}.")
        return " ".join(parts)
