"""Messaging-related capability contracts."""

from __future__ import annotations

from typing import Protocol

from telegram_app.capabilities.base import CapabilityResult


class MessagingCapability(Protocol):
    """Operations for reading and sending Telegram messages."""

    def read_messages(self, chat_id: str, limit: int = 20) -> CapabilityResult:
        """Read recent messages from a chat."""

    def send_message(self, chat_id: str, text: str) -> CapabilityResult:
        """Send a message to a chat."""

