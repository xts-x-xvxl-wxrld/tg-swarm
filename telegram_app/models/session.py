"""Session state records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class SessionStatus(StrEnum):
    """Lifecycle states for an operator session."""

    NEW = "new"
    ACTIVE = "active"
    PENDING_APPROVAL = "pending_approval"
    COMPLETED = "completed"
    ARCHIVED = "archived"


@dataclass(slots=True)
class SessionRecord:
    """Durable session state tracked across operator interactions."""

    session_id: str
    operator_id: str
    status: SessionStatus = SessionStatus.NEW
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    latest_operator_message: str = ""
    workflow_state: dict[str, Any] = field(default_factory=dict)
    linked_entity_ids: dict[str, str] = field(default_factory=dict)
    pending_approval_id: str | None = None

    def touch(self) -> None:
        """Refresh the session timestamp after a mutation."""
        self.updated_at = datetime.now(UTC)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the session for JSON-backed runtime storage."""
        return {
            "session_id": self.session_id,
            "operator_id": self.operator_id,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "latest_operator_message": self.latest_operator_message,
            "workflow_state": dict(self.workflow_state),
            "linked_entity_ids": dict(self.linked_entity_ids),
            "pending_approval_id": self.pending_approval_id,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "SessionRecord":
        """Hydrate a session from persisted JSON state."""
        payload = payload or {}
        raw_status = payload.get("status", SessionStatus.NEW.value)
        status = SessionStatus._value2member_map_.get(raw_status, SessionStatus.NEW)
        workflow_state = payload.get("workflow_state", {})
        linked_entity_ids = payload.get("linked_entity_ids", {})
        return cls(
            session_id=str(payload.get("session_id", "")),
            operator_id=str(payload.get("operator_id", "")),
            status=status,
            created_at=datetime.fromisoformat(payload["created_at"])
            if payload.get("created_at")
            else datetime.now(UTC),
            updated_at=datetime.fromisoformat(payload["updated_at"])
            if payload.get("updated_at")
            else datetime.now(UTC),
            latest_operator_message=str(payload.get("latest_operator_message", "")),
            workflow_state=dict(workflow_state) if isinstance(workflow_state, dict) else {},
            linked_entity_ids=dict(linked_entity_ids) if isinstance(linked_entity_ids, dict) else {},
            pending_approval_id=payload.get("pending_approval_id"),
        )
