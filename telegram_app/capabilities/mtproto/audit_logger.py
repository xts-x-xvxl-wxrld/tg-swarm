"""Lightweight file-backed audit logging for MTProto write actions."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from telegram_app.capabilities.base import CapabilityResult


class JsonlAuditLogger:
    """Append structured audit events to a local JSONL file."""

    def __init__(self, file_path: str | Path) -> None:
        self._file_path = Path(file_path)
        self._lock = RLock()
        self._file_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        """Expose the backing audit path for diagnostics."""
        return self._file_path

    def record_event(self, category: str, payload: dict[str, object]) -> CapabilityResult:
        event = {
            "event_id": str(uuid4()),
            "category": category,
            "recorded_at": datetime.now(UTC).isoformat(),
            "payload": payload,
        }

        with self._lock:
            with self._file_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=True, sort_keys=True, default=str))
                handle.write("\n")

        return CapabilityResult(
            success=True,
            data={"event": event},
            audit={"implementation": "jsonl_audit_logger", "path": str(self._file_path)},
        )
