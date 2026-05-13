"""Recurring schedule records for campaign maintenance work."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from telegram_app.models.work_item import WorkItemPriority


class ScheduleStatus(StrEnum):
    """Lifecycle states for recurring schedules."""

    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


@dataclass(slots=True)
class ScheduleRecord:
    """A simple interval-based schedule that refreshes campaign work."""

    schedule_id: str
    campaign_id: str
    owner_role: str
    work_type: str
    goal: str
    interval_minutes: int
    next_run_at: datetime
    constraints: list[str] = field(default_factory=list)
    priority: WorkItemPriority = WorkItemPriority.MEDIUM
    evaluation_metric: str = ""
    minimum_value: int | None = None
    pause_after_consecutive_misses: int | None = None
    status: ScheduleStatus = ScheduleStatus.ACTIVE
    last_run_at: datetime | None = None
    consecutive_miss_count: int = 0
    last_outcome_value: int | None = None
    last_outcome_summary: str = ""
    last_error: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def touch(self) -> None:
        """Refresh the update timestamp after a mutation."""
        self.updated_at = datetime.now(UTC)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the schedule for JSON-backed persistence."""
        return {
            "schedule_id": self.schedule_id,
            "campaign_id": self.campaign_id,
            "owner_role": self.owner_role,
            "work_type": self.work_type,
            "goal": self.goal,
            "interval_minutes": self.interval_minutes,
            "next_run_at": self.next_run_at.isoformat(),
            "constraints": list(self.constraints),
            "priority": self.priority.value,
            "evaluation_metric": self.evaluation_metric,
            "minimum_value": self.minimum_value,
            "pause_after_consecutive_misses": self.pause_after_consecutive_misses,
            "status": self.status.value,
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at is not None else None,
            "consecutive_miss_count": self.consecutive_miss_count,
            "last_outcome_value": self.last_outcome_value,
            "last_outcome_summary": self.last_outcome_summary,
            "last_error": self.last_error,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "ScheduleRecord":
        """Hydrate a schedule from persisted JSON state."""
        payload = payload or {}
        raw_priority = payload.get("priority", WorkItemPriority.MEDIUM.value)
        priority = WorkItemPriority._value2member_map_.get(raw_priority, WorkItemPriority.MEDIUM)
        raw_status = payload.get("status", ScheduleStatus.ACTIVE.value)
        status = ScheduleStatus._value2member_map_.get(raw_status, ScheduleStatus.ACTIVE)
        constraints = payload.get("constraints", [])
        return cls(
            schedule_id=str(payload.get("schedule_id", "")),
            campaign_id=str(payload.get("campaign_id", "")),
            owner_role=str(payload.get("owner_role", "")),
            work_type=str(payload.get("work_type", "")),
            goal=str(payload.get("goal", "")),
            interval_minutes=int(payload.get("interval_minutes", 0) or 0),
            next_run_at=datetime.fromisoformat(payload["next_run_at"])
            if payload.get("next_run_at")
            else datetime.now(UTC),
            constraints=list(constraints) if isinstance(constraints, list) else [],
            priority=priority,
            evaluation_metric=str(payload.get("evaluation_metric", "")),
            minimum_value=int(payload["minimum_value"])
            if payload.get("minimum_value") is not None
            else None,
            pause_after_consecutive_misses=int(payload["pause_after_consecutive_misses"])
            if payload.get("pause_after_consecutive_misses") is not None
            else None,
            status=status,
            last_run_at=datetime.fromisoformat(payload["last_run_at"])
            if payload.get("last_run_at")
            else None,
            consecutive_miss_count=int(payload.get("consecutive_miss_count", 0) or 0),
            last_outcome_value=int(payload["last_outcome_value"])
            if payload.get("last_outcome_value") is not None
            else None,
            last_outcome_summary=str(payload.get("last_outcome_summary", "")),
            last_error=str(payload.get("last_error", "")),
            created_at=datetime.fromisoformat(payload["created_at"])
            if payload.get("created_at")
            else datetime.now(UTC),
            updated_at=datetime.fromisoformat(payload["updated_at"])
            if payload.get("updated_at")
            else datetime.now(UTC),
        )
