"""Workflow snapshots stored inside session state."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class WorkflowStage(StrEnum):
    """High-level stages for a Telegram-native operator workflow."""

    INTAKE = "intake"
    DISCOVERY = "discovery"
    STRATEGY = "strategy"
    ACCOUNT_PLANNING = "account_planning"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    COMPLETE = "complete"


class WorkflowArtifactKind(StrEnum):
    """Structured artifacts that sessions can accumulate over time."""

    GENERIC = "generic"
    CAMPAIGN_INTENT = "campaign_intent"
    CAMPAIGN_CONTEXT = "campaign_context"
    CONVERSION_TARGET = "conversion_target"
    CAMPAIGN_BRIEF = "campaign_brief"
    COMMUNITY_SHORTLIST = "community_shortlist"
    COMMUNITY_PROFILE = "community_profile"
    STRATEGY_PLAYBOOK = "strategy_playbook"
    ACCOUNT_ASSIGNMENT_PLAN = "account_assignment_plan"
    EXECUTION_REPORT = "execution_report"
    RESEARCH_NOTE = "research_note"


@dataclass(slots=True)
class WorkflowSnapshot:
    """Current workflow picture for a session."""

    stage: WorkflowStage = WorkflowStage.INTAKE
    summary: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the snapshot for JSON-backed session storage."""
        return {
            "stage": self.stage.value,
            "summary": self.summary,
            "data": dict(self.data),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "WorkflowSnapshot":
        """Hydrate a snapshot from persisted session state."""
        payload = payload or {}
        raw_stage = payload.get("stage", WorkflowStage.INTAKE.value)
        stage = WorkflowStage._value2member_map_.get(raw_stage, WorkflowStage.INTAKE)
        data = payload.get("data", {})
        return cls(
            stage=stage,
            summary=str(payload.get("summary", "")),
            data=dict(data) if isinstance(data, dict) else {},
        )


@dataclass(slots=True)
class WorkflowArtifact:
    """Structured workflow output that should survive beyond chat memory."""

    artifact_id: str
    kind: WorkflowArtifactKind = WorkflowArtifactKind.GENERIC
    title: str = ""
    summary: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def touch(self) -> None:
        """Refresh the update timestamp after a mutation."""
        self.updated_at = datetime.now(UTC)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the artifact for JSON-backed session storage."""
        return {
            "artifact_id": self.artifact_id,
            "kind": self.kind.value,
            "title": self.title,
            "summary": self.summary,
            "data": dict(self.data),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "WorkflowArtifact":
        """Hydrate a structured artifact from persisted session state."""
        payload = payload or {}
        raw_kind = payload.get("kind", WorkflowArtifactKind.GENERIC.value)
        kind = WorkflowArtifactKind._value2member_map_.get(raw_kind, WorkflowArtifactKind.GENERIC)
        data = payload.get("data", {})
        return cls(
            artifact_id=str(payload.get("artifact_id", "")),
            kind=kind,
            title=str(payload.get("title", "")),
            summary=str(payload.get("summary", "")),
            data=dict(data) if isinstance(data, dict) else {},
            created_at=datetime.fromisoformat(payload["created_at"])
            if payload.get("created_at")
            else datetime.now(UTC),
            updated_at=datetime.fromisoformat(payload["updated_at"])
            if payload.get("updated_at")
            else datetime.now(UTC),
        )
