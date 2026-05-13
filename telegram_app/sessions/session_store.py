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

    def list_for_campaign(self, campaign_id: str) -> list[SessionRecord]:
        """Return all sessions attached to a campaign."""


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

    def list_for_campaign(self, campaign_id: str) -> list[SessionRecord]:
        return [session for session in self._sessions.values() if session.campaign_id == campaign_id]


class JsonSessionStore:
    """File-backed session store that preserves runtime state across restarts."""

    def __init__(self, file_path: str | Path) -> None:
        self._file_path = Path(file_path)
        self._sessions_dir = self._file_path.parent / "sessions"
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

    def list_for_campaign(self, campaign_id: str) -> list[SessionRecord]:
        with self._lock:
            return [session for session in self._sessions.values() if session.campaign_id == campaign_id]

    def _load(self) -> None:
        payload = load_json_file(
            self._file_path,
            default={"active_session_ids": {}},
        )
        raw_sessions = payload.get("sessions", {})
        raw_active_session_ids = payload.get("active_session_ids", {})
        if not isinstance(raw_active_session_ids, dict):
            raw_active_session_ids = {}

        migrated_legacy_sessions = isinstance(raw_sessions, dict) and bool(raw_sessions)
        if migrated_legacy_sessions:
            self._migrate_legacy_sessions(raw_sessions)

        self._sessions = self._load_session_files()
        self._active_session_ids = {
            operator_id: str(session_id)
            for operator_id, session_id in raw_active_session_ids.items()
        }
        if migrated_legacy_sessions:
            self._persist()

    def _persist(self) -> None:
        self._sessions_dir.mkdir(parents=True, exist_ok=True)
        for session_id, session in self._sessions.items():
            write_json_file(self._sessions_dir / f"{session_id}.json", session.to_dict())

        payload = {"active_session_ids": dict(self._active_session_ids)}
        write_json_file(self._file_path, payload)

    def _load_session_files(self) -> dict[str, SessionRecord]:
        if not self._sessions_dir.exists():
            return {}

        sessions: dict[str, SessionRecord] = {}
        for session_path in self._sessions_dir.glob("*.json"):
            session_payload = load_json_file(session_path, default={})
            if not isinstance(session_payload, dict):
                continue
            session = SessionRecord.from_dict(session_payload)
            if session.session_id:
                sessions[session.session_id] = session
        return sessions

    def _migrate_legacy_sessions(self, raw_sessions: dict[str, object]) -> None:
        self._sessions_dir.mkdir(parents=True, exist_ok=True)
        for session_id, session_payload in raw_sessions.items():
            if not isinstance(session_payload, dict):
                continue
            write_json_file(self._sessions_dir / f"{session_id}.json", session_payload)
