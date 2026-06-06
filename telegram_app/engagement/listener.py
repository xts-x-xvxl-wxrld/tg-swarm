"""Thin managed-account listener that persists inbound MTProto events."""

from __future__ import annotations

from datetime import UTC, datetime
import logging
import time
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from telegram_app.capabilities.mtproto.presence import set_account_offline
from telegram_app.capabilities.mtproto.client import TelethonClientWrapper
from telegram_app.capabilities.mtproto.registry import AccountRegistry
from telegram_app.engagement.models import (
    EngagementEventKind,
    EngagementEventRecord,
    EngagementRoutingStatus,
    utc_now,
)
from telegram_app.external_conversations import ExternalConversationProjector
from telegram_app.engagement.storage import ManagedAccountEngagementStore

logger = logging.getLogger(__name__)


class ManagedAccountEventListener:
    """Subscribe to managed-account inbound messages and persist normalized events."""

    def __init__(
        self,
        registry: AccountRegistry,
        client_wrapper: TelethonClientWrapper,
        store: ManagedAccountEngagementStore,
        conversation_projector: ExternalConversationProjector | None = None,
        *,
        poll_interval_seconds: float = 15.0,
    ) -> None:
        self._registry = registry
        self._client_wrapper = client_wrapper
        self._store = store
        self._conversation_projector = conversation_projector
        self._poll_interval_seconds = max(poll_interval_seconds, 1.0)
        self._active_account_ids: set[str] = set()

    def run_forever(self) -> None:
        """Run the long-lived listener process, attaching to newly available accounts."""
        logger.info("Starting managed-account inbound listener.")
        while True:
            self._ensure_account_listeners()
            time.sleep(self._poll_interval_seconds)

    def ingest_incoming_event(self, account_id: str, event: Any) -> EngagementEventRecord | None:
        """Normalize and persist one inbound event, returning the stored record when accepted."""
        record = self._build_inbound_event_record(account_id, event)
        if record is None:
            return None
        stored = self._store.append_inbound_event(record)
        if not stored:
            return None
        self._project_stored_event(record)
        return record

    def _ensure_account_listeners(self) -> None:
        for account in self._registry.list_accounts():
            account_id = account.account_id.strip()
            if not account_id or account_id in self._active_account_ids:
                continue
            self._start_listener_for_account(account_id)

    def _start_listener_for_account(self, account_id: str) -> None:
        try:
            self._client_wrapper.connect(account_id)
            self._client_wrapper.run(
                account_id,
                lambda client: self._install_incoming_message_handler(client, account_id),
            )
            self._client_wrapper.run(account_id, set_account_offline)
        except Exception as exc:
            logger.warning("Could not start inbound listener for %s: %s", account_id, exc)
            return

        self._active_account_ids.add(account_id)
        logger.info("Managed-account inbound listener attached for %s.", account_id)

    async def _install_incoming_message_handler(self, client: Any, account_id: str) -> None:
        if getattr(client, "_tg_swarm_inbound_listener_installed", False):
            return

        try:
            from telethon import events
        except ModuleNotFoundError as exc:
            raise RuntimeError("Telethon is required to run the managed-account inbound listener.") from exc

        async def handle_new_message(event: Any) -> None:
            try:
                record = self.ingest_incoming_event(account_id, event)
                if record is not None:
                    logger.info(
                        "Recorded inbound %s event for %s in chat %s.",
                        record.event_kind.value,
                        account_id,
                        record.chat_id or "<unknown>",
                    )
            except Exception:
                logger.exception("Inbound listener failed while processing an event for %s.", account_id)

        client.add_event_handler(handle_new_message, events.NewMessage(incoming=True))
        client._tg_swarm_inbound_listener_installed = True

    def _build_inbound_event_record(self, account_id: str, event: Any) -> EngagementEventRecord | None:
        message = getattr(event, "message", event)
        message_id = self._normalize_id(getattr(message, "id", None))
        chat_id = self._normalize_id(getattr(message, "chat_id", None) or getattr(event, "chat_id", None))
        sender_id = self._normalize_id(getattr(message, "sender_id", None) or getattr(event, "sender_id", None))
        reply_to_message_id = self._extract_reply_to_message_id(message)
        text = self._extract_text(message)
        occurred_at = self._extract_occurred_at(message)
        recorded_at = utc_now()
        is_private = self._is_private_event(message, event)

        outbound_reference = None
        event_kind: EngagementEventKind | None = None
        routing_status = EngagementRoutingStatus.UNRESOLVED
        campaign_id = ""
        community_id = ""

        if is_private:
            event_kind = EngagementEventKind.INBOUND_DM
        elif chat_id and reply_to_message_id:
            outbound_reference = self._store.find_outbound_message(account_id, chat_id, reply_to_message_id)
            if outbound_reference is not None:
                event_kind = EngagementEventKind.GROUP_REPLY
                campaign_id = outbound_reference.campaign_id
                routing_status = (
                    EngagementRoutingStatus.ROUTED
                    if outbound_reference.campaign_id
                    else EngagementRoutingStatus.UNRESOLVED
                )
                community_id = chat_id

        if event_kind is None:
            return None

        dedupe_key = self._build_dedupe_key(
            account_id=account_id,
            event_kind=event_kind,
            chat_id=chat_id,
            sender_id=sender_id,
            message_id=message_id,
            reply_to_message_id=reply_to_message_id,
        )
        event_id = str(uuid5(NAMESPACE_URL, dedupe_key))
        conversation_id = f"{account_id}:{chat_id or sender_id or 'unknown'}"
        raw_summary = {
            "source_event_type": type(event).__name__,
            "is_private": is_private,
            "has_reply_target": bool(reply_to_message_id),
            "reply_matched_outbound": outbound_reference is not None,
            "text_preview": text[:160],
        }

        return EngagementEventRecord(
            event_id=event_id,
            dedupe_key=dedupe_key,
            account_id=account_id.strip(),
            event_kind=event_kind,
            chat_id=chat_id,
            peer_id=chat_id,
            sender_id=sender_id,
            message_id=message_id,
            reply_to_message_id=reply_to_message_id,
            text=text,
            occurred_at=occurred_at,
            recorded_at=recorded_at,
            campaign_id=campaign_id,
            community_id=community_id,
            conversation_id=conversation_id,
            routing_status=routing_status,
            raw_summary=raw_summary,
        )

    def _project_stored_event(self, record: EngagementEventRecord) -> None:
        if self._conversation_projector is None:
            return
        try:
            self._conversation_projector.project_inbound_event(record)
        except Exception:
            logger.exception(
                "External conversation projection failed for account %s event %s.",
                record.account_id,
                record.event_id,
            )

    def _build_dedupe_key(
        self,
        *,
        account_id: str,
        event_kind: EngagementEventKind,
        chat_id: str,
        sender_id: str,
        message_id: str,
        reply_to_message_id: str,
    ) -> str:
        parts = [
            account_id.strip(),
            event_kind.value,
            chat_id,
            sender_id,
            message_id,
            reply_to_message_id,
        ]
        return "|".join(parts)

    def _extract_reply_to_message_id(self, message: Any) -> str:
        direct_value = self._normalize_id(getattr(message, "reply_to_msg_id", None))
        if direct_value:
            return direct_value
        reply_to = getattr(message, "reply_to", None)
        if reply_to is None:
            return ""
        return self._normalize_id(getattr(reply_to, "reply_to_msg_id", None))

    def _extract_text(self, message: Any) -> str:
        return str(
            getattr(message, "message", None)
            or getattr(message, "raw_text", None)
            or getattr(message, "text", "")
        )

    def _extract_occurred_at(self, message: Any) -> datetime:
        value = getattr(message, "date", None)
        if not isinstance(value, datetime):
            return utc_now()
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def _is_private_event(self, message: Any, event: Any) -> bool:
        message_flag = getattr(message, "is_private", None)
        if isinstance(message_flag, bool):
            return message_flag
        event_flag = getattr(event, "is_private", None)
        if isinstance(event_flag, bool):
            return event_flag
        return False

    def _normalize_id(self, value: Any) -> str:
        if value is None:
            return ""
        normalized = str(value).strip()
        return normalized if normalized != "None" else ""
