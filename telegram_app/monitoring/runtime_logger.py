"""File-backed structured monitoring for the Telegram-native runtime."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from threading import RLock
from typing import Any, Protocol
from uuid import uuid4

from telegram_app.models import ApprovalRecord, SessionRecord
from telegram_app.monitoring.runtime_events import (
    RuntimeTraceContext,
    summarize_approval,
    summarize_session,
    summarize_update,
)
from telegram_app.transport import TelegramUpdate

MAX_STRING_LENGTH = 4000
MAX_LIST_ITEMS = 25
MAX_DICT_ITEMS = 50
MAX_DEPTH = 6


class RuntimeEventLogger(Protocol):
    """Persistence contract for structured runtime events."""

    def record_event(
        self,
        *,
        component: str,
        event_type: str,
        trace_context: RuntimeTraceContext | None = None,
        session: SessionRecord | None = None,
        approval: ApprovalRecord | None = None,
        update: TelegramUpdate | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Persist one structured runtime event."""


class NullRuntimeEventLogger:
    """No-op logger for tests or callers that do not need runtime monitoring."""

    def record_event(
        self,
        *,
        component: str,
        event_type: str,
        trace_context: RuntimeTraceContext | None = None,
        session: SessionRecord | None = None,
        approval: ApprovalRecord | None = None,
        update: TelegramUpdate | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        return None


class JsonlRuntimeEventLogger:
    """Append structured runtime events to a local JSONL file."""

    def __init__(self, file_path: str | Path) -> None:
        self._file_path = Path(file_path)
        self._lock = RLock()
        self._file_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        """Expose the backing file path for diagnostics and tests."""
        return self._file_path

    def record_event(
        self,
        *,
        component: str,
        event_type: str,
        trace_context: RuntimeTraceContext | None = None,
        session: SessionRecord | None = None,
        approval: ApprovalRecord | None = None,
        update: TelegramUpdate | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        event = {
            "event_id": str(uuid4()),
            "recorded_at": datetime.now(UTC).isoformat(),
            "component": component,
            "event_type": event_type,
            "trace": _sanitize_value(_build_trace_payload(trace_context), depth=0),
            "session": _sanitize_value(summarize_session(session), depth=0),
            "approval": _sanitize_value(summarize_approval(approval), depth=0),
            "update": _sanitize_value(summarize_update(update), depth=0),
            "payload": _sanitize_value(payload or {}, depth=0),
        }

        with self._lock:
            with self._file_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=True, sort_keys=True, default=str))
                handle.write("\n")


def _build_trace_payload(trace_context: RuntimeTraceContext | None) -> dict[str, str]:
    if trace_context is None:
        return {}
    return {
        "trace_id": trace_context.trace_id,
        "chat_id": trace_context.chat_id,
        "user_id": trace_context.user_id,
        "session_id": trace_context.session_id,
        "workflow_stage": trace_context.workflow_stage,
    }


def _sanitize_value(value: Any, *, depth: int) -> Any:
    if depth >= MAX_DEPTH:
        return "<max_depth_reached>"

    if value is None or isinstance(value, (bool, int, float)):
        return value

    if isinstance(value, str):
        return value if len(value) <= MAX_STRING_LENGTH else f"{value[:MAX_STRING_LENGTH]}...[truncated]"

    if isinstance(value, list):
        items = value[:MAX_LIST_ITEMS]
        sanitized = [_sanitize_value(item, depth=depth + 1) for item in items]
        if len(value) > MAX_LIST_ITEMS:
            sanitized.append(f"...[{len(value) - MAX_LIST_ITEMS} more items]")
        return sanitized

    if isinstance(value, tuple):
        return _sanitize_value(list(value), depth=depth + 1)

    if isinstance(value, dict):
        sanitized_dict: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= MAX_DICT_ITEMS:
                sanitized_dict["..."] = f"{len(value) - MAX_DICT_ITEMS} more keys"
                break
            sanitized_dict[str(key)] = _sanitize_value(item, depth=depth + 1)
        return sanitized_dict

    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except TypeError:
            return str(value)

    return str(value)
