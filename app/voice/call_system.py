from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app import models
from app.database import SessionLocal
from app.services.emergency_dispatch import DispatchServiceKey, build_dispatch_call_script
from app.voice.run_system import VoiceTurnResult


@dataclass(frozen=True)
class DispatchCallContext:
    event: models.Event
    service: DispatchServiceKey


class EmergencyCallOrchestrator:
    """One-turn outbound call flow where the callee speaks first."""

    def __init__(self, *, event_id: int, service: DispatchServiceKey):
        self._context = self._load_context(event_id=event_id, service=service)
        self._initial_briefing_sent = False

    def start_conversation(self) -> VoiceTurnResult:
        return VoiceTurnResult(replies=[])

    def add_assistant_message(self, content: str) -> None:
        return None

    def on_user_text(self, content: str) -> VoiceTurnResult:
        _ = content
        if self._initial_briefing_sent:
            return VoiceTurnResult(
                replies=["Danke. Weitere Updates folgen, falls noch etwas hinzukommt."],
                completed=True,
            )

        self._initial_briefing_sent = True
        return VoiceTurnResult(
            replies=[build_dispatch_call_script(self._context.event, self._context.service)],
            completed=True,
        )

    @staticmethod
    def _load_context(*, event_id: int, service: DispatchServiceKey) -> DispatchCallContext:
        with SessionLocal() as db:
            event = db.get(models.Event, event_id)
            if event is None:
                raise ValueError(f"Event {event_id} not found for outbound {service} call")

            detached_event = EmergencyCallOrchestrator._detach_event(db, event)
            return DispatchCallContext(event=detached_event, service=service)

    @staticmethod
    def _detach_event(db: Session, event: models.Event) -> models.Event:
        db.expunge(event)
        return event
