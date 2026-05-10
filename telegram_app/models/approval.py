"""Approval state records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class ApprovalStatus(StrEnum):
    """States for approval requests."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class ApprovalRecord:
    """Approval request tied to a session."""

    approval_id: str
    session_id: str
    category: str
    prompt: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    context: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    resolved_at: datetime | None = None
    resolution_note: str = ""

    def resolve(self, status: ApprovalStatus, note: str = "") -> None:
        """Resolve the approval with a terminal status."""
        if status is ApprovalStatus.PENDING:
            msg = "Pending is not a terminal approval status."
            raise ValueError(msg)
        self.status = status
        self.resolution_note = note
        self.resolved_at = datetime.now(UTC)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the approval for JSON-backed runtime storage."""
        return {
            "approval_id": self.approval_id,
            "session_id": self.session_id,
            "category": self.category,
            "prompt": self.prompt,
            "status": self.status.value,
            "context": dict(self.context),
            "created_at": self.created_at.isoformat(),
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at is not None else None,
            "resolution_note": self.resolution_note,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "ApprovalRecord":
        """Hydrate an approval from persisted JSON state."""
        payload = payload or {}
        raw_status = payload.get("status", ApprovalStatus.PENDING.value)
        status = ApprovalStatus._value2member_map_.get(raw_status, ApprovalStatus.PENDING)
        context = payload.get("context", {})
        return cls(
            approval_id=str(payload.get("approval_id", "")),
            session_id=str(payload.get("session_id", "")),
            category=str(payload.get("category", "")),
            prompt=str(payload.get("prompt", "")),
            status=status,
            context=dict(context) if isinstance(context, dict) else {},
            created_at=datetime.fromisoformat(payload["created_at"])
            if payload.get("created_at")
            else datetime.now(UTC),
            resolved_at=datetime.fromisoformat(payload["resolved_at"])
            if payload.get("resolved_at")
            else None,
            resolution_note=str(payload.get("resolution_note", "")),
        )
