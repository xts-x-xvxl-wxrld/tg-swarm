"""Campaign-owned contracts for autonomous send authorization."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


def utc_now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(UTC)


def parse_datetime(value: str | None) -> datetime | None:
    """Parse an ISO 8601 datetime or return None for empty values."""
    if value is None:
        return None
    normalized = value.strip()
    if not normalized or normalized.lower() in {"none", "null"}:
        return None
    return datetime.fromisoformat(normalized)


class AutonomousSendMode(StrEnum):
    """Campaign-level posture for one autonomous send family."""

    MANUAL_ONLY = "manual_only"
    AUTONOMOUS_ALLOWED = "autonomous_allowed"


class AutonomousSendDecisionType(StrEnum):
    """Normalized authorization outcomes for one proposed send."""

    ALLOWED = "allowed"
    BLOCKED = "blocked"


class AutonomousSendReviewStatus(StrEnum):
    """Lifecycle states for one durable review-needed record."""

    PENDING = "pending"
    MATERIALIZED = "materialized"
    DISMISSED = "dismissed"
    SUPERSEDED = "superseded"


@dataclass(slots=True)
class AutonomousSendPosture:
    """Campaign-scoped autonomous send settings."""

    campaign_id: str
    group_outreach_mode: AutonomousSendMode = AutonomousSendMode.AUTONOMOUS_ALLOWED
    group_reply_mode: AutonomousSendMode = AutonomousSendMode.AUTONOMOUS_ALLOWED
    dm_reply_mode: AutonomousSendMode = AutonomousSendMode.AUTONOMOUS_ALLOWED
    updated_at: datetime = field(default_factory=utc_now)
    updated_by: str = ""
    notes: str = ""

    def mode_for_action(self, action_type: str) -> AutonomousSendMode:
        """Return the autonomous posture for a normalized action type."""
        normalized_action_type = action_type.strip()
        if normalized_action_type == "send_group_reply":
            return self.group_reply_mode
        if normalized_action_type == "send_dm_reply":
            return self.dm_reply_mode
        return self.group_outreach_mode

    def to_dict(self) -> dict[str, Any]:
        """Serialize the posture for JSON-backed persistence."""
        return {
            "campaign_id": self.campaign_id,
            "group_outreach_mode": self.group_outreach_mode.value,
            "group_reply_mode": self.group_reply_mode.value,
            "dm_reply_mode": self.dm_reply_mode.value,
            "updated_at": self.updated_at.isoformat(),
            "updated_by": self.updated_by,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "AutonomousSendPosture":
        """Hydrate a posture from persisted JSON."""
        payload = payload or {}
        return cls(
            campaign_id=str(payload.get("campaign_id", "")).strip(),
            group_outreach_mode=AutonomousSendMode(
                str(payload.get("group_outreach_mode", AutonomousSendMode.AUTONOMOUS_ALLOWED.value)).strip()
                or AutonomousSendMode.AUTONOMOUS_ALLOWED.value
            ),
            group_reply_mode=AutonomousSendMode(
                str(payload.get("group_reply_mode", AutonomousSendMode.AUTONOMOUS_ALLOWED.value)).strip()
                or AutonomousSendMode.AUTONOMOUS_ALLOWED.value
            ),
            dm_reply_mode=AutonomousSendMode(
                str(payload.get("dm_reply_mode", AutonomousSendMode.AUTONOMOUS_ALLOWED.value)).strip()
                or AutonomousSendMode.AUTONOMOUS_ALLOWED.value
            ),
            updated_at=parse_datetime(str(payload.get("updated_at", "")).strip()) or utc_now(),
            updated_by=str(payload.get("updated_by", "")).strip(),
            notes=str(payload.get("notes", "")).strip(),
        )


@dataclass(slots=True)
class AutonomousSendReviewRecord:
    """One durable review-needed proposal that was grounded but not auto-sendable."""

    review_id: str
    campaign_id: str
    conversation_id: str
    account_id: str
    action_type: str
    status: AutonomousSendReviewStatus = AutonomousSendReviewStatus.PENDING
    draft_text: str = ""
    goal: str = ""
    qualification_state: str = ""
    presentation_hints: list[str] = field(default_factory=list)
    approved_claim_ids_used: list[str] = field(default_factory=list)
    community_risk_level: str = ""
    conversation_risk_level: str = ""
    autonomous_send_mode: str = ""
    trigger_key: str = ""
    trigger_source: str = ""
    context_fingerprint: str = ""
    reason_codes: list[str] = field(default_factory=list)
    summary: str = ""
    created_at: datetime = field(default_factory=utc_now)
    resolved_at: datetime | None = None
    resolved_by: str = ""
    resolution_note: str = ""
    materialized_action_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize the review record for JSON-backed persistence."""
        return {
            "review_id": self.review_id,
            "campaign_id": self.campaign_id,
            "conversation_id": self.conversation_id,
            "account_id": self.account_id,
            "action_type": self.action_type,
            "status": self.status.value,
            "draft_text": self.draft_text,
            "goal": self.goal,
            "qualification_state": self.qualification_state,
            "presentation_hints": list(self.presentation_hints),
            "approved_claim_ids_used": list(self.approved_claim_ids_used),
            "community_risk_level": self.community_risk_level,
            "conversation_risk_level": self.conversation_risk_level,
            "autonomous_send_mode": self.autonomous_send_mode,
            "trigger_key": self.trigger_key,
            "trigger_source": self.trigger_source,
            "context_fingerprint": self.context_fingerprint,
            "reason_codes": list(self.reason_codes),
            "summary": self.summary,
            "created_at": self.created_at.isoformat(),
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at is not None else None,
            "resolved_by": self.resolved_by,
            "resolution_note": self.resolution_note,
            "materialized_action_id": self.materialized_action_id,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "AutonomousSendReviewRecord":
        """Hydrate one review record from persisted JSON."""
        payload = payload or {}
        raw_hints = payload.get("presentation_hints", [])
        raw_claim_ids = payload.get("approved_claim_ids_used", [])
        raw_reason_codes = payload.get("reason_codes", [])
        return cls(
            review_id=str(payload.get("review_id", "")).strip(),
            campaign_id=str(payload.get("campaign_id", "")).strip(),
            conversation_id=str(payload.get("conversation_id", "")).strip(),
            account_id=str(payload.get("account_id", "")).strip(),
            action_type=str(payload.get("action_type", "")).strip(),
            status=AutonomousSendReviewStatus(
                str(payload.get("status", AutonomousSendReviewStatus.PENDING.value)).strip()
                or AutonomousSendReviewStatus.PENDING.value
            ),
            draft_text=str(payload.get("draft_text", "")).strip(),
            goal=str(payload.get("goal", "")).strip(),
            qualification_state=str(payload.get("qualification_state", "")).strip(),
            presentation_hints=[
                str(value).strip()
                for value in raw_hints
                if isinstance(raw_hints, list) and str(value).strip()
            ],
            approved_claim_ids_used=[
                str(value).strip()
                for value in raw_claim_ids
                if isinstance(raw_claim_ids, list) and str(value).strip()
            ],
            community_risk_level=str(payload.get("community_risk_level", "")).strip(),
            conversation_risk_level=str(payload.get("conversation_risk_level", "")).strip(),
            autonomous_send_mode=str(payload.get("autonomous_send_mode", "")).strip(),
            trigger_key=str(payload.get("trigger_key", "")).strip(),
            trigger_source=str(payload.get("trigger_source", "")).strip(),
            context_fingerprint=str(payload.get("context_fingerprint", "")).strip(),
            reason_codes=[
                str(value).strip()
                for value in raw_reason_codes
                if isinstance(raw_reason_codes, list) and str(value).strip()
            ],
            summary=str(payload.get("summary", "")).strip(),
            created_at=parse_datetime(str(payload.get("created_at", "")).strip()) or utc_now(),
            resolved_at=parse_datetime(str(payload.get("resolved_at", "")).strip()),
            resolved_by=str(payload.get("resolved_by", "")).strip(),
            resolution_note=str(payload.get("resolution_note", "")).strip(),
            materialized_action_id=str(payload.get("materialized_action_id", "")).strip(),
        )


@dataclass(slots=True)
class AutonomousSendDecision:
    """Machine-readable authorization result for one proposed send."""

    decision: AutonomousSendDecisionType
    reason_codes: list[str] = field(default_factory=list)
    summary: str = ""
    action_type: str = ""
    campaign_id: str = ""
    conversation_id: str = ""
    trigger_key: str = ""
    context_fingerprint: str = ""
    recommended_operator_action: str = ""
    approval_context: dict[str, object] = field(default_factory=dict)
    review_record_id: str = ""

    def primary_reason_code(self) -> str:
        """Return the highest-signal reason code for compact status fields."""
        return self.reason_codes[0] if self.reason_codes else self.decision.value
