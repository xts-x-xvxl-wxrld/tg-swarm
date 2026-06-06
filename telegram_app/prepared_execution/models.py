"""Durable campaign-owned prepared execution records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from telegram_app.live_execution import LiveActionType


def utc_now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(UTC)


def parse_datetime(value: str | None) -> datetime | None:
    """Parse an ISO 8601 datetime, returning None for empty values."""
    if value is None:
        return None
    normalized = value.strip()
    if not normalized or normalized.lower() in {"none", "null"}:
        return None
    return datetime.fromisoformat(normalized)


class PreparedExecutionBatchStatus(StrEnum):
    """Lifecycle states for one prepared execution batch."""

    PREPARED = "prepared"
    PARTIALLY_QUEUED = "partially_queued"
    QUEUED = "queued"
    SUPERSEDED = "superseded"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class PreparedExecutionItemStatus(StrEnum):
    """Lifecycle states for one prepared execution item."""

    PREPARED = "prepared"
    QUEUED = "queued"
    CLAIMED = "claimed"
    EXECUTED = "executed"
    SUPERSEDED = "superseded"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


_ACTIVE_BATCH_STATUSES = frozenset(
    {
        PreparedExecutionBatchStatus.PREPARED,
        PreparedExecutionBatchStatus.PARTIALLY_QUEUED,
        PreparedExecutionBatchStatus.QUEUED,
    }
)


@dataclass(slots=True)
class PreparedExecutionBatch:
    """One activation-time snapshot of the approved execution plan."""

    batch_id: str
    campaign_id: str
    source_plan_artifact_id: str
    source_plan_updated_at: datetime
    source_plan_fingerprint: str
    source_strategy_artifact_id: str = ""
    activated_by_operator_id: str = ""
    activated_at: datetime = field(default_factory=utc_now)
    status: PreparedExecutionBatchStatus = PreparedExecutionBatchStatus.PREPARED
    summary: str = ""
    schedule_intent_refs: list[str] = field(default_factory=list)
    queued_action_ids: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def touch(self) -> None:
        """Refresh the update timestamp after a mutation."""
        self.updated_at = utc_now()

    def is_active(self) -> bool:
        """Return whether the batch still owns non-terminal prepared state."""
        return self.status in _ACTIVE_BATCH_STATUSES

    def to_dict(self) -> dict[str, object]:
        """Serialize the batch for JSON-backed persistence."""
        return {
            "batch_id": self.batch_id,
            "campaign_id": self.campaign_id,
            "source_plan_artifact_id": self.source_plan_artifact_id,
            "source_plan_updated_at": self.source_plan_updated_at.isoformat(),
            "source_plan_fingerprint": self.source_plan_fingerprint,
            "source_strategy_artifact_id": self.source_strategy_artifact_id,
            "activated_by_operator_id": self.activated_by_operator_id,
            "activated_at": self.activated_at.isoformat(),
            "status": self.status.value,
            "summary": self.summary,
            "schedule_intent_refs": list(self.schedule_intent_refs),
            "queued_action_ids": list(self.queued_action_ids),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object] | None) -> "PreparedExecutionBatch":
        """Hydrate one batch record from persisted JSON."""
        payload = payload or {}
        raw_status = str(payload.get("status", PreparedExecutionBatchStatus.PREPARED.value))
        return cls(
            batch_id=str(payload.get("batch_id", "")).strip(),
            campaign_id=str(payload.get("campaign_id", "")).strip(),
            source_plan_artifact_id=str(payload.get("source_plan_artifact_id", "")).strip(),
            source_plan_updated_at=parse_datetime(str(payload.get("source_plan_updated_at", "")).strip()) or utc_now(),
            source_plan_fingerprint=str(payload.get("source_plan_fingerprint", "")).strip(),
            source_strategy_artifact_id=str(payload.get("source_strategy_artifact_id", "")).strip(),
            activated_by_operator_id=str(payload.get("activated_by_operator_id", "")).strip(),
            activated_at=parse_datetime(str(payload.get("activated_at", "")).strip()) or utc_now(),
            status=PreparedExecutionBatchStatus._value2member_map_.get(
                raw_status,
                PreparedExecutionBatchStatus.PREPARED,
            ),
            summary=str(payload.get("summary", "")),
            schedule_intent_refs=[
                str(value).strip()
                for value in payload.get("schedule_intent_refs", [])
                if str(value).strip()
            ]
            if isinstance(payload.get("schedule_intent_refs", []), list)
            else [],
            queued_action_ids=[
                str(value).strip()
                for value in payload.get("queued_action_ids", [])
                if str(value).strip()
            ]
            if isinstance(payload.get("queued_action_ids", []), list)
            else [],
            created_at=parse_datetime(str(payload.get("created_at", "")).strip()) or utc_now(),
            updated_at=parse_datetime(str(payload.get("updated_at", "")).strip()) or utc_now(),
        )


@dataclass(slots=True)
class PreparedExecutionItem:
    """One normalized executable unit prepared from an approved plan."""

    prepared_item_id: str
    batch_id: str
    campaign_id: str
    action_type: LiveActionType
    account_id: str
    community_ref: str = ""
    chat_id: str = ""
    community_id: str = ""
    source_assignment_index: int = 0
    source_post_index: int = 0
    day_offset: int = 0
    time_window: str = ""
    draft_text: str = ""
    approval_context: dict[str, object] = field(default_factory=dict)
    status: PreparedExecutionItemStatus = PreparedExecutionItemStatus.PREPARED
    live_action_id: str = ""
    invalidated_reason: str = ""
    result_summary: str = ""
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def touch(self) -> None:
        """Refresh the update timestamp after a mutation."""
        self.updated_at = utc_now()

    def to_dict(self) -> dict[str, object]:
        """Serialize the item for JSON-backed persistence."""
        return {
            "prepared_item_id": self.prepared_item_id,
            "batch_id": self.batch_id,
            "campaign_id": self.campaign_id,
            "action_type": self.action_type.value,
            "account_id": self.account_id,
            "community_ref": self.community_ref,
            "chat_id": self.chat_id,
            "community_id": self.community_id,
            "source_assignment_index": self.source_assignment_index,
            "source_post_index": self.source_post_index,
            "day_offset": self.day_offset,
            "time_window": self.time_window,
            "draft_text": self.draft_text,
            "approval_context": dict(self.approval_context),
            "status": self.status.value,
            "live_action_id": self.live_action_id,
            "invalidated_reason": self.invalidated_reason,
            "result_summary": self.result_summary,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object] | None) -> "PreparedExecutionItem":
        """Hydrate one prepared item from persisted JSON."""
        payload = payload or {}
        raw_action_type = str(payload.get("action_type", LiveActionType.SEND_GROUP_MESSAGE.value))
        raw_status = str(payload.get("status", PreparedExecutionItemStatus.PREPARED.value))
        raw_approval_context = payload.get("approval_context", {})
        return cls(
            prepared_item_id=str(payload.get("prepared_item_id", "")).strip(),
            batch_id=str(payload.get("batch_id", "")).strip(),
            campaign_id=str(payload.get("campaign_id", "")).strip(),
            action_type=LiveActionType._value2member_map_.get(raw_action_type, LiveActionType.SEND_GROUP_MESSAGE),
            account_id=str(payload.get("account_id", "")).strip(),
            community_ref=str(payload.get("community_ref", "")).strip(),
            chat_id=str(payload.get("chat_id", "")).strip(),
            community_id=str(payload.get("community_id", "")).strip(),
            source_assignment_index=max(int(payload.get("source_assignment_index", 0) or 0), 0),
            source_post_index=max(int(payload.get("source_post_index", 0) or 0), 0),
            day_offset=max(int(payload.get("day_offset", 0) or 0), 0),
            time_window=str(payload.get("time_window", "")).strip(),
            draft_text=str(payload.get("draft_text", "")),
            approval_context=dict(raw_approval_context) if isinstance(raw_approval_context, dict) else {},
            status=PreparedExecutionItemStatus._value2member_map_.get(
                raw_status,
                PreparedExecutionItemStatus.PREPARED,
            ),
            live_action_id=str(payload.get("live_action_id", "")).strip(),
            invalidated_reason=str(payload.get("invalidated_reason", "")),
            result_summary=str(payload.get("result_summary", "")),
            created_at=parse_datetime(str(payload.get("created_at", "")).strip()) or utc_now(),
            updated_at=parse_datetime(str(payload.get("updated_at", "")).strip()) or utc_now(),
        )
