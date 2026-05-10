"""Session persistence contracts."""

from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Protocol

from telegram_app.json_store import load_json_file, write_json_file
from telegram_app.models import SessionRecord


class SessionStore(Protocol):
    """Persistence contract for operator sessions."""

    def create(self, session: SessionRecord) -> SessionRecord:
        """Persist a new session."""

    def get(self, session_id: str) -> SessionRecord | None:
        """Fetch a session by id."""

    def update(self, session: SessionRecord) -> SessionRecord:
        """Persist a mutated session."""

    def get_active_for_operator(self, operator_id: str) -> SessionRecord | None:
        """Return the latest active session for an operator."""


class InMemorySessionStore:
    """Simple in-memory store for early control-path development."""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionRecord] = {}
        self._active_session_ids: dict[str, str] = {}

    def create(self, session: SessionRecord) -> SessionRecord:
        self._sessions[session.session_id] = session
        self._active_session_ids[session.operator_id] = session.session_id
        return session

    def get(self, session_id: str) -> SessionRecord | None:
        return self._sessions.get(session_id)

    def update(self, session: SessionRecord) -> SessionRecord:
        self._sessions[session.session_id] = session
        self._active_session_ids[session.operator_id] = session.session_id
        return session

    def get_active_for_operator(self, operator_id: str) -> SessionRecord | None:
        session_id = self._active_session_ids.get(operator_id)
        if session_id is None:
            return None
        return self._sessions.get(session_id)


class JsonSessionStore:
    """File-backed session store that preserves runtime state across restarts."""

    def __init__(self, file_path: str | Path) -> None:
        self._file_path = Path(file_path)
        self._lock = RLock()
        self._sessions: dict[str, SessionRecord] = {}
        self._active_session_ids: dict[str, str] = {}
        self._load()

    def create(self, session: SessionRecord) -> SessionRecord:
        with self._lock:
            self._sessions[session.session_id] = session
            self._active_session_ids[session.operator_id] = session.session_id
            self._persist()
            return session

    def get(self, session_id: str) -> SessionRecord | None:
        with self._lock:
            return self._sessions.get(session_id)

    def update(self, session: SessionRecord) -> SessionRecord:
        with self._lock:
            self._sessions[session.session_id] = session
            self._active_session_ids[session.operator_id] = session.session_id
            self._persist()
            return session

    def get_active_for_operator(self, operator_id: str) -> SessionRecord | None:
        with self._lock:
            session_id = self._active_session_ids.get(operator_id)
            if session_id is None:
                return None
            return self._sessions.get(session_id)

    def _load(self) -> None:
        payload = load_json_file(
            self._file_path,
            default={"sessions": {}, "active_session_ids": {}},
        )
        raw_sessions = payload.get("sessions", {})
        raw_active_session_ids = payload.get("active_session_ids", {})
        if not isinstance(raw_sessions, dict):
            raw_sessions = {}
        if not isinstance(raw_active_session_ids, dict):
            raw_active_session_ids = {}

        self._sessions = {
            session_id: SessionRecord.from_dict(session_payload)
            for session_id, session_payload in raw_sessions.items()
            if isinstance(session_payload, dict)
        }
        self._active_session_ids = {
            operator_id: str(session_id)
            for operator_id, session_id in raw_active_session_ids.items()
        }

    def _persist(self) -> None:
        payload = {
            "sessions": {
                session_id: session.to_dict()
                for session_id, session in self._sessions.items()
            },
            "active_session_ids": dict(self._active_session_ids),
        }
        write_json_file(self._file_path, payload)
