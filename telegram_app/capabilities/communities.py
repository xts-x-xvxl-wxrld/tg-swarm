"""Community-related capability contracts."""

from __future__ import annotations

from typing import Protocol

from telegram_app.capabilities.base import CapabilityResult


class CommunityCapability(Protocol):
    """Operations for discovering and profiling Telegram communities."""

    def search(self, query: str) -> CapabilityResult:
        """Search for communities matching a query."""

    def get_profile(self, community_id: str) -> CapabilityResult:
        """Return profile details for a community."""

