import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from app import models
from app.database import SessionLocal
from app.services.emergency_dispatch import (
    build_dispatch_calls_for_event,
    infer_dispatch_targets_from_text,
)
from app.voice.conversation_store import conversation_store


@dataclass(frozen=True)
class VoiceTurnResult:
    replies: list[str]
    completed: bool = False
    event_payload: dict[str, Any] | None = None


class VoiceUsecaseOrchestrator:
    """Deterministic incident collection flow used by the Pipecat voice runtime."""

    _location_pattern = re.compile(
        r"\b(?:location|ort|standort|bei|an|zwischen)\s+([A-Za-zÄÖÜäöüß0-9 .,'\-]{3,120})\b",
        re.IGNORECASE,
    )
    _urgent_description_pattern = re.compile(
        r"\b("
        r"unfall|kollision|zusammensto(ß|ss)\w*|entgleis\w*|brand|feuer|rauch|"
        r"blut|bewusstlos\w*|ohnmacht|verletz\w*|notfall\w*|angriff\w*|attack\w*|messer|"
        r"bedroh\w*|schläg\w*|pruegel\w*|prügel\w*|gewalt\w*|polizei|rettung|ambulanz"
        r")\b",
        re.IGNORECASE,
    )
    _yes_pattern = re.compile(
        r"\b(ja|jep|klar|genau|bitte|unbedingt|sofort|mach das|alarmier|informier)\b",
        re.IGNORECASE,
    )
    _no_pattern = re.compile(
        r"\b(nein|nee|nicht|kein|keine|reicht|nur dokumentation|erstmal nicht)\b",
        re.IGNORECASE,
    )
    def __init__(
        self,
        *,
        session_id: str,
        driver_name: str | None = None,
        train_number: str | None = None,
    ):
        self._session_id = session_id
        self._last_question_slot: str | None = None
        self._event_created = False
        self._question_attempts: dict[str, int] = {
            "description": 0,
            "location": 0,
            "people_hurt": 0,
            "dispatch_targets": 0,
        }
        self._slots: dict[str, Any] = {
            "driver_name": self._normalize_metadata_value(driver_name, "Unknown Driver"),
            "train_number": self._normalize_metadata_value(train_number, "Unknown Vehicle"),
            "description": None,
            "location": None,
            "people_hurt": None,
            "dispatch_targets": None,
        }
        conversation_store.start_session(session_id)
        conversation_store.update_slots(session_id, self._slots)

    def start_conversation(self) -> VoiceTurnResult:
        return VoiceTurnResult(replies=[self._build_next_question()])

    def add_assistant_message(self, content: str) -> None:
        conversation_store.add_message(self._session_id, "ai", content)

    def on_user_text(self, content: str) -> VoiceTurnResult:
        conversation_store.add_message(self._session_id, "driver", content)

        if self._event_created:
            return VoiceTurnResult(replies=[])

        if self._last_question_slot:
            self._question_attempts[self._last_question_slot] += 1

        slot_updates = self._extract_slot_updates(content)
        if slot_updates:
            self._slots.update(slot_updates)
            conversation_store.update_slots(self._session_id, slot_updates)
            for slot_name in slot_updates:
                if slot_name in self._question_attempts:
                    self._question_attempts[slot_name] = 0

        if not self._is_dialog_complete():
            return VoiceTurnResult(replies=[self._build_next_question()])

        event = self._persist_event()
        self._event_created = True

        event_payload = {
            "event_id": event.id,
            "driver_name": event.driver_name,
            "train_number": event.train_bus_number,
            "timestamp": event.timestamp.isoformat() if event.timestamp else None,
            "location": event.location,
            "description": event.description,
            "status": event.status,
            "dispatch_calls": build_dispatch_calls_for_event(event),
        }
        conversation_store.set_event(self._session_id, event_payload)

        return VoiceTurnResult(
            replies=["Alles klar, ich bin dran."],
            completed=True,
            event_payload=event_payload,
        )

    def _persist_event(self) -> models.Event:
        description = str(self._slots["description"] or "").strip()
        hurt = self._bool_to_label(self._slots["people_hurt"])
        dispatch_targets = self._dispatch_targets_label(self._slots["dispatch_targets"])
        full_description = (
            f"{description}\n\n"
            f"People hurt: {hurt}\n"
            f"Dispatch requested: {dispatch_targets}"
        )

        with SessionLocal() as db:
            event = models.Event(
                driver_name=str(self._slots["driver_name"]).strip(),
                train_bus_number=str(self._slots["train_number"]).strip(),
                location=str(self._slots["location"]).strip(),
                description=full_description,
                status="in progress" if self._slots["dispatch_targets"] else "open",
                timestamp=datetime.now(timezone.utc),
            )
            db.add(event)
            db.commit()
            db.refresh(event)
            return event

    def _build_next_question(self) -> str:
        missing = self._next_missing_slot()
        self._last_question_slot = missing
        attempts = self._question_attempts.get(missing or "", 0)
        if missing == "description":
            if attempts > 0:
                return "Beschreib mir bitte noch einmal ganz kurz, was passiert ist."
            return "Erzähl mir bitte kurz, was passiert ist."
        if missing == "location":
            if attempts > 0:
                return "Wo genau ist das passiert? Nenn mir bitte die Haltestelle oder den Abschnitt."
            return "Wo genau ist das passiert?"
        if missing == "people_hurt":
            if self._description_sounds_urgent():
                if attempts > 0:
                    return "Nur kurz zur Sicherheit: Gibt es Verletzte oder akute Gefahr?"
                return "Sind Menschen verletzt oder in akuter Gefahr?"
            if attempts > 0:
                return "Nur kurz zur Sicherheit: Ist jemand verletzt, ja oder nein?"
            return "Ist jemand verletzt?"
        if missing == "dispatch_targets":
            if self._description_sounds_urgent() or self._slots.get("people_hurt") is True:
                if attempts > 0:
                    return "Soll ich jetzt Polizei, Rettung oder beide alarmieren? Sag bitte klar, was gerufen werden soll."
                return "Soll ich Polizei, Rettung oder beide alarmieren?"
            if attempts > 0:
                return "Brauchst du Polizei, Rettung oder beide, oder reicht erstmal nur die Meldung?"
            return "Soll ich Polizei oder Rettung dazuholen, oder reicht erstmal nur die Meldung?"
        return "Alles klar."

    def _next_missing_slot(self) -> str | None:
        for key in ("description", "location", "people_hurt", "dispatch_targets"):
            if self._slots.get(key) is None:
                return key
        return None

    def _is_dialog_complete(self) -> bool:
        return self._next_missing_slot() is None

    def _extract_slot_updates(self, transcript: str) -> dict[str, Any]:
        updates: dict[str, Any] = {}
        clean = " ".join(transcript.strip().split())

        if self._last_question_slot == "description" and clean:
            updates["description"] = self._normalize_slot_answer("description", clean)

        location_match = self._location_pattern.search(clean)
        if location_match and self._slots.get("location") is None:
            updates["location"] = location_match.group(1).strip(" .")

        if self._last_question_slot == "location" and "location" not in updates and clean:
            updates["location"] = self._normalize_slot_answer("location", clean)

        if self._last_question_slot == "people_hurt" and self._slots.get("people_hurt") is None:
            parsed = self._parse_yes_no(clean)
            if parsed is not None:
                updates["people_hurt"] = parsed

        if (
            self._last_question_slot == "dispatch_targets"
            and self._slots.get("dispatch_targets") is None
        ):
            parsed = self._parse_dispatch_targets(clean)
            if parsed is not None:
                updates["dispatch_targets"] = parsed

        return updates

    def _description_sounds_urgent(self) -> bool:
        description = str(self._slots.get("description") or "")
        return bool(self._urgent_description_pattern.search(description))

    def _parse_yes_no(self, text: str) -> bool | None:
        has_yes = bool(self._yes_pattern.search(text))
        has_no = bool(self._no_pattern.search(text))
        if has_yes and not has_no:
            return True
        if has_no and not has_yes:
            return False
        return None

    @staticmethod
    def _normalize_metadata_value(value: str | None, fallback: str) -> str:
        if value is None:
            return fallback
        cleaned = " ".join(value.strip().split())
        return cleaned or fallback

    @staticmethod
    def _bool_to_label(value: bool | None) -> str:
        if value is True:
            return "Yes"
        if value is False:
            return "No"
        return "Unknown"

    @staticmethod
    def _normalize_slot_answer(slot_name: str, text: str) -> str:
        cleaned = " ".join(text.strip().split())
        cleaned = re.sub(r"^(?:ja|okay|ok|also|gut)[, ]+", "", cleaned, flags=re.IGNORECASE)

        if slot_name == "location":
            cleaned = re.sub(
                r"^(?:es\s+)?ist\s+",
                "",
                cleaned,
                flags=re.IGNORECASE,
            )
            return cleaned.strip(" .")

        return cleaned.strip(" .")

    def _parse_dispatch_targets(self, text: str) -> list[str] | None:
        requested_from_answer = infer_dispatch_targets_from_text(text)
        if requested_from_answer:
            return requested_from_answer

        parsed_yes_no = self._parse_yes_no(text)
        if parsed_yes_no is True:
            return infer_dispatch_targets_from_text(str(self._slots.get("description") or ""))
        if parsed_yes_no is False:
            return []
        return None

    @staticmethod
    def _dispatch_targets_label(value: list[str] | None) -> str:
        if not value:
            return "none"
        return ", ".join(value)


def prewarm_usecase_imports() -> None:
    _ = (VoiceTurnResult, VoiceUsecaseOrchestrator, models.Event, Session)
    logger.debug("Voice use-case layer prewarmed")
