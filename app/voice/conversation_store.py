from __future__ import annotations

from datetime import datetime, timezone
from threading import RLock
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConversationStore:
    """In-memory store for latest voice conversation transcript + derived event."""

    def __init__(self):
        self._lock = RLock()
        self._sessions: dict[str, dict[str, Any]] = {}
        self._latest_session_id: str | None = None

    def start_session(self, session_id: str) -> None:
        with self._lock:
            now = _utc_now_iso()
            self._sessions[session_id] = {
                "session_id": session_id,
                "status": "collecting",
                "created_at": now,
                "updated_at": now,
                "messages": [],
                "slots": {
                    "driver_name": None,
                    "train_number": None,
                    "description": None,
                    "location": None,
                    "people_hurt": None,
                    "dispatch_targets": None,
                },
                "event": None,
            }
            self._latest_session_id = session_id

    def add_message(self, session_id: str, role: str, text: str) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                self.start_session(session_id)
                session = self._sessions[session_id]
            session["messages"].append(
                {
                    "role": role,
                    "text": text,
                    "timestamp": _utc_now_iso(),
                }
            )
            session["updated_at"] = _utc_now_iso()
            self._latest_session_id = session_id

    def update_slots(self, session_id: str, updates: dict[str, Any]) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                self.start_session(session_id)
                session = self._sessions[session_id]
            session["slots"].update(updates)
            session["updated_at"] = _utc_now_iso()

    def set_status(self, session_id: str, status: str) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return
            session["status"] = status
            session["updated_at"] = _utc_now_iso()

    def set_event(self, session_id: str, event_payload: dict[str, Any]) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return
            session["event"] = event_payload
            session["status"] = "completed"
            session["updated_at"] = _utc_now_iso()

    def get_latest_snapshot(self) -> dict[str, Any]:
        with self._lock:
            if not self._latest_session_id or self._latest_session_id not in self._sessions:
                return {
                    "session_id": None,
                    "status": "idle",
                    "messages": [],
                    "slots": {},
                    "event": None,
                }
            session = self._sessions[self._latest_session_id]
            return {
                "session_id": session["session_id"],
                "status": session["status"],
                "created_at": session["created_at"],
                "updated_at": session["updated_at"],
                "messages": [dict(item) for item in session["messages"]],
                "slots": dict(session["slots"]),
                "event": dict(session["event"]) if isinstance(session["event"], dict) else None,
            }


conversation_store = ConversationStore()
