"""Membership-related capability contracts."""

from __future__ import annotations

from typing import Protocol

from telegram_app.capabilities.base import CapabilityResult


class MembershipCapability(Protocol):
    """Operations for community membership state and changes."""

    def get_membership(self, account_id: str, community_id: str) -> CapabilityResult:
        """Return membership state for an account-community pair."""

    def join(self, account_id: str, community_id: str) -> CapabilityResult:
        """Join a community with a given account."""

