"""Durable work-item records for campaign operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class WorkItemStatus(StrEnum):
    """Lifecycle states for campaign work items."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    REVIEW_PENDING = "review_pending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ESCALATED = "escalated"


class WorkItemPriority(StrEnum):
    """Relative urgency for campaign work items."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(slots=True)
class WorkItemRecord:
    """A bounded unit of campaign work assigned to one role."""

    work_item_id: str
    campaign_id: str
    owner_role: str
    work_type: str
    goal: str
    constraints: list[str] = field(default_factory=list)
    priority: WorkItemPriority = WorkItemPriority.MEDIUM
    status: WorkItemStatus = WorkItemStatus.PENDING
    due_at: datetime | None = None
    related_memory_refs: list[str] = field(default_factory=list)
    result_summary: str = ""
    escalation_reason: str = ""
    schedule_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None

    def touch(self) -> None:
        """Refresh the update timestamp after a mutation."""
        self.updated_at = datetime.now(UTC)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the work item for JSON-backed persistence."""
        return {
            "work_item_id": self.work_item_id,
            "campaign_id": self.campaign_id,
            "owner_role": self.owner_role,
            "work_type": self.work_type,
            "goal": self.goal,
            "constraints": list(self.constraints),
            "priority": self.priority.value,
            "status": self.status.value,
            "due_at": self.due_at.isoformat() if self.due_at is not None else None,
            "related_memory_refs": list(self.related_memory_refs),
            "result_summary": self.result_summary,
            "escalation_reason": self.escalation_reason,
            "schedule_id": self.schedule_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at is not None else None,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "WorkItemRecord":
        """Hydrate a work item from persisted JSON state."""
        payload = payload or {}
        raw_priority = payload.get("priority", WorkItemPriority.MEDIUM.value)
        priority = WorkItemPriority._value2member_map_.get(raw_priority, WorkItemPriority.MEDIUM)
        raw_status = payload.get("status", WorkItemStatus.PENDING.value)
        status = WorkItemStatus._value2member_map_.get(raw_status, WorkItemStatus.PENDING)
        constraints = payload.get("constraints", [])
        related_memory_refs = payload.get("related_memory_refs", [])
        return cls(
            work_item_id=str(payload.get("work_item_id", "")),
            campaign_id=str(payload.get("campaign_id", "")),
            owner_role=str(payload.get("owner_role", "")),
            work_type=str(payload.get("work_type", "")),
            goal=str(payload.get("goal", "")),
            constraints=list(constraints) if isinstance(constraints, list) else [],
            priority=priority,
            status=status,
            due_at=datetime.fromisoformat(payload["due_at"]) if payload.get("due_at") else None,
            related_memory_refs=list(related_memory_refs) if isinstance(related_memory_refs, list) else [],
            result_summary=str(payload.get("result_summary", "")),
            escalation_reason=str(payload.get("escalation_reason", "")),
            schedule_id=payload.get("schedule_id"),
            created_at=datetime.fromisoformat(payload["created_at"])
            if payload.get("created_at")
            else datetime.now(UTC),
            updated_at=datetime.fromisoformat(payload["updated_at"])
            if payload.get("updated_at")
            else datetime.now(UTC),
            completed_at=datetime.fromisoformat(payload["completed_at"])
            if payload.get("completed_at")
            else None,
        )
