"""Structured contracts for campaign qualification and handoff state."""

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


class HandoffStatus(StrEnum):
    """Lifecycle states for one campaign-linked conversion handoff."""

    NONE = "none"
    READY = "ready"
    CLARIFICATION_REQUIRED = "clarification_required"
    DELIVERED = "delivered"
    BLOCKED = "blocked"
    FAILED = "failed"


@dataclass(slots=True)
class CampaignQualificationFrame:
    """Compact campaign-owned qualification frame derived from campaign artifacts."""

    campaign_id: str
    summary: str = ""
    offer_summary: str = ""
    target_audience_summary: str = ""
    qualification_posture: str = ""
    conversion_target_summary: str = ""
    conversion_target_kind: str = ""
    conversion_target_value: str = ""
    handoff_action_types: list[str] = field(default_factory=list)
    qualification_signals: list[str] = field(default_factory=list)
    updated_at: datetime = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the frame for JSON-backed persistence."""
        return {
            "campaign_id": self.campaign_id,
            "summary": self.summary,
            "offer_summary": self.offer_summary,
            "target_audience_summary": self.target_audience_summary,
            "qualification_posture": self.qualification_posture,
            "conversion_target_summary": self.conversion_target_summary,
            "conversion_target_kind": self.conversion_target_kind,
            "conversion_target_value": self.conversion_target_value,
            "handoff_action_types": list(self.handoff_action_types),
            "qualification_signals": list(self.qualification_signals),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "CampaignQualificationFrame":
        """Hydrate a persisted frame payload."""
        payload = payload or {}
        raw_handoff_action_types = payload.get("handoff_action_types", [])
        raw_qualification_signals = payload.get("qualification_signals", [])
        return cls(
            campaign_id=str(payload.get("campaign_id", "")).strip(),
            summary=str(payload.get("summary", "")).strip(),
            offer_summary=str(payload.get("offer_summary", "")).strip(),
            target_audience_summary=str(payload.get("target_audience_summary", "")).strip(),
            qualification_posture=str(payload.get("qualification_posture", "")).strip(),
            conversion_target_summary=str(payload.get("conversion_target_summary", "")).strip(),
            conversion_target_kind=str(payload.get("conversion_target_kind", "")).strip(),
            conversion_target_value=str(payload.get("conversion_target_value", "")).strip(),
            handoff_action_types=[
                str(value).strip()
                for value in raw_handoff_action_types
                if isinstance(raw_handoff_action_types, list) and str(value).strip()
            ],
            qualification_signals=[
                str(value).strip()
                for value in raw_qualification_signals
                if isinstance(raw_qualification_signals, list) and str(value).strip()
            ],
            updated_at=parse_datetime(str(payload.get("updated_at", "")).strip()) or utc_now(),
        )
