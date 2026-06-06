"""Runtime records for managed-account inbound engagement events."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


def utc_now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(UTC)


def parse_datetime(value: str | None) -> datetime | None:
    """Parse an ISO 8601 datetime, returning None when the field is empty."""
    if not value:
        return None
    return datetime.fromisoformat(value)


class EngagementEventKind(StrEnum):
    """Supported managed-account inbound event categories."""

    INBOUND_DM = "inbound_dm"
    GROUP_REPLY = "group_reply_to_managed_message"
    MESSAGE_EDITED = "message_edited"
    MESSAGE_DELETED = "message_deleted"
    MODERATION_SIGNAL = "moderation_or_membership_signal"
    UNSUPPORTED = "unsupported"


class EngagementRoutingStatus(StrEnum):
    """Routing state for one persisted inbound engagement event."""

    UNRESOLVED = "unresolved"
    ROUTED = "routed"
    IGNORED = "ignored"
    UNSUPPORTED = "unsupported"


@dataclass(slots=True)
class EngagementEventRecord:
    """A normalized inbound managed-account event stored outside operator sessions."""

    event_id: str
    dedupe_key: str
    account_id: str
    event_kind: EngagementEventKind
    chat_id: str = ""
    peer_id: str = ""
    sender_id: str = ""
    message_id: str = ""
    reply_to_message_id: str = ""
    text: str = ""
    occurred_at: datetime = field(default_factory=utc_now)
    recorded_at: datetime = field(default_factory=utc_now)
    campaign_id: str = ""
    community_id: str = ""
    conversation_id: str = ""
    routing_status: EngagementRoutingStatus = EngagementRoutingStatus.UNRESOLVED
    raw_summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the event for JSONL persistence."""
        return {
            "event_id": self.event_id,
            "dedupe_key": self.dedupe_key,
            "account_id": self.account_id,
            "event_kind": self.event_kind.value,
            "chat_id": self.chat_id,
            "peer_id": self.peer_id,
            "sender_id": self.sender_id,
            "message_id": self.message_id,
            "reply_to_message_id": self.reply_to_message_id,
            "text": self.text,
            "occurred_at": self.occurred_at.isoformat(),
            "recorded_at": self.recorded_at.isoformat(),
            "campaign_id": self.campaign_id,
            "community_id": self.community_id,
            "conversation_id": self.conversation_id,
            "routing_status": self.routing_status.value,
            "raw_summary": dict(self.raw_summary),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "EngagementEventRecord":
        """Hydrate a stored inbound event from a JSON payload."""
        payload = payload or {}
        raw_kind = str(payload.get("event_kind", EngagementEventKind.UNSUPPORTED.value))
        raw_status = str(payload.get("routing_status", EngagementRoutingStatus.UNRESOLVED.value))
        return cls(
            event_id=str(payload.get("event_id", "")).strip(),
            dedupe_key=str(payload.get("dedupe_key", "")).strip(),
            account_id=str(payload.get("account_id", "")).strip(),
            event_kind=EngagementEventKind._value2member_map_.get(raw_kind, EngagementEventKind.UNSUPPORTED),
            chat_id=str(payload.get("chat_id", "")).strip(),
            peer_id=str(payload.get("peer_id", "")).strip(),
            sender_id=str(payload.get("sender_id", "")).strip(),
            message_id=str(payload.get("message_id", "")).strip(),
            reply_to_message_id=str(payload.get("reply_to_message_id", "")).strip(),
            text=str(payload.get("text", "")),
            occurred_at=parse_datetime(str(payload.get("occurred_at", "")).strip()) or utc_now(),
            recorded_at=parse_datetime(str(payload.get("recorded_at", "")).strip()) or utc_now(),
            campaign_id=str(payload.get("campaign_id", "")).strip(),
            community_id=str(payload.get("community_id", "")).strip(),
            conversation_id=str(payload.get("conversation_id", "")).strip(),
            routing_status=EngagementRoutingStatus._value2member_map_.get(
                raw_status,
                EngagementRoutingStatus.UNRESOLVED,
            ),
            raw_summary=dict(payload.get("raw_summary", {}) or {}),
        )


@dataclass(slots=True)
class ListenerState:
    """Small account-scoped state that keeps listener restarts idempotent."""

    account_id: str
    recent_dedupe_keys: list[str] = field(default_factory=list)
    last_event_id: str = ""
    last_recorded_at: str = ""
    updated_at: datetime = field(default_factory=utc_now)

    def remember(self, dedupe_key: str, *, event_id: str, recorded_at: datetime, max_keys: int) -> None:
        """Track a dedupe key while keeping the stored state compact."""
        dedupe_key = dedupe_key.strip()
        if not dedupe_key:
            return
        existing_keys = [value for value in self.recent_dedupe_keys if value != dedupe_key]
        existing_keys.append(dedupe_key)
        self.recent_dedupe_keys = existing_keys[-max_keys:]
        self.last_event_id = event_id
        self.last_recorded_at = recorded_at.isoformat()
        self.updated_at = utc_now()

    def to_dict(self) -> dict[str, Any]:
        """Serialize the listener state for JSON persistence."""
        return {
            "account_id": self.account_id,
            "recent_dedupe_keys": list(self.recent_dedupe_keys),
            "last_event_id": self.last_event_id,
            "last_recorded_at": self.last_recorded_at,
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None, *, account_id: str) -> "ListenerState":
        """Hydrate listener state from JSON, preserving the requested account id."""
        payload = payload or {}
        keys = payload.get("recent_dedupe_keys", [])
        return cls(
            account_id=account_id,
            recent_dedupe_keys=[str(value).strip() for value in keys if str(value).strip()] if isinstance(keys, list) else [],
            last_event_id=str(payload.get("last_event_id", "")).strip(),
            last_recorded_at=str(payload.get("last_recorded_at", "")).strip(),
            updated_at=parse_datetime(str(payload.get("updated_at", "")).strip()) or utc_now(),
        )


@dataclass(slots=True)
class OutboundMessageReference:
    """Compact account-scoped reference used to match future inbound replies."""

    account_id: str
    chat_id: str
    message_id: str
    sent_at: datetime = field(default_factory=utc_now)
    campaign_id: str = ""
    conversation_id: str = ""
    text: str = ""
    asset_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the outbound reference for JSON persistence."""
        return {
            "account_id": self.account_id,
            "asset_refs": list(self.asset_refs),
            "chat_id": self.chat_id,
            "message_id": self.message_id,
            "conversation_id": self.conversation_id,
            "text": self.text,
            "sent_at": self.sent_at.isoformat(),
            "campaign_id": self.campaign_id,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "OutboundMessageReference":
        """Hydrate one outbound reference from a JSON payload."""
        payload = payload or {}
        raw_asset_refs = payload.get("asset_refs", [])
        return cls(
            account_id=str(payload.get("account_id", "")).strip(),
            chat_id=str(payload.get("chat_id", "")).strip(),
            message_id=str(payload.get("message_id", "")).strip(),
            sent_at=parse_datetime(str(payload.get("sent_at", "")).strip()) or utc_now(),
            campaign_id=str(payload.get("campaign_id", "")).strip(),
            conversation_id=str(payload.get("conversation_id", "")).strip(),
            text=str(payload.get("text", "")),
            asset_refs=[str(value).strip() for value in raw_asset_refs if str(value).strip()]
            if isinstance(raw_asset_refs, list)
            else [],
        )
