"""Messaging capability implementation backed by Telethon."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from telegram_app.capabilities.base import CapabilityResult
from telegram_app.capabilities.mtproto.audit_logger import JsonlAuditLogger
from telegram_app.capabilities.mtproto.client import TelethonClientWrapper
from telegram_app.capabilities.mtproto.error_classifier import classify_mtproto_exception
from telegram_app.capabilities.mtproto import presence
from telegram_app.capabilities.mtproto.registry import AccountRegistry, parse_iso8601
from telegram_app.engagement import ManagedAccountEngagementStore
from telegram_app.transport.formatting import TELEGRAM_MTPROTO_PARSE_MODE, format_telegram_html


def _isoformat_if_datetime(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return ""


def _normalize_message_id(value: str | int | None) -> str:
    if value is None:
        return ""
    normalized = str(value).strip()
    return normalized if normalized != "None" else ""


def _coerce_message_id(value: str) -> int | str:
    return int(value) if value.isdigit() else value


def _normalize_visible_text(value: str) -> str:
    return " ".join(str(value).split()).strip()


def _extract_reply_to_message_id(message: Any) -> str:
    direct_value = _normalize_message_id(getattr(message, "reply_to_msg_id", None))
    if direct_value:
        return direct_value
    reply_to = getattr(message, "reply_to", None)
    if reply_to is None:
        return ""
    return _normalize_message_id(getattr(reply_to, "reply_to_msg_id", None))


def _parse_message_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _should_verify_delivery_after_exception(exc: Exception) -> bool:
    return exc.__class__.__name__ in {"OSError", "RpcCallFailError", "ServerError", "TimeoutError"}


def _peer_type(entity: Any) -> str:
    if getattr(entity, "broadcast", False):
        return "channel"
    if getattr(entity, "megagroup", False):
        return "supergroup"
    if getattr(entity, "title", None):
        return "group"
    return "direct"


class MessagingCapabilityImpl:
    """Read and send Telegram messages through the shared MTProto client wrapper."""

    def __init__(
        self,
        registry: AccountRegistry,
        client_wrapper: TelethonClientWrapper,
        *,
        audit_logger: JsonlAuditLogger | None = None,
        engagement_store: ManagedAccountEngagementStore | None = None,
    ) -> None:
        self._registry = registry
        self._client_wrapper = client_wrapper
        self._audit_logger = audit_logger
        self._engagement_store = engagement_store

    def read_messages(self, chat_id: str, limit: int = 20) -> CapabilityResult:
        account = self._registry.resolve_default_read_account()
        if account is None:
            return CapabilityResult(
                success=False,
                data={"chat_id": chat_id, "limit": limit, "source": "telethon"},
                audit={"implementation": "mtproto_messaging_capability", "action": "read_messages"},
                error="No Telegram account is configured for live message reads.",
            )

        return self._read_history_for_account(
            account.account_id,
            chat_id,
            limit=limit,
            action="read_messages",
        )

    def send_message(
        self,
        account_id: str,
        chat_id: str,
        text: str,
        *,
        approval_context: dict[str, object] | None = None,
    ) -> CapabilityResult:
        return self._send_visible_message(
            account_id,
            chat_id,
            text,
            approval_context=approval_context,
            action="send_message",
            audit_category_prefix="message_send",
            registry_action="send",
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
        normalized_reply_id = _normalize_message_id(reply_to_message_id)
        if not normalized_reply_id:
            result = CapabilityResult(
                success=False,
                data={
                    "account_id": account_id,
                    "chat_id": chat_id,
                    "reply_to_message_id": normalized_reply_id,
                    "outcome_code": "invalid_action_payload",
                    "source": "telethon",
                },
                audit={"implementation": "mtproto_messaging_capability", "action": "send_reply"},
                error="Reply sends require a target reply_to_message_id.",
            )
            self._record_audit_event("message_reply_blocked", result)
            return result

        return self._send_visible_message(
            account_id,
            chat_id,
            text,
            approval_context=approval_context,
            action="send_reply",
            audit_category_prefix="message_reply",
            registry_action="send_reply",
            reply_to_message_id=normalized_reply_id,
        )

    def mark_read(
        self,
        account_id: str,
        chat_id: str,
        message_id: str | int | None = None,
    ) -> CapabilityResult:
        normalized_message_id = _normalize_message_id(message_id)
        can_write, reason, outcome_code = self._can_perform_write_action(account_id)
        if not can_write:
            result = CapabilityResult(
                success=False,
                data={
                    "account_id": account_id,
                    "chat_id": chat_id,
                    "message_id": normalized_message_id,
                    "outcome_code": outcome_code,
                    "source": "telethon",
                },
                audit={"implementation": "mtproto_messaging_capability", "action": "mark_read"},
                error=reason,
            )
            self._record_audit_event("message_mark_read_blocked", result)
            return result

        available, error = self._client_wrapper.is_available()
        if not available:
            result = CapabilityResult(
                success=False,
                data={
                    "account_id": account_id,
                    "chat_id": chat_id,
                    "message_id": normalized_message_id,
                    "outcome_code": "telethon_unavailable",
                    "source": "telethon",
                },
                audit={"implementation": "mtproto_messaging_capability", "action": "mark_read"},
                error=error,
            )
            self._record_audit_event("message_mark_read_unavailable", result)
            return result

        try:
            acknowledged = self._client_wrapper.run(
                account_id,
                lambda client: self._mark_read_async(client, chat_id, normalized_message_id),
            )
            self._registry.mark_action_success(account_id, action="mark_read", target=chat_id)
            result = CapabilityResult(
                success=True,
                data={
                    "account_id": account_id,
                    "chat_id": chat_id,
                    "message_id": normalized_message_id,
                    "acknowledged": bool(acknowledged),
                    "outcome_code": "success",
                    "source": "telethon",
                },
                audit={"implementation": "mtproto_messaging_capability", "action": "mark_read"},
            )
            self._record_audit_event("message_mark_read_succeeded", result)
            return result
        except Exception as exc:
            error_details = classify_mtproto_exception(exc, action="marking a dialog as read")
            self._registry.mark_action_failure(
                account_id,
                action="mark_read",
                target=chat_id,
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
                    "message_id": normalized_message_id,
                    "outcome_code": error_details.code,
                    "wait_seconds": error_details.wait_seconds,
                    "source": "telethon",
                },
                audit={"implementation": "mtproto_messaging_capability", "action": "mark_read"},
                error=error_details.message,
            )
            self._record_audit_event("message_mark_read_failed", result)
            return result

    def get_dialog_history(
        self,
        account_id: str,
        peer_id: str,
        limit: int = 20,
    ) -> CapabilityResult:
        return self._read_history_for_account(
            account_id,
            peer_id,
            limit=limit,
            action="get_dialog_history",
        )

    def list_recent_dialogs(
        self,
        account_id: str,
        limit: int = 20,
    ) -> CapabilityResult:
        account = self._registry.get_account(account_id)
        if account is None:
            return CapabilityResult(
                success=False,
                data={
                    "account_id": account_id,
                    "limit": limit,
                    "outcome_code": "unknown_account",
                    "source": "telethon",
                },
                audit={"implementation": "mtproto_messaging_capability", "action": "list_recent_dialogs"},
                error=f"Unknown Telegram account: {account_id}",
            )

        available, error = self._client_wrapper.is_available()
        if not available:
            return CapabilityResult(
                success=False,
                data={
                    "account_id": account_id,
                    "limit": limit,
                    "outcome_code": "telethon_unavailable",
                    "source": "telethon",
                },
                audit={"implementation": "mtproto_messaging_capability", "action": "list_recent_dialogs"},
                error=error,
            )

        try:
            dialogs = self._client_wrapper.run(
                account_id,
                lambda client: self._list_recent_dialogs_async(client, limit),
            )
        except Exception as exc:
            error_details = classify_mtproto_exception(exc, action="listing recent dialogs")
            return CapabilityResult(
                success=False,
                data={
                    "account_id": account_id,
                    "limit": limit,
                    "outcome_code": error_details.code,
                    "wait_seconds": error_details.wait_seconds,
                    "source": "telethon",
                },
                audit={"implementation": "mtproto_messaging_capability", "action": "list_recent_dialogs"},
                error=error_details.message,
            )

        return CapabilityResult(
            success=True,
            data={
                "account_id": account_id,
                "limit": limit,
                "dialogs": dialogs,
                "outcome_code": "success",
                "source": "telethon",
            },
            audit={"implementation": "mtproto_messaging_capability", "action": "list_recent_dialogs"},
        )

    def leave_dialog(self, account_id: str, peer_id: str) -> CapabilityResult:
        can_write, reason, outcome_code = self._can_perform_write_action(account_id)
        if not can_write:
            result = CapabilityResult(
                success=False,
                data={
                    "account_id": account_id,
                    "peer_id": peer_id,
                    "outcome_code": outcome_code,
                    "source": "telethon",
                },
                audit={"implementation": "mtproto_messaging_capability", "action": "leave_dialog"},
                error=reason,
            )
            self._record_audit_event("dialog_leave_blocked", result)
            return result

        available, error = self._client_wrapper.is_available()
        if not available:
            result = CapabilityResult(
                success=False,
                data={
                    "account_id": account_id,
                    "peer_id": peer_id,
                    "outcome_code": "telethon_unavailable",
                    "source": "telethon",
                },
                audit={"implementation": "mtproto_messaging_capability", "action": "leave_dialog"},
                error=error,
            )
            self._record_audit_event("dialog_leave_unavailable", result)
            return result

        try:
            self._client_wrapper.run(account_id, lambda client: self._leave_dialog_async(client, peer_id))
            self._registry.mark_action_success(account_id, action="leave_dialog", target=peer_id)
            result = CapabilityResult(
                success=True,
                data={
                    "account_id": account_id,
                    "peer_id": peer_id,
                    "outcome_code": "left",
                    "source": "telethon",
                },
                audit={"implementation": "mtproto_messaging_capability", "action": "leave_dialog"},
            )
            self._record_audit_event("dialog_leave_succeeded", result)
            return result
        except Exception as exc:
            error_details = classify_mtproto_exception(exc, action="leaving a dialog")
            if error_details.already_satisfied:
                self._registry.mark_action_success(account_id, action="leave_dialog", target=peer_id)
                result = CapabilityResult(
                    success=True,
                    data={
                        "account_id": account_id,
                        "peer_id": peer_id,
                        "outcome_code": error_details.code,
                        "source": "telethon",
                    },
                    audit={"implementation": "mtproto_messaging_capability", "action": "leave_dialog"},
                )
                self._record_audit_event("dialog_leave_already_satisfied", result)
                return result

            self._registry.mark_action_failure(
                account_id,
                action="leave_dialog",
                target=peer_id,
                health=error_details.health,
                wait_seconds=error_details.wait_seconds,
                error=error_details.message,
                outcome=error_details.code,
            )
            result = CapabilityResult(
                success=False,
                data={
                    "account_id": account_id,
                    "peer_id": peer_id,
                    "outcome_code": error_details.code,
                    "wait_seconds": error_details.wait_seconds,
                    "source": "telethon",
                },
                audit={"implementation": "mtproto_messaging_capability", "action": "leave_dialog"},
                error=error_details.message,
            )
            self._record_audit_event("dialog_leave_failed", result)
            return result

    def _send_visible_message(
        self,
        account_id: str,
        chat_id: str,
        text: str,
        *,
        approval_context: dict[str, object] | None,
        action: str,
        audit_category_prefix: str,
        registry_action: str,
        reply_to_message_id: str = "",
    ) -> CapabilityResult:
        approval_context = dict(approval_context or {})
        if not self._is_send_approved(approval_context):
            result = CapabilityResult(
                success=False,
                data={
                    "account_id": account_id,
                    "chat_id": chat_id,
                    "reply_to_message_id": reply_to_message_id,
                    "approval_context": approval_context,
                    "outcome_code": "approval_required",
                    "source": "telethon",
                },
                audit={"implementation": "mtproto_messaging_capability", "action": action},
                error="Live Telegram sends require explicit structured approved-send context.",
            )
            self._record_audit_event(f"{audit_category_prefix}_blocked", result)
            return result

        can_write, reason, outcome_code = self._can_perform_write_action(account_id)
        if not can_write:
            result = CapabilityResult(
                success=False,
                data={
                    "account_id": account_id,
                    "chat_id": chat_id,
                    "reply_to_message_id": reply_to_message_id,
                    "outcome_code": outcome_code,
                    "source": "telethon",
                },
                audit={"implementation": "mtproto_messaging_capability", "action": action},
                error=reason,
            )
            self._record_audit_event(f"{audit_category_prefix}_blocked", result)
            return result

        available, error = self._client_wrapper.is_available()
        if not available:
            result = CapabilityResult(
                success=False,
                data={
                    "account_id": account_id,
                    "chat_id": chat_id,
                    "reply_to_message_id": reply_to_message_id,
                    "outcome_code": "telethon_unavailable",
                    "source": "telethon",
                },
                audit={"implementation": "mtproto_messaging_capability", "action": action},
                error=error,
            )
            self._record_audit_event(f"{audit_category_prefix}_unavailable", result)
            return result

        mark_read_before_send = self._should_mark_read_before_send(
            approval_context,
            reply_to_message_id=reply_to_message_id,
        )
        attempt_started_at = datetime.now(UTC)
        attempt = 1
        try:
            payload = self._client_wrapper.run(
                account_id,
                lambda client: self._send_message_async(
                    client,
                    chat_id,
                    text,
                    reply_to_message_id=reply_to_message_id,
                    mark_read_before_send=mark_read_before_send,
                ),
            )
            self._registry.mark_action_success(account_id, action=registry_action, target=chat_id)
            result = CapabilityResult(
                success=True,
                data={
                    **payload,
                    "account_id": account_id,
                    "chat_id": chat_id,
                    "reply_to_message_id": reply_to_message_id,
                    "attempts": attempt,
                    "approval_context": approval_context,
                    "outcome_code": "success",
                    "source": "telethon",
                },
                audit={"implementation": "mtproto_messaging_capability", "action": action},
            )
            self._record_outbound_reference(result)
            self._record_audit_event(f"{audit_category_prefix}_succeeded", result)
            return result
        except Exception as exc:
            error_details = classify_mtproto_exception(exc, action="sending a message")
            if error_details.retriable and _should_verify_delivery_after_exception(exc):
                recovered_payload = self._find_recent_outbound_delivery(
                    account_id,
                    chat_id,
                    text,
                    reply_to_message_id=reply_to_message_id,
                    sent_after=attempt_started_at - timedelta(minutes=2),
                )
                if recovered_payload is not None:
                    self._registry.mark_action_success(account_id, action=registry_action, target=chat_id)
                    result = CapabilityResult(
                        success=True,
                        data={
                            **recovered_payload,
                            "account_id": account_id,
                            "chat_id": chat_id,
                            "reply_to_message_id": reply_to_message_id,
                            "attempts": attempt,
                            "approval_context": approval_context,
                            "outcome_code": "success",
                            "source": "telethon",
                            "verified_after_retry_error": True,
                            "recovered_error_code": error_details.code,
                        },
                        audit={"implementation": "mtproto_messaging_capability", "action": action},
                    )
                    self._record_outbound_reference(result)
                    self._record_audit_event(f"{audit_category_prefix}_recovered", result)
                    return result

            self._registry.mark_action_failure(
                account_id,
                action=registry_action,
                target=chat_id,
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
                    "reply_to_message_id": reply_to_message_id,
                    "attempts": attempt,
                    "outcome_code": error_details.code,
                    "wait_seconds": error_details.wait_seconds,
                    "source": "telethon",
                },
                audit={"implementation": "mtproto_messaging_capability", "action": action},
                error=error_details.message,
            )
            self._record_audit_event(f"{audit_category_prefix}_failed", result)
            return result

    def _find_recent_outbound_delivery(
        self,
        account_id: str,
        chat_id: str,
        text: str,
        *,
        reply_to_message_id: str = "",
        sent_after: datetime,
    ) -> dict[str, Any] | None:
        try:
            return self._client_wrapper.run(
                account_id,
                lambda client: self._find_recent_outbound_delivery_async(
                    client,
                    chat_id,
                    text,
                    reply_to_message_id=reply_to_message_id,
                    sent_after=sent_after,
                ),
            )
        except Exception:
            return None

    async def _find_recent_outbound_delivery_async(
        self,
        client: Any,
        chat_id: str,
        text: str,
        *,
        reply_to_message_id: str = "",
        sent_after: datetime,
    ) -> dict[str, Any] | None:
        expected_text = _normalize_visible_text(text)
        history = await client.get_messages(chat_id, limit=10)
        for message in history:
            serialized = self._serialize_message(message)
            if not serialized["is_outbound"]:
                continue
            if _normalize_visible_text(str(serialized.get("text", ""))) != expected_text:
                continue
            candidate_reply_to = _normalize_message_id(serialized.get("reply_to_message_id"))
            if reply_to_message_id and candidate_reply_to != reply_to_message_id:
                continue
            candidate_date = _parse_message_datetime(serialized.get("date"))
            if candidate_date is None or candidate_date < sent_after:
                continue
            return {
                "message_id": serialized.get("message_id"),
                "date": serialized.get("date", ""),
                "text": str(serialized.get("text", "")),
                "reply_to_message_id": candidate_reply_to or reply_to_message_id,
            }
        return None

    def _read_history_for_account(
        self,
        account_id: str,
        chat_id: str,
        *,
        limit: int,
        action: str,
    ) -> CapabilityResult:
        account = self._registry.get_account(account_id)
        if account is None:
            return CapabilityResult(
                success=False,
                data={
                    "account_id": account_id,
                    "chat_id": chat_id,
                    "limit": limit,
                    "outcome_code": "unknown_account",
                    "source": "telethon",
                },
                audit={"implementation": "mtproto_messaging_capability", "action": action},
                error=f"Unknown Telegram account: {account_id}",
            )

        available, error = self._client_wrapper.is_available()
        if not available:
            return CapabilityResult(
                success=False,
                data={
                    "account_id": account_id,
                    "chat_id": chat_id,
                    "limit": limit,
                    "outcome_code": "telethon_unavailable",
                    "source": "telethon",
                },
                audit={"implementation": "mtproto_messaging_capability", "action": action},
                error=error,
            )

        try:
            messages = self._client_wrapper.run(
                account_id,
                lambda client: self._get_dialog_history_async(client, chat_id, limit),
            )
        except Exception as exc:
            error_details = classify_mtproto_exception(exc, action="reading dialog history")
            return CapabilityResult(
                success=False,
                data={
                    "account_id": account_id,
                    "chat_id": chat_id,
                    "limit": limit,
                    "outcome_code": error_details.code,
                    "wait_seconds": error_details.wait_seconds,
                    "source": "telethon",
                },
                audit={"implementation": "mtproto_messaging_capability", "action": action},
                error=error_details.message,
            )

        return CapabilityResult(
            success=True,
            data={
                "account_id": account_id,
                "chat_id": chat_id,
                "limit": limit,
                "messages": messages,
                "outcome_code": "success",
                "source": "telethon",
            },
            audit={"implementation": "mtproto_messaging_capability", "action": action},
        )

    async def _get_dialog_history_async(self, client: Any, chat_id: str, limit: int) -> list[dict[str, Any]]:
        await presence.open_online_window(client)
        try:
            history = await client.get_messages(chat_id, limit=limit)
            serialized = [self._serialize_message(message) for message in history]
            await presence.simulate_read_delay([item["text"] for item in serialized if item.get("text")])
            if serialized:
                latest_message_id = _normalize_message_id(serialized[0].get("message_id"))
                await self._mark_chat_read(client, chat_id, message_id=latest_message_id)
            return serialized
        finally:
            await presence.close_online_window(client)

    async def _read_messages_async(self, client: Any, chat_id: str, limit: int) -> list[dict[str, Any]]:
        return await self._get_dialog_history_async(client, chat_id, limit)

    async def _send_message_async(
        self,
        client: Any,
        chat_id: str,
        text: str,
        *,
        reply_to_message_id: str = "",
        mark_read_before_send: bool = False,
    ) -> dict[str, Any]:
        target_entity = await client.get_entity(chat_id)
        target_type = _peer_type(target_entity)
        if target_type == "channel":
            raise ChannelSendDeferredError(
                "Broadcast channel sends are deferred in this version. Use groups/supergroups for outbound sandbox testing."
            )
        kwargs: dict[str, object] = {"parse_mode": TELEGRAM_MTPROTO_PARSE_MODE}
        if reply_to_message_id:
            kwargs["reply_to"] = _coerce_message_id(reply_to_message_id)
        rendered_text = format_telegram_html(text)
        await presence.open_online_window(client)
        try:
            if mark_read_before_send:
                await presence.simulate_read_delay([])
                await self._mark_chat_read(client, chat_id, message_id=reply_to_message_id)
            await presence.show_typing_indicator(client, chat_id, text)
            message = await client.send_message(chat_id, rendered_text, **kwargs)
            return {
                "message_id": getattr(message, "id", None),
                "date": _isoformat_if_datetime(getattr(message, "date", None)),
                "text": getattr(message, "message", rendered_text) or rendered_text,
                "reply_to_message_id": _extract_reply_to_message_id(message) or reply_to_message_id,
                "target_type": target_type,
            }
        finally:
            await presence.close_online_window(client)

    async def _mark_read_async(self, client: Any, chat_id: str, message_id: str) -> bool:
        await presence.open_online_window(client)
        try:
            await presence.simulate_read_delay([])
            return await self._mark_chat_read(client, chat_id, message_id=message_id)
        finally:
            await presence.close_online_window(client)

    async def _mark_chat_read(
        self,
        client: Any,
        chat_id: str,
        *,
        message_id: str = "",
    ) -> bool:
        read_acknowledge = getattr(client, "send_read_acknowledge", None)
        if not callable(read_acknowledge):
            return False
        if message_id:
            return bool(await read_acknowledge(chat_id, max_id=_coerce_message_id(message_id)))
        return bool(await read_acknowledge(chat_id))

    async def _list_recent_dialogs_async(self, client: Any, limit: int) -> list[dict[str, Any]]:
        await presence.open_online_window(client)
        try:
            dialogs: list[dict[str, Any]] = []
            async for dialog in client.iter_dialogs(limit=limit):
                dialogs.append(self._serialize_dialog(dialog))
            return dialogs
        finally:
            await presence.close_online_window(client)

    async def _leave_dialog_async(self, client: Any, peer_id: str) -> None:
        await presence.open_online_window(client)
        try:
            await client.delete_dialog(peer_id)
        finally:
            await presence.close_online_window(client)

    def _should_mark_read_before_send(
        self,
        approval_context: dict[str, object],
        *,
        reply_to_message_id: str,
    ) -> bool:
        if reply_to_message_id:
            return True
        conversation_id = str(approval_context.get("conversation_id", "")).strip()
        return bool(conversation_id)

    def _serialize_message(self, message: Any) -> dict[str, Any]:
        return {
            "message_id": getattr(message, "id", None),
            "chat_id": _normalize_message_id(getattr(message, "chat_id", None)),
            "sender_id": _normalize_message_id(getattr(message, "sender_id", None)),
            "text": getattr(message, "message", "") or "",
            "date": _isoformat_if_datetime(getattr(message, "date", None)),
            "reply_to_message_id": _extract_reply_to_message_id(message),
            "is_outbound": bool(getattr(message, "out", False)),
            "views": getattr(message, "views", None),
        }

    def _serialize_dialog(self, dialog: Any) -> dict[str, Any]:
        entity = getattr(dialog, "entity", None)
        message = getattr(dialog, "message", None)
        peer_id = _normalize_message_id(getattr(entity, "id", None) or getattr(dialog, "id", None))
        return {
            "peer_id": peer_id,
            "title": str(getattr(dialog, "name", "") or ""),
            "unread_count": int(getattr(dialog, "unread_count", 0) or 0),
            "archived": bool(getattr(dialog, "archived", False)),
            "is_user": bool(getattr(dialog, "is_user", False)),
            "is_group": bool(getattr(dialog, "is_group", False)),
            "is_channel": bool(getattr(dialog, "is_channel", False)),
            "last_message_id": getattr(message, "id", None),
            "last_message_text": getattr(message, "message", "") or "",
            "last_message_date": _isoformat_if_datetime(getattr(message, "date", None)),
        }

    def _can_perform_write_action(self, account_id: str) -> tuple[bool, str, str]:
        record = self._registry.get_account(account_id)
        if record is None:
            return False, f"Unknown Telegram account: {account_id}", "unknown_account"
        if record.health == "banned":
            return False, f"Telegram account {account_id} is banned.", "account_banned"
        if record.health == "flagged":
            return (
                False,
                f"Telegram account {account_id} is flagged and should not perform managed-account writes until reviewed.",
                "account_flagged",
            )

        rate_limit_until = parse_iso8601(record.rate_limit_until)
        if rate_limit_until is not None and rate_limit_until > datetime.now(UTC):
            wait_seconds = int((rate_limit_until - datetime.now(UTC)).total_seconds())
            return (
                False,
                f"Telegram account {account_id} is rate-limited for another {wait_seconds} seconds.",
                "rate_limited",
            )
        return True, "", ""

    def _is_send_approved(self, approval_context: dict[str, object]) -> bool:
        if approval_context.get("approved") is not True:
            return False

        approval_mode = str(approval_context.get("approval_mode", "")).strip().lower()
        campaign_id = str(approval_context.get("campaign_id", "")).strip()
        approval_source = str(approval_context.get("approval_source", "")).strip()
        if not approval_mode or not campaign_id or not approval_source:
            return False

        if approval_mode == "autonomous":
            return all(
                [
                    str(approval_context.get("authorization_decision", "")).strip().lower() == "allowed",
                    str(approval_context.get("authorized_action_type", "")).strip(),
                    str(approval_context.get("authorized_at", "")).strip(),
                    str(approval_context.get("context_fingerprint", "")).strip(),
                ]
            )

        if approval_mode == "operator":
            return any(
                [
                    str(approval_context.get("approval_id", "")).strip(),
                    str(approval_context.get("source_plan_artifact_id", "")).strip(),
                    str(approval_context.get("approved_by", "")).strip(),
                ]
            )

        return False

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

    def _record_outbound_reference(self, result: CapabilityResult) -> None:
        if self._engagement_store is None or not result.success:
            return

        account_id = str(result.data.get("account_id", "")).strip()
        chat_id = str(result.data.get("chat_id", "")).strip()
        message_id = result.data.get("message_id")
        if not account_id or not chat_id or message_id in {None, ""}:
            return

        raw_sent_at = str(result.data.get("date", "")).strip()
        if raw_sent_at:
            try:
                sent_at = datetime.fromisoformat(raw_sent_at)
            except ValueError:
                sent_at = datetime.now(UTC)
        else:
            sent_at = datetime.now(UTC)

        campaign_id = str(result.data.get("campaign_id", "")).strip()
        approval_context = result.data.get("approval_context", {})
        if not campaign_id and isinstance(approval_context, dict):
            campaign_id = str(approval_context.get("campaign_id", "")).strip()
        conversation_id = ""
        asset_refs: list[str] = []
        if isinstance(approval_context, dict):
            conversation_id = str(approval_context.get("conversation_id", "")).strip()
            raw_asset_refs = approval_context.get("asset_refs", [])
            if isinstance(raw_asset_refs, list):
                asset_refs = [str(value).strip() for value in raw_asset_refs if str(value).strip()]

        self._engagement_store.record_outbound_message(
            account_id,
            chat_id,
            message_id,
            sent_at=sent_at,
            campaign_id=campaign_id,
            conversation_id=conversation_id,
            text=str(result.data.get("text", "")),
            asset_refs=asset_refs,
        )


class ChannelSendDeferredError(Exception):
    """Raised when the runtime is asked to post into a broadcast channel in this version."""
