"""Stub capability implementations used before MTProto is wired in."""

from __future__ import annotations

from typing import Final

from telegram_app.capabilities.base import CapabilityResult

_PLACEHOLDER_ACCOUNTS: Final[list[dict[str, str]]] = [
    {
        "account_id": "account_senior_1",
        "tier": "senior",
        "health": "active",
        "language": "en",
        "geography": "global",
    },
    {
        "account_id": "account_standard_1",
        "tier": "standard",
        "health": "active",
        "language": "en",
        "geography": "global",
    },
    {
        "account_id": "account_new_1",
        "tier": "new",
        "health": "warming_up",
        "language": "en",
        "geography": "global",
    },
]


class StubCommunityCapability:
    """Placeholder community capability for pre-MTProto development."""

    def search(self, query: str, *, mode: str = "exact", limit: int = 10) -> CapabilityResult:
        return CapabilityResult(
            success=False,
            data={
                "query": query,
                "mode": mode,
                "limit": limit,
                "results": [],
                "source": "stub",
            },
            audit={"implementation": "stub_community_capability"},
            error="Live community search is not implemented yet.",
        )

    def get_profile(self, community_id: str) -> CapabilityResult:
        return CapabilityResult(
            success=False,
            data={
                "community_id": community_id,
                "source": "stub",
            },
            audit={"implementation": "stub_community_capability"},
            error="Live community profiling is not implemented yet.",
        )


class StubAccountCapability:
    """Placeholder account capability that exposes a deterministic roster."""

    def list_accounts(self) -> CapabilityResult:
        return CapabilityResult(
            success=True,
            data={
                "accounts": list(_PLACEHOLDER_ACCOUNTS),
                "source": "stub",
            },
            audit={"implementation": "stub_account_capability"},
        )

    def get_account(self, account_id: str) -> CapabilityResult:
        for account in _PLACEHOLDER_ACCOUNTS:
            if account["account_id"] == account_id:
                return CapabilityResult(
                    success=True,
                    data={
                        "account": dict(account),
                        "source": "stub",
                    },
                    audit={"implementation": "stub_account_capability"},
                )

        return CapabilityResult(
            success=False,
            data={
                "account_id": account_id,
                "source": "stub",
            },
            audit={"implementation": "stub_account_capability"},
            error=f"Unknown stub account: {account_id}",
        )


class StubMembershipCapability:
    """Placeholder membership capability for approval-gated join work."""

    def get_membership(self, account_id: str, community_id: str) -> CapabilityResult:
        return CapabilityResult(
            success=False,
            data={
                "account_id": account_id,
                "community_id": community_id,
                "source": "stub",
            },
            audit={"implementation": "stub_membership_capability"},
            error="Live membership lookups are not implemented yet.",
        )

    def join(self, account_id: str, community_id: str) -> CapabilityResult:
        return CapabilityResult(
            success=False,
            data={
                "account_id": account_id,
                "community_id": community_id,
                "source": "stub",
            },
            audit={"implementation": "stub_membership_capability"},
            error="Live community joins are not implemented yet.",
        )


class StubMessagingCapability:
    """Placeholder messaging capability for pre-MTProto profiling work."""

    def read_messages(self, chat_id: str, limit: int = 20) -> CapabilityResult:
        return CapabilityResult(
            success=False,
            data={
                "chat_id": chat_id,
                "limit": limit,
                "messages": [],
                "source": "stub",
            },
            audit={"implementation": "stub_messaging_capability"},
            error="Live message reads are not implemented yet.",
        )

    def send_message(
        self,
        account_id: str,
        chat_id: str,
        text: str,
        *,
        approval_context: dict[str, object] | None = None,
    ) -> CapabilityResult:
        return CapabilityResult(
            success=False,
            data={
                "account_id": account_id,
                "chat_id": chat_id,
                "text": text,
                "approval_context": dict(approval_context or {}),
                "source": "stub",
            },
            audit={"implementation": "stub_messaging_capability"},
            error="Live message sends are not implemented yet.",
        )

    def send_reply(
        self,
        account_id: str,
        chat_id: str,
        reply_to_message_id: str | int,
        text: str,
        *,
        approval_context: dict[str, object] | None = None,
    ) -> CapabilityResult:
        return CapabilityResult(
            success=False,
            data={
                "account_id": account_id,
                "chat_id": chat_id,
                "reply_to_message_id": str(reply_to_message_id).strip(),
                "text": text,
                "approval_context": dict(approval_context or {}),
                "source": "stub",
            },
            audit={"implementation": "stub_messaging_capability"},
            error="Live reply sends are not implemented yet.",
        )

    def mark_read(
        self,
        account_id: str,
        chat_id: str,
        message_id: str | int | None = None,
    ) -> CapabilityResult:
        return CapabilityResult(
            success=False,
            data={
                "account_id": account_id,
                "chat_id": chat_id,
                "message_id": "" if message_id is None else str(message_id).strip(),
                "source": "stub",
            },
            audit={"implementation": "stub_messaging_capability"},
            error="Managed-account read-state updates are not implemented yet.",
        )

    def get_dialog_history(
        self,
        account_id: str,
        peer_id: str,
        limit: int = 20,
    ) -> CapabilityResult:
        return CapabilityResult(
            success=False,
            data={
                "account_id": account_id,
                "peer_id": peer_id,
                "limit": limit,
                "messages": [],
                "source": "stub",
            },
            audit={"implementation": "stub_messaging_capability"},
            error="Managed-account dialog history reads are not implemented yet.",
        )

    def list_recent_dialogs(
        self,
        account_id: str,
        limit: int = 20,
    ) -> CapabilityResult:
        return CapabilityResult(
            success=False,
            data={
                "account_id": account_id,
                "limit": limit,
                "dialogs": [],
                "source": "stub",
            },
            audit={"implementation": "stub_messaging_capability"},
            error="Managed-account dialog listing is not implemented yet.",
        )

    def leave_dialog(self, account_id: str, peer_id: str) -> CapabilityResult:
        return CapabilityResult(
            success=False,
            data={
                "account_id": account_id,
                "peer_id": peer_id,
                "source": "stub",
            },
            audit={"implementation": "stub_messaging_capability"},
            error="Managed-account dialog leave actions are not implemented yet.",
        )
