"""Durable records for queued managed-account live execution actions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


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


class LiveActionType(StrEnum):
    """Supported live execution action types for the MVP runtime."""

    JOIN_COMMUNITY = "join_community"
    SEND_GROUP_MESSAGE = "send_group_message"
    SEND_GROUP_REPLY = "send_group_reply"
    SEND_DM_REPLY = "send_dm_reply"
    MARK_READ = "mark_read"
    LEAVE_DIALOG = "leave_dialog"


class LiveActionStatus(StrEnum):
    """Lifecycle states for one queued live action."""

    QUEUED = "queued"
    CLAIMED = "claimed"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    RETRY_WAIT = "retry_wait"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


_READY_STATUSES = frozenset({LiveActionStatus.QUEUED, LiveActionStatus.RETRY_WAIT})
_ACTIVE_STATUSES = frozenset(
    {
        LiveActionStatus.QUEUED,
        LiveActionStatus.CLAIMED,
        LiveActionStatus.RUNNING,
        LiveActionStatus.RETRY_WAIT,
    }
)


@dataclass(slots=True)
class LiveActionRecord:
    """A durable request to perform one managed-account Telegram action."""

    action_id: str
    campaign_id: str
    account_id: str
    action_type: LiveActionType
    payload: dict[str, Any] = field(default_factory=dict)
    conversation_id: str = ""
    source_batch_id: str = ""
    source_prepared_item_id: str = ""
    source_plan_artifact_id: str = ""
    status: LiveActionStatus = LiveActionStatus.QUEUED
    idempotency_key: str = ""
    retry_count: int = 0
    max_retries: int = 3
    next_attempt_at: datetime | None = None
    claimed_by: str = ""
    claimed_at: datetime | None = None
    claim_expires_at: datetime | None = None
    last_error: str = ""
    terminal_failure_reason: str = ""
    last_result_summary: str = ""
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    completed_at: datetime | None = None

    def touch(self) -> None:
        """Refresh the update timestamp after a mutation."""
        self.updated_at = utc_now()

    def is_ready(self, *, now: datetime | None = None) -> bool:
        """Return whether this action can be claimed for execution."""
        if self.status not in _READY_STATUSES:
            return False
        current_time = now or utc_now()
        return self.next_attempt_at is None or self.next_attempt_at <= current_time

    def is_active(self) -> bool:
        """Return whether this action still represents pending external behavior."""
        return self.status in _ACTIVE_STATUSES

    def to_dict(self) -> dict[str, Any]:
        """Serialize the action for JSON-backed persistence."""
        return {
            "action_id": self.action_id,
            "campaign_id": self.campaign_id,
            "account_id": self.account_id,
            "action_type": self.action_type.value,
            "payload": dict(self.payload),
            "conversation_id": self.conversation_id,
            "source_batch_id": self.source_batch_id,
            "source_prepared_item_id": self.source_prepared_item_id,
            "source_plan_artifact_id": self.source_plan_artifact_id,
            "status": self.status.value,
            "idempotency_key": self.idempotency_key,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "next_attempt_at": self.next_attempt_at.isoformat() if self.next_attempt_at else None,
            "claimed_by": self.claimed_by,
            "claimed_at": self.claimed_at.isoformat() if self.claimed_at else None,
            "claim_expires_at": self.claim_expires_at.isoformat() if self.claim_expires_at else None,
            "last_error": self.last_error,
            "terminal_failure_reason": self.terminal_failure_reason,
            "last_result_summary": self.last_result_summary,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "LiveActionRecord":
        """Hydrate a live action from persisted JSON."""
        payload = payload or {}
        raw_action_type = str(payload.get("action_type", LiveActionType.SEND_GROUP_MESSAGE.value))
        raw_status = str(payload.get("status", LiveActionStatus.QUEUED.value))
        raw_payload = payload.get("payload", {})
        return cls(
            action_id=str(payload.get("action_id", "")).strip(),
            campaign_id=str(payload.get("campaign_id", "")).strip(),
            account_id=str(payload.get("account_id", "")).strip(),
            action_type=LiveActionType._value2member_map_.get(raw_action_type, LiveActionType.SEND_GROUP_MESSAGE),
            payload=dict(raw_payload) if isinstance(raw_payload, dict) else {},
            conversation_id=str(payload.get("conversation_id", "")).strip(),
            source_batch_id=str(payload.get("source_batch_id", "")).strip(),
            source_prepared_item_id=str(payload.get("source_prepared_item_id", "")).strip(),
            source_plan_artifact_id=str(payload.get("source_plan_artifact_id", "")).strip(),
            status=LiveActionStatus._value2member_map_.get(raw_status, LiveActionStatus.QUEUED),
            idempotency_key=str(payload.get("idempotency_key", "")).strip(),
            retry_count=max(int(payload.get("retry_count", 0) or 0), 0),
            max_retries=max(int(payload.get("max_retries", 3) or 0), 0),
            next_attempt_at=parse_datetime(str(payload.get("next_attempt_at", "")).strip()),
            claimed_by=str(payload.get("claimed_by", "")).strip(),
            claimed_at=parse_datetime(str(payload.get("claimed_at", "")).strip()),
            claim_expires_at=parse_datetime(str(payload.get("claim_expires_at", "")).strip()),
            last_error=str(payload.get("last_error", "")),
            terminal_failure_reason=str(payload.get("terminal_failure_reason", "")),
            last_result_summary=str(payload.get("last_result_summary", "")),
            created_at=parse_datetime(str(payload.get("created_at", "")).strip()) or utc_now(),
            updated_at=parse_datetime(str(payload.get("updated_at", "")).strip()) or utc_now(),
            completed_at=parse_datetime(str(payload.get("completed_at", "")).strip()),
        )


@dataclass(slots=True)
class LiveActionAttemptRecord:
    """One bounded execution attempt linked back to a live action."""

    attempt_id: str
    action_id: str
    campaign_id: str
    account_id: str
    action_type: LiveActionType
    conversation_id: str = ""
    attempt_number: int = 1
    outcome_code: str = ""
    started_at: datetime = field(default_factory=utc_now)
    finished_at: datetime = field(default_factory=utc_now)
    error: str = ""
    wait_seconds: int | None = None
    result_data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the attempt record for append-only persistence."""
        return {
            "attempt_id": self.attempt_id,
            "action_id": self.action_id,
            "campaign_id": self.campaign_id,
            "account_id": self.account_id,
            "action_type": self.action_type.value,
            "conversation_id": self.conversation_id,
            "attempt_number": self.attempt_number,
            "outcome_code": self.outcome_code,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "error": self.error,
            "wait_seconds": self.wait_seconds,
            "result_data": dict(self.result_data),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "LiveActionAttemptRecord":
        """Hydrate one attempt record from persisted JSON."""
        payload = payload or {}
        raw_action_type = str(payload.get("action_type", LiveActionType.SEND_GROUP_MESSAGE.value))
        raw_result_data = payload.get("result_data", {})
        return cls(
            attempt_id=str(payload.get("attempt_id", "")).strip(),
            action_id=str(payload.get("action_id", "")).strip(),
            campaign_id=str(payload.get("campaign_id", "")).strip(),
            account_id=str(payload.get("account_id", "")).strip(),
            action_type=LiveActionType._value2member_map_.get(raw_action_type, LiveActionType.SEND_GROUP_MESSAGE),
            conversation_id=str(payload.get("conversation_id", "")).strip(),
            attempt_number=max(int(payload.get("attempt_number", 1) or 1), 1),
            outcome_code=str(payload.get("outcome_code", "")).strip(),
            started_at=parse_datetime(str(payload.get("started_at", "")).strip()) or utc_now(),
            finished_at=parse_datetime(str(payload.get("finished_at", "")).strip()) or utc_now(),
            error=str(payload.get("error", "")),
            wait_seconds=int(payload["wait_seconds"]) if payload.get("wait_seconds") is not None else None,
            result_data=dict(raw_result_data) if isinstance(raw_result_data, dict) else {},
        )
