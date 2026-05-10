"""Account-related capability contracts."""

from __future__ import annotations

from typing import Protocol

from telegram_app.capabilities.base import CapabilityResult


class AccountCapability(Protocol):
    """Operations for Telegram account inventory and health."""

    def list_accounts(self) -> CapabilityResult:
        """Return known Telegram accounts."""

    def get_account(self, account_id: str) -> CapabilityResult:
        """Return details for one Telegram account."""

