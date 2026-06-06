"""Structured contracts for operator-facing live-ops chat control."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


def utc_now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(UTC)


def parse_datetime(value: str | None) -> datetime | None:
    """Parse an ISO 8601 datetime when the value is present."""
    if value is None:
        return None
    normalized = value.strip()
    if not normalized or normalized.lower() in {"none", "null"}:
        return None
    return datetime.fromisoformat(normalized)


class LiveOpsIntentKind(StrEnum):
    """Normalized live-ops intent families resolved from operator chat."""

    SHOW_STATUS = "show_status"
    SHOW_ATTENTION = "show_attention"
    SHOW_BLOCKED = "show_blocked"
    SHOW_BLOCK_REASON = "show_block_reason"
    SHOW_PENDING_REVIEWS = "show_pending_reviews"
    APPROVE_REVIEW = "approve_review"
    DISMISS_REVIEW = "dismiss_review"
    PAUSE_SCOPE = "pause_scope"
    RESUME_SCOPE = "resume_scope"
    SET_POSTURE = "set_posture"
    UPDATE_VOICE = "update_voice"
    UPDATE_SAFEGUARD = "update_safeguard"


class LiveOpsScope(StrEnum):
    """Supported scope targets for live-ops controls."""

    CAMPAIGN = "campaign"
    ACCOUNT = "account"
    CONVERSATION = "conversation"
    REVIEW = "review"


class ControlCompletenessStatus(StrEnum):
    """Compact readiness states for operator-facing campaign controls."""

    UNSET = "unset"
    DEFAULT = "default"
    PARTIAL = "partial"
    CONFIRMED = "confirmed"
    AMBIGUOUS = "ambiguous"


@dataclass(slots=True)
class LiveOpsIntent:
    """Parsed operator request that should route through deterministic live-ops code."""

    kind: LiveOpsIntentKind
    scope: LiveOpsScope = LiveOpsScope.CAMPAIGN
    raw_text: str = ""
    campaign_id: str = ""
    account_id: str = ""
    conversation_id: str = ""
    review_id: str = ""
    posture_field: str = ""
    requested_mode: str = ""


@dataclass(slots=True)
class OperatorVoiceProfile:
    """Durable operator-owned live reply voice overrides."""

    tone_descriptors: list[str] = field(default_factory=list)
    style_do: list[str] = field(default_factory=list)
    style_avoid: list[str] = field(default_factory=list)
    cta_style: str = ""
    emoji_policy: str = ""
    evidence_style: str = ""

    def has_any(self) -> bool:
        """Return whether any operator override is currently defined."""
        return bool(
            self.tone_descriptors
            or self.style_do
            or self.style_avoid
            or self.cta_style
            or self.emoji_policy
            or self.evidence_style
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the voice profile for JSON persistence."""
        return {
            "tone_descriptors": list(self.tone_descriptors),
            "style_do": list(self.style_do),
            "style_avoid": list(self.style_avoid),
            "cta_style": self.cta_style,
            "emoji_policy": self.emoji_policy,
            "evidence_style": self.evidence_style,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "OperatorVoiceProfile":
        """Hydrate one operator voice profile from JSON."""
        payload = payload or {}
        return cls(
            tone_descriptors=_string_list(payload.get("tone_descriptors")),
            style_do=_string_list(payload.get("style_do")),
            style_avoid=_string_list(payload.get("style_avoid")),
            cta_style=str(payload.get("cta_style", "")).strip(),
            emoji_policy=str(payload.get("emoji_policy", "")).strip(),
            evidence_style=str(payload.get("evidence_style", "")).strip(),
        )


@dataclass(slots=True)
class OperatorApprovedClaim:
    """One operator-managed approved claim override."""

    claim_id: str
    text: str
    evidence_basis: str = ""
    usage_notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize one approved claim override."""
        return {
            "claim_id": self.claim_id,
            "text": self.text,
            "evidence_basis": self.evidence_basis,
            "usage_notes": self.usage_notes,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "OperatorApprovedClaim":
        """Hydrate one approved claim override from JSON."""
        payload = payload or {}
        return cls(
            claim_id=str(payload.get("claim_id", "")).strip(),
            text=str(payload.get("text", "")).strip(),
            evidence_basis=str(payload.get("evidence_basis", "")).strip(),
            usage_notes=str(payload.get("usage_notes", "")).strip(),
        )


@dataclass(slots=True)
class OperatorGuardrail:
    """One operator-managed safeguard or forbidden-claim override."""

    label: str
    instruction: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize one operator guardrail."""
        return {
            "label": self.label,
            "instruction": self.instruction,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "OperatorGuardrail":
        """Hydrate one operator guardrail from JSON."""
        payload = payload or {}
        return cls(
            label=str(payload.get("label", "")).strip(),
            instruction=str(payload.get("instruction", "")).strip(),
        )


@dataclass(slots=True)
class LiveOpsControlProfile:
    """Campaign-scoped durable operator controls for live operations."""

    campaign_id: str
    operator_preferences: list[str] = field(default_factory=list)
    voice_profile: OperatorVoiceProfile = field(default_factory=OperatorVoiceProfile)
    approved_claims: list[OperatorApprovedClaim] = field(default_factory=list)
    forbidden_claims: list[OperatorGuardrail] = field(default_factory=list)
    community_tone_guidance: list[str] = field(default_factory=list)
    escalation_rules: list[str] = field(default_factory=list)
    confirmed_areas: list[str] = field(default_factory=list)
    updated_at: datetime = field(default_factory=utc_now)
    updated_by: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize one live-ops control profile."""
        return {
            "campaign_id": self.campaign_id,
            "operator_preferences": list(self.operator_preferences),
            "voice_profile": self.voice_profile.to_dict(),
            "approved_claims": [claim.to_dict() for claim in self.approved_claims],
            "forbidden_claims": [claim.to_dict() for claim in self.forbidden_claims],
            "community_tone_guidance": list(self.community_tone_guidance),
            "escalation_rules": list(self.escalation_rules),
            "confirmed_areas": list(self.confirmed_areas),
            "updated_at": self.updated_at.isoformat(),
            "updated_by": self.updated_by,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "LiveOpsControlProfile":
        """Hydrate one live-ops control profile from JSON."""
        payload = payload or {}
        raw_approved_claims = payload.get("approved_claims", [])
        raw_forbidden_claims = payload.get("forbidden_claims", [])
        return cls(
            campaign_id=str(payload.get("campaign_id", "")).strip(),
            operator_preferences=_string_list(payload.get("operator_preferences")),
            voice_profile=OperatorVoiceProfile.from_dict(payload.get("voice_profile") if isinstance(payload.get("voice_profile"), dict) else {}),
            approved_claims=[
                OperatorApprovedClaim.from_dict(item)
                for item in raw_approved_claims
                if isinstance(raw_approved_claims, list) and isinstance(item, dict)
            ],
            forbidden_claims=[
                OperatorGuardrail.from_dict(item)
                for item in raw_forbidden_claims
                if isinstance(raw_forbidden_claims, list) and isinstance(item, dict)
            ],
            community_tone_guidance=_string_list(payload.get("community_tone_guidance")),
            escalation_rules=_string_list(payload.get("escalation_rules")),
            confirmed_areas=_string_list(payload.get("confirmed_areas")),
            updated_at=parse_datetime(str(payload.get("updated_at", "")).strip()) or utc_now(),
            updated_by=str(payload.get("updated_by", "")).strip(),
        )


@dataclass(slots=True)
class ControlAreaState:
    """One operator-visible control area and its current completeness."""

    area_key: str
    label: str
    status: ControlCompletenessStatus
    summary: str
    default_is_acceptable: bool = False


@dataclass(slots=True)
class AttentionItem:
    """One compact operator-facing item that currently needs attention."""

    item_type: str
    item_id: str
    summary: str
    recommended_action: str
    reason_code: str = ""
    conversation_id: str = ""
    account_id: str = ""


@dataclass(slots=True)
class CampaignLiveOpsSnapshot:
    """Compact campaign status view for Telegram-facing live-ops reporting."""

    campaign_id: str
    campaign_status: str
    primary_goal: str = ""
    activation_status: str = ""
    latest_batch_id: str = ""
    queued_count: int = 0
    retry_wait_count: int = 0
    running_count: int = 0
    blocked_count: int = 0
    recent_success_count: int = 0
    pending_autonomous_review_count: int = 0
    paused_conversation_count: int = 0
    escalated_conversation_count: int = 0
    review_inbound_count: int = 0
    follow_up_due_count: int = 0
    commercial_summary: str = ""
    promising_active_thread_count: int = 0
    objection_heavy_thread_count: int = 0
    conversion_ready_thread_count: int = 0
    unresolved_high_opportunity_thread_count: int = 0
    stale_promising_thread_count: int = 0
    high_yield_account_labels: list[str] = field(default_factory=list)
    high_yield_community_labels: list[str] = field(default_factory=list)
    group_reply_mode: str = ""
    dm_reply_mode: str = ""
    blocked_reasons: list[str] = field(default_factory=list)
    attention_items: list[AttentionItem] = field(default_factory=list)
    control_areas: list[ControlAreaState] = field(default_factory=list)
    recommended_next_action: str = ""


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        text = str(item).strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized
