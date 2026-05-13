"""Membership capability implementation backed by Telethon."""

from __future__ import annotations

from typing import Any

from telegram_app.capabilities.base import CapabilityResult
from telegram_app.capabilities.mtproto.audit_logger import JsonlAuditLogger
from telegram_app.capabilities.mtproto.client import TelethonClientWrapper
from telegram_app.capabilities.mtproto.error_classifier import classify_mtproto_exception
from telegram_app.capabilities.mtproto.registry import AccountRegistry


class MembershipCapabilityImpl:
    """Handle Telegram join reads and writes behind capability boundaries."""

    def __init__(
        self,
        registry: AccountRegistry,
        client_wrapper: TelethonClientWrapper,
        *,
        audit_logger: JsonlAuditLogger | None = None,
    ) -> None:
        self._registry = registry
        self._client_wrapper = client_wrapper
        self._audit_logger = audit_logger

    def get_membership(self, account_id: str, community_id: str) -> CapabilityResult:
        account = self._registry.get_account(account_id)
        if account is None:
            return CapabilityResult(
                success=False,
                data={"account_id": account_id, "community_id": community_id, "source": "telethon"},
                audit={"implementation": "mtproto_membership_capability", "action": "get_membership"},
                error=f"Unknown Telegram account: {account_id}",
            )

        available, error = self._client_wrapper.is_available()
        if not available:
            return CapabilityResult(
                success=False,
                data={"account_id": account_id, "community_id": community_id, "source": "telethon"},
                audit={"implementation": "mtproto_membership_capability", "action": "get_membership"},
                error=error,
            )

        try:
            membership_state = self._client_wrapper.run(
                account_id,
                lambda client: self._get_membership_async(client, community_id),
            )
        except Exception as exc:
            return CapabilityResult(
                success=False,
                data={"account_id": account_id, "community_id": community_id, "source": "telethon"},
                audit={"implementation": "mtproto_membership_capability", "action": "get_membership"},
                error=f"Telegram membership lookup failed: {exc}",
            )

        return CapabilityResult(
            success=True,
            data={
                "account_id": account_id,
                "community_id": community_id,
                "membership": membership_state,
                "source": "telethon",
            },
            audit={"implementation": "mtproto_membership_capability", "action": "get_membership"},
        )

    def join(self, account_id: str, community_id: str) -> CapabilityResult:
        can_join, reason = self._registry.can_join(account_id)
        if not can_join:
            result = CapabilityResult(
                success=False,
                data={"account_id": account_id, "community_id": community_id, "source": "telethon"},
                audit={"implementation": "mtproto_membership_capability", "action": "join"},
                error=reason,
            )
            self._record_audit_event("membership_join_blocked", result)
            return result

        available, error = self._client_wrapper.is_available()
        if not available:
            result = CapabilityResult(
                success=False,
                data={"account_id": account_id, "community_id": community_id, "source": "telethon"},
                audit={"implementation": "mtproto_membership_capability", "action": "join"},
                error=error,
            )
            self._record_audit_event("membership_join_unavailable", result)
            return result

        max_attempts = 2
        for attempt in range(1, max_attempts + 1):
            try:
                join_data = self._client_wrapper.run(
                    account_id,
                    lambda client: self._join_async(client, community_id),
                )
                self._registry.mark_join_success(account_id, community_id=community_id)
                result = CapabilityResult(
                    success=True,
                    data={
                        **join_data,
                        "account_id": account_id,
                        "community_id": community_id,
                        "attempts": attempt,
                        "source": "telethon",
                    },
                    audit={"implementation": "mtproto_membership_capability", "action": "join"},
                )
                self._record_audit_event("membership_join_succeeded", result)
                return result
            except Exception as exc:
                error = classify_mtproto_exception(exc, action="joining the community")
                if error.already_satisfied:
                    self._registry.mark_join_success(account_id, community_id=community_id)
                    result = CapabilityResult(
                        success=True,
                        data={
                            "account_id": account_id,
                            "community_id": community_id,
                            "already_member": True,
                            "attempts": attempt,
                            "source": "telethon",
                        },
                        audit={"implementation": "mtproto_membership_capability", "action": "join"},
                    )
                    self._record_audit_event("membership_join_already_member", result)
                    return result

                if error.retriable and attempt < max_attempts:
                    continue

                self._registry.mark_join_failure(
                    account_id,
                    community_id=community_id,
                    health=error.health,
                    wait_seconds=error.wait_seconds,
                    error=error.message,
                    outcome=error.code,
                )
                result = CapabilityResult(
                    success=False,
                    data={
                        "account_id": account_id,
                        "community_id": community_id,
                        "attempts": attempt,
                        "wait_seconds": error.wait_seconds,
                        "source": "telethon",
                    },
                    audit={"implementation": "mtproto_membership_capability", "action": "join"},
                    error=error.message,
                )
                self._record_audit_event("membership_join_failed", result)
                return result

        result = CapabilityResult(
            success=False,
            data={"account_id": account_id, "community_id": community_id, "source": "telethon"},
            audit={"implementation": "mtproto_membership_capability", "action": "join"},
            error="Telegram community join failed without a final result.",
        )
        self._record_audit_event("membership_join_failed", result)
        return result

    async def _get_membership_async(self, client: Any, community_id: str) -> dict[str, Any]:
        entity = await client.get_entity(community_id)
        state = "member"

        try:
            await client.get_permissions(entity, "me")
        except Exception as exc:
            if exc.__class__.__name__ == "UserNotParticipantError":
                state = "not_member"
            else:
                raise

        return {
            "community_id": str(getattr(entity, "id", community_id)),
            "community_name": getattr(entity, "title", "") or getattr(entity, "username", ""),
            "state": state,
        }

    async def _join_async(self, client: Any, community_id: str) -> dict[str, Any]:
        from telethon.tl.functions.channels import JoinChannelRequest

        result = await client(JoinChannelRequest(channel=community_id))
        return {
            "raw_updates_type": result.__class__.__name__,
        }

    def _record_audit_event(self, category: str, result: CapabilityResult) -> None:
        if self._audit_logger is None:
            return
        self._audit_logger.record_event(
            category,
            {
                "success": result.success,
                "data": result.data,
                "audit": result.audit,
                "error": result.error,
            },
        )
