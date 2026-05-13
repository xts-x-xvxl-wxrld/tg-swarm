"""Outbound Telegram response models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class TelegramMessage:
    """Single outbound Telegram message payload."""

    text: str
    reply_markup: dict[str, Any] | None = None


@dataclass(slots=True)
class TelegramResponse:
    """Collection of outbound messages for a chat."""

    chat_id: str
    messages: list[TelegramMessage] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def single(cls, chat_id: str, text: str) -> "TelegramResponse":
        """Create a response with one plain-text message."""
        return cls(chat_id=chat_id, messages=[TelegramMessage(text=text)])
