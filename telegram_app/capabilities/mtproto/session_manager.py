"""Session path and client construction helpers for Telethon-backed accounts."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
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
        session_namespace: str = "",
    ) -> None:
        self._sessions_dir = Path(sessions_dir)
        self._client_factory = client_factory or _default_client_factory
        self._session_namespace = self._normalize_namespace(
            session_namespace or os.getenv("TG_SWARM_MTPROTO_SESSION_NAMESPACE", "")
        )
        self._ensure_session_dir()

    @property
    def sessions_dir(self) -> Path:
        """Expose the root session directory for diagnostics."""
        return self._sessions_dir

    @property
    def session_namespace(self) -> str:
        """Expose the optional per-process session namespace for diagnostics."""
        return self._session_namespace

    def resolve_canonical_session_path(self, account_id: str) -> Path:
        """Return the canonical shared Telethon session path for an account."""
        return self._sessions_dir / self._safe_account_id(account_id)

    def resolve_session_path(self, account_id: str) -> Path:
        """Return the role-local Telethon session path for an account."""
        canonical_path = self.resolve_canonical_session_path(account_id)
        if not self._session_namespace:
            return canonical_path
        return self._sessions_dir / f"{canonical_path.name}__{self._session_namespace}"

    def build_client(self, account_id: str, api_id: int, api_hash: str) -> Any:
        """Instantiate a Telethon client for one account."""
        self._ensure_local_session_copy(account_id)
        session_path = self.resolve_session_path(account_id)
        return self._client_factory(str(session_path), api_id, api_hash)

    def delete_session_file(self, account_id: str) -> None:
        """Remove local Telethon session artifacts for a cancelled login."""
        safe_account_id = self._safe_account_id(account_id)
        candidate_paths = {
            self.resolve_canonical_session_path(account_id),
            self.resolve_canonical_session_path(account_id).with_suffix(".session"),
            self.resolve_canonical_session_path(account_id).with_suffix(".session-journal"),
            self.resolve_session_path(account_id),
            self.resolve_session_path(account_id).with_suffix(".session"),
            self.resolve_session_path(account_id).with_suffix(".session-journal"),
        }
        for namespaced_path in self._sessions_dir.glob(f"{safe_account_id}__*"):
            candidate_paths.add(namespaced_path)
            candidate_paths.add(namespaced_path.with_suffix(".session"))
            candidate_paths.add(namespaced_path.with_suffix(".session-journal"))
        for candidate in candidate_paths:
            if candidate.exists():
                candidate.unlink()

    def _ensure_session_dir(self) -> None:
        self._sessions_dir.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            self._sessions_dir.chmod(0o700)

    def _ensure_local_session_copy(self, account_id: str) -> None:
        if not self._session_namespace:
            return
        canonical_path = self.resolve_canonical_session_path(account_id)
        local_path = self.resolve_session_path(account_id)
        for canonical_candidate, local_candidate in self._session_artifact_pairs(canonical_path, local_path):
            if not canonical_candidate.exists():
                continue
            if local_candidate.exists():
                canonical_stat = canonical_candidate.stat()
                local_stat = local_candidate.stat()
                if local_stat.st_mtime_ns >= canonical_stat.st_mtime_ns:
                    continue
            local_candidate.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(canonical_candidate, local_candidate)

    def _session_artifact_pairs(self, canonical_path: Path, local_path: Path) -> list[tuple[Path, Path]]:
        return [
            (canonical_path, local_path),
            (canonical_path.with_suffix(".session"), local_path.with_suffix(".session")),
            (canonical_path.with_suffix(".session-journal"), local_path.with_suffix(".session-journal")),
        ]

    def _safe_account_id(self, account_id: str) -> str:
        return "".join(
            character if character.isalnum() or character in {"-", "_"} else "_"
            for character in account_id.strip()
        )

    def _normalize_namespace(self, value: str) -> str:
        normalized = "".join(
            character.lower()
            for character in value.strip()
            if character.isalnum() or character in {"-", "_"}
        )
        return normalized
