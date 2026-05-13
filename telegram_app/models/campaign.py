"""Campaign metadata tracked outside session chat history."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class CampaignStatus(StrEnum):
    """Lifecycle states for a durable campaign workspace."""

    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


@dataclass(slots=True)
class CampaignRecord:
    """Small runtime-oriented metadata for a campaign workspace."""

    campaign_id: str
    operator_id: str
    workspace_path: str
    status: CampaignStatus = CampaignStatus.ACTIVE
    primary_goal: str = ""
    tags: list[str] = field(default_factory=list)
    canonical_files: list[str] = field(default_factory=list)
    agent_memory_files: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def touch(self) -> None:
        """Refresh the update timestamp after a mutation."""
        self.updated_at = datetime.now(UTC)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the campaign for file-backed runtime storage."""
        return {
            "campaign_id": self.campaign_id,
            "operator_id": self.operator_id,
            "workspace_path": self.workspace_path,
            "status": self.status.value,
            "primary_goal": self.primary_goal,
            "tags": list(self.tags),
            "canonical_files": list(self.canonical_files),
            "agent_memory_files": list(self.agent_memory_files),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "CampaignRecord":
        """Hydrate campaign metadata from persisted JSON state."""
        payload = payload or {}
        raw_status = payload.get("status", CampaignStatus.ACTIVE.value)
        status = CampaignStatus._value2member_map_.get(raw_status, CampaignStatus.ACTIVE)
        tags = payload.get("tags", [])
        canonical_files = payload.get("canonical_files", [])
        agent_memory_files = payload.get("agent_memory_files", [])
        return cls(
            campaign_id=str(payload.get("campaign_id", "")),
            operator_id=str(payload.get("operator_id", "")),
            workspace_path=str(payload.get("workspace_path", "")),
            status=status,
            primary_goal=str(payload.get("primary_goal", "")),
            tags=list(tags) if isinstance(tags, list) else [],
            canonical_files=list(canonical_files) if isinstance(canonical_files, list) else [],
            agent_memory_files=list(agent_memory_files) if isinstance(agent_memory_files, list) else [],
            created_at=datetime.fromisoformat(payload["created_at"])
            if payload.get("created_at")
            else datetime.now(UTC),
            updated_at=datetime.fromisoformat(payload["updated_at"])
            if payload.get("updated_at")
            else datetime.now(UTC),
        )
