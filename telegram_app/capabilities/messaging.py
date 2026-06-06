"""Messaging-related capability contracts."""

from __future__ import annotations

from typing import Protocol

from telegram_app.capabilities.base import CapabilityResult


class MessagingCapability(Protocol):
    """Operations for reading and sending Telegram messages."""

    def read_messages(self, chat_id: str, limit: int = 20) -> CapabilityResult:
        """Read recent messages from a chat."""

    def send_message(
        self,
        account_id: str,
        chat_id: str,
        text: str,
        *,
        approval_context: dict[str, object] | None = None,
    ) -> CapabilityResult:
        """Send a message to a chat from a specific Telegram account."""

    def send_reply(
        self,
        account_id: str,
        chat_id: str,
        reply_to_message_id: str | int,
        text: str,
        *,
        approval_context: dict[str, object] | None = None,
    ) -> CapabilityResult:
        """Send a reply to a specific Telegram message from a managed account."""

    def mark_read(
        self,
        account_id: str,
        chat_id: str,
        message_id: str | int | None = None,
    ) -> CapabilityResult:
        """Mark one dialog or message range as read for a managed account."""

    def get_dialog_history(
        self,
        account_id: str,
        peer_id: str,
        limit: int = 20,
    ) -> CapabilityResult:
        """Read bounded dialog history for one managed account and peer."""

    def list_recent_dialogs(
        self,
        account_id: str,
        limit: int = 20,
    ) -> CapabilityResult:
        """List a bounded recent-dialog view for one managed account."""

    def leave_dialog(self, account_id: str, peer_id: str) -> CapabilityResult:
        """Leave or exit one dialog for a managed account."""
