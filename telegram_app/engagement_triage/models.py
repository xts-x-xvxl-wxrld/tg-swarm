"""Structured low-cost inbound triage contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class TriageInterestLevel(StrEnum):
    """Coarse commercial-interest levels for one review moment."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TriageUrgencyLevel(StrEnum):
    """Coarse urgency levels for one review moment."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TriageReviewPriority(StrEnum):
    """Priority assigned by the cheap triage layer."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TriagePromotionDecision(StrEnum):
    """Whether triage should hand the thread to the deeper review layer."""

    COMPLETE_IN_TRIAGE = "complete_in_triage"
    PROMOTE_TO_DEEP_REVIEW = "promote_to_deep_review"


@dataclass(slots=True)
class ConversationTriageState:
    """Durable cheap-triage state persisted on one conversation."""

    interest_level: TriageInterestLevel = TriageInterestLevel.LOW
    urgency_level: TriageUrgencyLevel = TriageUrgencyLevel.LOW
    objection_present: bool = False
    objection_hints: list[str] = field(default_factory=list)
    hostile_signal: bool = False
    negative_signal_labels: list[str] = field(default_factory=list)
    low_signal_chatter: bool = False
    review_priority: TriageReviewPriority = TriageReviewPriority.LOW
    promotion_decision: TriagePromotionDecision = TriagePromotionDecision.COMPLETE_IN_TRIAGE
    promoted_to_deep_review: bool = False
    triage_summary: str = ""
    last_triaged_at: datetime | None = None
    last_trigger_key: str = ""
    last_trigger_source: str = ""

    def __post_init__(self) -> None:
        self.objection_hints = _string_list(self.objection_hints)
        self.negative_signal_labels = _string_list(self.negative_signal_labels)
        self.promoted_to_deep_review = (
            self.promoted_to_deep_review
            or self.promotion_decision is TriagePromotionDecision.PROMOTE_TO_DEEP_REVIEW
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the triage state for JSON persistence."""
        return {
            "interest_level": self.interest_level.value,
            "urgency_level": self.urgency_level.value,
            "objection_present": self.objection_present,
            "objection_hints": list(self.objection_hints),
            "hostile_signal": self.hostile_signal,
            "negative_signal_labels": list(self.negative_signal_labels),
            "low_signal_chatter": self.low_signal_chatter,
            "review_priority": self.review_priority.value,
            "promotion_decision": self.promotion_decision.value,
            "promoted_to_deep_review": (
                self.promoted_to_deep_review
                or self.promotion_decision is TriagePromotionDecision.PROMOTE_TO_DEEP_REVIEW
            ),
            "triage_summary": self.triage_summary.strip(),
            "last_triaged_at": self.last_triaged_at.isoformat() if self.last_triaged_at else "",
            "last_trigger_key": self.last_trigger_key.strip(),
            "last_trigger_source": self.last_trigger_source.strip(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "ConversationTriageState":
        """Hydrate durable triage state from JSON."""
        payload = payload or {}
        promotion_decision = _triage_promotion_decision(payload.get("promotion_decision"))
        return cls(
            interest_level=_triage_interest_level(payload.get("interest_level")),
            urgency_level=_triage_urgency_level(payload.get("urgency_level")),
            objection_present=bool(payload.get("objection_present", False)),
            objection_hints=_string_list(payload.get("objection_hints")),
            hostile_signal=bool(payload.get("hostile_signal", False)),
            negative_signal_labels=_string_list(payload.get("negative_signal_labels")),
            low_signal_chatter=bool(payload.get("low_signal_chatter", False)),
            review_priority=_triage_review_priority(payload.get("review_priority")),
            promotion_decision=promotion_decision,
            promoted_to_deep_review=_bool_from_payload(
                payload.get("promoted_to_deep_review"),
                default=promotion_decision is TriagePromotionDecision.PROMOTE_TO_DEEP_REVIEW,
            ),
            triage_summary=str(payload.get("triage_summary", "")).strip(),
            last_triaged_at=_parse_datetime(payload.get("last_triaged_at")),
            last_trigger_key=str(payload.get("last_trigger_key", "")).strip(),
            last_trigger_source=str(payload.get("last_trigger_source", "")).strip(),
        )


@dataclass(slots=True)
class InboundTriageResult:
    """Normalized outcome from one cheap inbound triage pass."""

    triage_state: ConversationTriageState
    should_promote: bool
    summary: str = ""
    reasons: list[str] = field(default_factory=list)


def _triage_interest_level(value: object) -> TriageInterestLevel:
    normalized = str(value or "").strip().lower()
    return TriageInterestLevel._value2member_map_.get(normalized, TriageInterestLevel.LOW)


def _triage_urgency_level(value: object) -> TriageUrgencyLevel:
    normalized = str(value or "").strip().lower()
    return TriageUrgencyLevel._value2member_map_.get(normalized, TriageUrgencyLevel.LOW)


def _triage_review_priority(value: object) -> TriageReviewPriority:
    normalized = str(value or "").strip().lower()
    return TriageReviewPriority._value2member_map_.get(normalized, TriageReviewPriority.LOW)


def _triage_promotion_decision(value: object) -> TriagePromotionDecision:
    normalized = str(value or "").strip().lower()
    return TriagePromotionDecision._value2member_map_.get(
        normalized,
        TriagePromotionDecision.COMPLETE_IN_TRIAGE,
    )


def _parse_datetime(value: object) -> datetime | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    return datetime.fromisoformat(normalized)


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _bool_from_payload(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    return default
