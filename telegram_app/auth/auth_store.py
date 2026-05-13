"""Persistence for operator-driven account onboarding state."""

from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Protocol

from telegram_app.auth.models import PendingAuthState
from telegram_app.json_store import load_json_file, write_json_file


class AuthStateStore(Protocol):
    """Persistence contract for pending auth state."""

    def create(self, state: PendingAuthState) -> PendingAuthState:
        """Persist a new auth state."""

    def update(self, state: PendingAuthState) -> PendingAuthState:
        """Persist a mutated auth state."""

    def get_active_for_operator(self, operator_id: str) -> PendingAuthState | None:
        """Return the active auth flow for an operator, if present."""


class InMemoryAuthStateStore:
    """Simple in-memory store for onboarding flow tests."""

    def __init__(self) -> None:
        self._states: dict[str, PendingAuthState] = {}
        self._active_auth_ids: dict[str, str] = {}

    def create(self, state: PendingAuthState) -> PendingAuthState:
        self._states[state.auth_id] = state
        self._active_auth_ids[state.operator_id] = state.auth_id
        return state

    def update(self, state: PendingAuthState) -> PendingAuthState:
        self._states[state.auth_id] = state
        if state.step.is_terminal:
            self._active_auth_ids.pop(state.operator_id, None)
        else:
            self._active_auth_ids[state.operator_id] = state.auth_id
        return state

    def get_active_for_operator(self, operator_id: str) -> PendingAuthState | None:
        auth_id = self._active_auth_ids.get(operator_id)
        if auth_id is None:
            return None
        return self._states.get(auth_id)


class JsonAuthStateStore:
    """File-backed store so onboarding survives restarts."""

    def __init__(self, file_path: str | Path) -> None:
        self._file_path = Path(file_path)
        self._lock = RLock()
        self._states: dict[str, PendingAuthState] = {}
        self._active_auth_ids: dict[str, str] = {}
        self._load()

    def create(self, state: PendingAuthState) -> PendingAuthState:
        with self._lock:
            self._states[state.auth_id] = state
            self._active_auth_ids[state.operator_id] = state.auth_id
            self._persist()
            return state

    def update(self, state: PendingAuthState) -> PendingAuthState:
        with self._lock:
            self._states[state.auth_id] = state
            if state.step.is_terminal:
                self._active_auth_ids.pop(state.operator_id, None)
            else:
                self._active_auth_ids[state.operator_id] = state.auth_id
            self._persist()
            return state

    def get_active_for_operator(self, operator_id: str) -> PendingAuthState | None:
        with self._lock:
            auth_id = self._active_auth_ids.get(operator_id)
            if auth_id is None:
                return None
            return self._states.get(auth_id)

    def _load(self) -> None:
        payload = load_json_file(
            self._file_path,
            default={"states": {}, "active_auth_ids": {}},
        )
        raw_states = payload.get("states", {})
        raw_active_auth_ids = payload.get("active_auth_ids", {})
        if not isinstance(raw_states, dict):
            raw_states = {}
        if not isinstance(raw_active_auth_ids, dict):
            raw_active_auth_ids = {}

        self._states = {
            auth_id: PendingAuthState.from_dict(state_payload)
            for auth_id, state_payload in raw_states.items()
            if isinstance(state_payload, dict)
        }
        self._active_auth_ids = {
            operator_id: str(auth_id)
            for operator_id, auth_id in raw_active_auth_ids.items()
        }

    def _persist(self) -> None:
        payload = {
            "states": {
                auth_id: state.to_dict()
                for auth_id, state in self._states.items()
            },
            "active_auth_ids": dict(self._active_auth_ids),
        }
        write_json_file(self._file_path, payload)
