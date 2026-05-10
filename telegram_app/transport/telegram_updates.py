"""Normalized inbound Telegram update models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class TelegramUpdate:
    """Normalized subset of a Telegram update used by the runtime."""

    chat_id: str
    user_id: str
    text: str
    command: str | None = None
    raw_update: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "TelegramUpdate":
        """Create an update from a Telegram-like payload."""
        message = payload.get("message", {})
        chat = message.get("chat", {})
        sender = message.get("from", {})
        text = message.get("text", "") or ""
        command = text.split(maxsplit=1)[0] if text.startswith("/") else None
        return cls(
            chat_id=str(chat.get("id", "")),
            user_id=str(sender.get("id", "")),
            text=text,
            command=command,
            raw_update=payload,
        )

