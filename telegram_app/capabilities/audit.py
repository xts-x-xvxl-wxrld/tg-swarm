"""Audit-related capability contracts."""

from __future__ import annotations

from typing import Protocol

from telegram_app.capabilities.base import CapabilityResult


class AuditCapability(Protocol):
    """Operations for recording Telegram-domain actions."""

    def record_event(self, category: str, payload: dict[str, object]) -> CapabilityResult:
        """Record an auditable Telegram event."""

