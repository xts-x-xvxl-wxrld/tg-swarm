"""Messaging capability implementation backed by Telethon."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from telegram_app.capabilities.base import CapabilityResult
from telegram_app.capabilities.mtproto.audit_logger import JsonlAuditLogger
from telegram_app.capabilities.mtproto.client import TelethonClientWrapper
from telegram_app.capabilities.mtproto.error_classifier import classify_mtproto_exception
from telegram_app.capabilities.mtproto.registry import AccountRegistry


def _isoformat_if_datetime(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return ""


class MessagingCapabilityImpl:
    """Read Telegram messages through the shared MTProto client wrapper."""

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

    def read_messages(self, chat_id: str, limit: int = 20) -> CapabilityResult:
        account = self._registry.resolve_default_read_account()
        if account is None:
            return CapabilityResult(
                success=False,
                data={"chat_id": chat_id, "limit": limit, "source": "telethon"},
                audit={"implementation": "mtproto_messaging_capability", "action": "read_messages"},
                error="No Telegram account is configured for live message reads.",
            )

        available, error = self._client_wrapper.is_available()
        if not available:
            return CapabilityResult(
                success=False,
                data={"chat_id": chat_id, "limit": limit, "source": "telethon"},
                audit={
                    "implementation": "mtproto_messaging_capability",
                    "action": "read_messages",
                    "account_id": account.account_id,
                },
                error=error,
            )

        try:
            messages = self._client_wrapper.run(
                account.account_id,
                lambda client: self._read_messages_async(client, chat_id, limit),
            )
        except Exception as exc:
            return CapabilityResult(
                success=False,
                data={"chat_id": chat_id, "limit": limit, "source": "telethon"},
                audit={
                    "implementation": "mtproto_messaging_capability",
                    "action": "read_messages",
                    "account_id": account.account_id,
                },
                error=f"Telegram message read failed: {exc}",
            )

        return CapabilityResult(
            success=True,
            data={"chat_id": chat_id, "limit": limit, "messages": messages, "source": "telethon"},
            audit={
                "implementation": "mtproto_messaging_capability",
                "action": "read_messages",
                "account_id": account.account_id,
            },
        )

    def send_message(
        self,
        account_id: str,
        chat_id: str,
        text: str,
        *,
        approval_context: dict[str, object] | None = None,
    ) -> CapabilityResult:
        approval_context = dict(approval_context or {})
        if not self._is_send_approved(approval_context):
            result = CapabilityResult(
                success=False,
                data={
                    "account_id": account_id,
                    "chat_id": chat_id,
                    "approval_context": approval_context,
                    "source": "telethon",
                },
                audit={"implementation": "mtproto_messaging_capability", "action": "send_message"},
                error="Live Telegram sends require explicit approved operator context.",
            )
            self._record_audit_event("message_send_blocked", result)
            return result

        can_send, reason = self._registry.can_send(account_id)
        if not can_send:
            result = CapabilityResult(
                success=False,
                data={"account_id": account_id, "chat_id": chat_id, "source": "telethon"},
                audit={"implementation": "mtproto_messaging_capability", "action": "send_message"},
                error=reason,
            )
            self._record_audit_event("message_send_blocked", result)
            return result

        available, error = self._client_wrapper.is_available()
        if not available:
            result = CapabilityResult(
                success=False,
                data={"account_id": account_id, "chat_id": chat_id, "source": "telethon"},
                audit={"implementation": "mtproto_messaging_capability", "action": "send_message"},
                error=error,
            )
            self._record_audit_event("message_send_unavailable", result)
            return result

        max_attempts = 2
        for attempt in range(1, max_attempts + 1):
            try:
                payload = self._client_wrapper.run(
                    account_id,
                    lambda client: self._send_message_async(client, chat_id, text),
                )
                self._registry.mark_send_success(account_id, chat_id=chat_id)
                result = CapabilityResult(
                    success=True,
                    data={
                        **payload,
                        "account_id": account_id,
                        "chat_id": chat_id,
                        "attempts": attempt,
                        "source": "telethon",
                    },
                    audit={"implementation": "mtproto_messaging_capability", "action": "send_message"},
                )
                self._record_audit_event("message_send_succeeded", result)
                return result
            except Exception as exc:
                error_details = classify_mtproto_exception(exc, action="sending a message")
                if error_details.retriable and attempt < max_attempts:
                    continue

                self._registry.mark_send_failure(
                    account_id,
                    chat_id=chat_id,
                    health=error_details.health,
                    wait_seconds=error_details.wait_seconds,
                    error=error_details.message,
                    outcome=error_details.code,
                )
                result = CapabilityResult(
                    success=False,
                    data={
                        "account_id": account_id,
                        "chat_id": chat_id,
                        "attempts": attempt,
                        "wait_seconds": error_details.wait_seconds,
                        "source": "telethon",
                    },
                    audit={"implementation": "mtproto_messaging_capability", "action": "send_message"},
                    error=error_details.message,
                )
                self._record_audit_event("message_send_failed", result)
                return result

        result = CapabilityResult(
            success=False,
            data={"account_id": account_id, "chat_id": chat_id, "source": "telethon"},
            audit={"implementation": "mtproto_messaging_capability", "action": "send_message"},
            error="Telegram message send failed without a final result.",
        )
        self._record_audit_event("message_send_failed", result)
        return result

    async def _read_messages_async(self, client: Any, chat_id: str, limit: int) -> list[dict[str, Any]]:
        history = await client.get_messages(chat_id, limit=limit)
        return [
            {
                "message_id": getattr(message, "id", None),
                "text": getattr(message, "message", "") or "",
                "date": _isoformat_if_datetime(getattr(message, "date", None)),
                "sender_id": getattr(message, "sender_id", None),
                "views": getattr(message, "views", None),
            }
            for message in history
        ]

    async def _send_message_async(self, client: Any, chat_id: str, text: str) -> dict[str, Any]:
        message = await client.send_message(chat_id, text)
        return {
            "message_id": getattr(message, "id", None),
            "date": _isoformat_if_datetime(getattr(message, "date", None)),
            "text": getattr(message, "message", text) or text,
        }

    def _is_send_approved(self, approval_context: dict[str, object]) -> bool:
        if approval_context.get("approved") is True:
            return True
        status = str(approval_context.get("status", "")).strip().lower()
        return status == "approved"

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
