"""Session path and client construction helpers for Telethon-backed accounts."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

ClientFactory = Callable[[str, int, str], Any]


def _default_client_factory(session_path: str, api_id: int, api_hash: str) -> Any:
    """Create a Telethon client lazily so local tests do not require the dependency."""
    from telethon import TelegramClient

    return TelegramClient(session=session_path, api_id=api_id, api_hash=api_hash)


class TelethonSessionManager:
    """Resolve session file locations and build per-account Telethon clients."""

    def __init__(
        self,
        sessions_dir: str | Path,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self._sessions_dir = Path(sessions_dir)
        self._client_factory = client_factory or _default_client_factory
        self._ensure_session_dir()

    @property
    def sessions_dir(self) -> Path:
        """Expose the root session directory for diagnostics."""
        return self._sessions_dir

    def resolve_session_path(self, account_id: str) -> Path:
        """Return the local Telethon session path for an account."""
        safe_account_id = "".join(
            character if character.isalnum() or character in {"-", "_"} else "_"
            for character in account_id.strip()
        )
        return self._sessions_dir / safe_account_id

    def build_client(self, account_id: str, api_id: int, api_hash: str) -> Any:
        """Instantiate a Telethon client for one account."""
        session_path = self.resolve_session_path(account_id)
        return self._client_factory(str(session_path), api_id, api_hash)

    def delete_session_file(self, account_id: str) -> None:
        """Remove local Telethon session artifacts for a cancelled login."""
        session_path = self.resolve_session_path(account_id)
        candidate_paths = [
            session_path,
            session_path.with_suffix(".session"),
            session_path.with_suffix(".session-journal"),
        ]
        for candidate in candidate_paths:
            if candidate.exists():
                candidate.unlink()

    def _ensure_session_dir(self) -> None:
        self._sessions_dir.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            self._sessions_dir.chmod(0o700)
