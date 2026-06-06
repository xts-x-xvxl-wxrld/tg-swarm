"""Runtime records for campaign-level live signals and observation pressure."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


def utc_now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(UTC)


def parse_datetime(value: str | None) -> datetime | None:
    """Parse an ISO 8601 datetime, returning None when the field is empty."""
    if not value:
        return None
    return datetime.fromisoformat(value)


class CampaignSignalSeverity(StrEnum):
    """Relative urgency for one campaign signal."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class CampaignSignalState(StrEnum):
    """Lifecycle states for one campaign signal."""

    UNRESOLVED = "unresolved"
    REVIEWED = "reviewed"
    DISMISSED = "dismissed"
    SUPERSEDED = "superseded"


class CampaignSignalCategory(StrEnum):
    """Commercial direction for one persisted campaign signal."""

    RISK = "risk"
    OPPORTUNITY = "opportunity"
    YIELD = "yield"


class ObservationMaterialChange(StrEnum):
    """Locked yes-or-no output for whether campaign meaning changed."""

    YES = "yes"
    NO = "no"


class ObservationPriorityPressure(StrEnum):
    """Locked observation pressure levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ObservationOperatorAttention(StrEnum):
    """Locked operator-attention requirements."""

    NONE = "none"
    RECOMMENDED = "recommended"
    REQUIRED = "required"


class ObservationRecommendedNextStep(StrEnum):
    """Locked top-level next-step recommendations."""

    KEEP_CURRENT_PLAN = "keep_current_plan"
    REFRESH_STRATEGY = "refresh_strategy"
    REFRESH_ACCOUNT_PLANNING = "refresh_account_planning"
    OPERATOR_REVIEW = "operator_review"


class ObservationWorkItemChangeAction(StrEnum):
    """Locked work-item actions suggested by observation review."""

    NONE = "none"
    REFRESH = "refresh"
    CREATE_IF_MISSING = "create_if_missing"


class ObservationWorkItemType(StrEnum):
    """Planning work families that observation may advise on."""

    STRATEGY = "strategy"
    ACCOUNT_PLANNING = "account_planning"


class ObservationPostureUpdateKind(StrEnum):
    """Advisory posture-update categories from observation review."""

    CAMPAIGN_PAUSE_REVIEW = "campaign_pause_review"
    COMMUNITY_AVOIDANCE_REVIEW = "community_avoidance_review"
    ACCOUNT_REST_REVIEW = "account_rest_review"


@dataclass(slots=True)
class ObservationSuggestedWorkItemChange:
    """One bounded planning-work suggestion from the observation specialist."""

    work_type: ObservationWorkItemType
    action: ObservationWorkItemChangeAction = ObservationWorkItemChangeAction.NONE
    reason: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "work_type": self.work_type.value,
            "action": self.action.value,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "ObservationSuggestedWorkItemChange":
        payload = payload or {}
        raw_work_type = str(payload.get("work_type", ObservationWorkItemType.STRATEGY.value)).strip()
        raw_action = str(payload.get("action", ObservationWorkItemChangeAction.NONE.value)).strip()
        return cls(
            work_type=ObservationWorkItemType._value2member_map_.get(raw_work_type, ObservationWorkItemType.STRATEGY),
            action=ObservationWorkItemChangeAction._value2member_map_.get(
                raw_action,
                ObservationWorkItemChangeAction.NONE,
            ),
            reason=str(payload.get("reason", "")).strip(),
        )


@dataclass(slots=True)
class ObservationSuggestedPostureUpdate:
    """One advisory posture update from the observation specialist."""

    kind: ObservationPostureUpdateKind
    summary: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind.value,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "ObservationSuggestedPostureUpdate":
        payload = payload or {}
        raw_kind = str(payload.get("kind", ObservationPostureUpdateKind.CAMPAIGN_PAUSE_REVIEW.value)).strip()
        return cls(
            kind=ObservationPostureUpdateKind._value2member_map_.get(
                raw_kind,
                ObservationPostureUpdateKind.CAMPAIGN_PAUSE_REVIEW,
            ),
            summary=str(payload.get("summary", "")).strip(),
        )


@dataclass(slots=True)
class ObservationReviewBrief:
    """Structured steering brief returned by the observation specialist."""

    summary: str
    material_change: ObservationMaterialChange
    priority_pressure: ObservationPriorityPressure
    suggested_work_item_changes: list[ObservationSuggestedWorkItemChange] = field(default_factory=list)
    suggested_posture_updates: list[ObservationSuggestedPostureUpdate] = field(default_factory=list)
    operator_attention_needed: ObservationOperatorAttention = ObservationOperatorAttention.NONE
    recommended_next_step: ObservationRecommendedNextStep = ObservationRecommendedNextStep.KEEP_CURRENT_PLAN
    memory_note_lines: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "material_change": self.material_change.value,
            "priority_pressure": self.priority_pressure.value,
            "suggested_work_item_changes": [item.to_dict() for item in self.suggested_work_item_changes],
            "suggested_posture_updates": [item.to_dict() for item in self.suggested_posture_updates],
            "operator_attention_needed": self.operator_attention_needed.value,
            "recommended_next_step": self.recommended_next_step.value,
            "memory_note_lines": list(self.memory_note_lines),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "ObservationReviewBrief":
        payload = payload or {}
        raw_work_item_changes = payload.get("suggested_work_item_changes", [])
        raw_posture_updates = payload.get("suggested_posture_updates", [])
        raw_memory_note_lines = payload.get("memory_note_lines", [])
        return cls(
            summary=str(payload.get("summary", "")).strip(),
            material_change=ObservationMaterialChange._value2member_map_.get(
                str(payload.get("material_change", ObservationMaterialChange.NO.value)).strip(),
                ObservationMaterialChange.NO,
            ),
            priority_pressure=ObservationPriorityPressure._value2member_map_.get(
                str(payload.get("priority_pressure", ObservationPriorityPressure.LOW.value)).strip(),
                ObservationPriorityPressure.LOW,
            ),
            suggested_work_item_changes=[
                ObservationSuggestedWorkItemChange.from_dict(item)
                for item in raw_work_item_changes
                if isinstance(raw_work_item_changes, list) and isinstance(item, dict)
            ],
            suggested_posture_updates=[
                ObservationSuggestedPostureUpdate.from_dict(item)
                for item in raw_posture_updates
                if isinstance(raw_posture_updates, list) and isinstance(item, dict)
            ],
            operator_attention_needed=ObservationOperatorAttention._value2member_map_.get(
                str(payload.get("operator_attention_needed", ObservationOperatorAttention.NONE.value)).strip(),
                ObservationOperatorAttention.NONE,
            ),
            recommended_next_step=ObservationRecommendedNextStep._value2member_map_.get(
                str(
                    payload.get(
                        "recommended_next_step",
                        ObservationRecommendedNextStep.KEEP_CURRENT_PLAN.value,
                    )
                ).strip(),
                ObservationRecommendedNextStep.KEEP_CURRENT_PLAN,
            ),
            memory_note_lines=[
                str(value).strip()
                for value in raw_memory_note_lines
                if isinstance(raw_memory_note_lines, list) and str(value).strip()
            ],
        )


@dataclass(slots=True)
class ObservationReviewResult:
    """Durable persisted review result for one observation work-item run."""

    review_id: str
    campaign_id: str
    work_item_id: str
    trigger_source: str
    review_reason: str
    signal_ids: list[str]
    signal_digest_count: int
    summary: str
    material_change: ObservationMaterialChange
    priority_pressure: ObservationPriorityPressure
    suggested_work_item_changes: list[ObservationSuggestedWorkItemChange] = field(default_factory=list)
    suggested_posture_updates: list[ObservationSuggestedPostureUpdate] = field(default_factory=list)
    operator_attention_needed: ObservationOperatorAttention = ObservationOperatorAttention.NONE
    recommended_next_step: ObservationRecommendedNextStep = ObservationRecommendedNextStep.KEEP_CURRENT_PLAN
    memory_note_lines: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "review_id": self.review_id,
            "campaign_id": self.campaign_id,
            "work_item_id": self.work_item_id,
            "trigger_source": self.trigger_source,
            "review_reason": self.review_reason,
            "signal_ids": list(self.signal_ids),
            "signal_digest_count": self.signal_digest_count,
            "summary": self.summary,
            "material_change": self.material_change.value,
            "priority_pressure": self.priority_pressure.value,
            "suggested_work_item_changes": [item.to_dict() for item in self.suggested_work_item_changes],
            "suggested_posture_updates": [item.to_dict() for item in self.suggested_posture_updates],
            "operator_attention_needed": self.operator_attention_needed.value,
            "recommended_next_step": self.recommended_next_step.value,
            "memory_note_lines": list(self.memory_note_lines),
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "ObservationReviewResult":
        payload = payload or {}
        raw_signal_ids = payload.get("signal_ids", [])
        raw_work_item_changes = payload.get("suggested_work_item_changes", [])
        raw_posture_updates = payload.get("suggested_posture_updates", [])
        raw_memory_note_lines = payload.get("memory_note_lines", [])
        return cls(
            review_id=str(payload.get("review_id", "")).strip(),
            campaign_id=str(payload.get("campaign_id", "")).strip(),
            work_item_id=str(payload.get("work_item_id", "")).strip(),
            trigger_source=str(payload.get("trigger_source", "")).strip(),
            review_reason=str(payload.get("review_reason", "")).strip(),
            signal_ids=[
                str(value).strip()
                for value in raw_signal_ids
                if isinstance(raw_signal_ids, list) and str(value).strip()
            ],
            signal_digest_count=max(int(payload.get("signal_digest_count", 0) or 0), 0),
            summary=str(payload.get("summary", "")).strip(),
            material_change=ObservationMaterialChange._value2member_map_.get(
                str(payload.get("material_change", ObservationMaterialChange.NO.value)).strip(),
                ObservationMaterialChange.NO,
            ),
            priority_pressure=ObservationPriorityPressure._value2member_map_.get(
                str(payload.get("priority_pressure", ObservationPriorityPressure.LOW.value)).strip(),
                ObservationPriorityPressure.LOW,
            ),
            suggested_work_item_changes=[
                ObservationSuggestedWorkItemChange.from_dict(item)
                for item in raw_work_item_changes
                if isinstance(raw_work_item_changes, list) and isinstance(item, dict)
            ],
            suggested_posture_updates=[
                ObservationSuggestedPostureUpdate.from_dict(item)
                for item in raw_posture_updates
                if isinstance(raw_posture_updates, list) and isinstance(item, dict)
            ],
            operator_attention_needed=ObservationOperatorAttention._value2member_map_.get(
                str(payload.get("operator_attention_needed", ObservationOperatorAttention.NONE.value)).strip(),
                ObservationOperatorAttention.NONE,
            ),
            recommended_next_step=ObservationRecommendedNextStep._value2member_map_.get(
                str(
                    payload.get(
                        "recommended_next_step",
                        ObservationRecommendedNextStep.KEEP_CURRENT_PLAN.value,
                    )
                ).strip(),
                ObservationRecommendedNextStep.KEEP_CURRENT_PLAN,
            ),
            memory_note_lines=[
                str(value).strip()
                for value in raw_memory_note_lines
                if isinstance(raw_memory_note_lines, list) and str(value).strip()
            ],
            created_at=parse_datetime(str(payload.get("created_at", "")).strip()) or utc_now(),
        )


@dataclass(slots=True)
class ObservationReviewCursor:
    """Compact cursor used to avoid immediately re-reviewing the same signals."""

    campaign_id: str
    last_review_id: str = ""
    last_reviewed_at: datetime | None = None
    last_reviewed_signal_ids: list[str] = field(default_factory=list)
    last_reviewed_signal_dedupe_keys: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "last_review_id": self.last_review_id,
            "last_reviewed_at": self.last_reviewed_at.isoformat() if self.last_reviewed_at else "",
            "last_reviewed_signal_ids": list(self.last_reviewed_signal_ids),
            "last_reviewed_signal_dedupe_keys": list(self.last_reviewed_signal_dedupe_keys),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "ObservationReviewCursor":
        payload = payload or {}
        raw_signal_ids = payload.get("last_reviewed_signal_ids", [])
        raw_dedupe_keys = payload.get("last_reviewed_signal_dedupe_keys", [])
        return cls(
            campaign_id=str(payload.get("campaign_id", "")).strip(),
            last_review_id=str(payload.get("last_review_id", "")).strip(),
            last_reviewed_at=parse_datetime(str(payload.get("last_reviewed_at", "")).strip()),
            last_reviewed_signal_ids=[
                str(value).strip()
                for value in raw_signal_ids
                if isinstance(raw_signal_ids, list) and str(value).strip()
            ],
            last_reviewed_signal_dedupe_keys=[
                str(value).strip()
                for value in raw_dedupe_keys
                if isinstance(raw_dedupe_keys, list) and str(value).strip()
            ],
        )


@dataclass(slots=True)
class CampaignSignalCandidate:
    """Normalized signal candidate before dedupe and persistence."""

    campaign_id: str
    source_kind: str
    source_ref: str
    signal_type: str
    category: CampaignSignalCategory = CampaignSignalCategory.RISK
    severity: CampaignSignalSeverity = CampaignSignalSeverity.MEDIUM
    summary: str = ""
    context_refs: list[str] = field(default_factory=list)
    account_id: str = ""
    community_id: str = ""
    conversation_id: str = ""
    happened_at: datetime = field(default_factory=utc_now)
    review_eligible: bool = False
    dedupe_key_hint: str = ""


@dataclass(slots=True)
class CampaignSignalRecord:
    """Compact durable campaign signal stored under the campaign workspace."""

    signal_id: str
    campaign_id: str
    source_kind: str
    source_ref: str
    signal_type: str
    category: CampaignSignalCategory = CampaignSignalCategory.RISK
    severity: CampaignSignalSeverity = CampaignSignalSeverity.MEDIUM
    state: CampaignSignalState = CampaignSignalState.UNRESOLVED
    dedupe_key: str = ""
    summary: str = ""
    context_refs: list[str] = field(default_factory=list)
    account_id: str = ""
    community_id: str = ""
    conversation_id: str = ""
    first_happened_at: datetime = field(default_factory=utc_now)
    last_happened_at: datetime = field(default_factory=utc_now)
    occurrence_count: int = 1
    review_eligible: bool = False
    last_reviewed_at: datetime | None = None
    last_review_result_ref: str = ""
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def touch(self) -> None:
        """Refresh the update timestamp after a mutation."""
        self.updated_at = utc_now()

    def to_dict(self) -> dict[str, Any]:
        """Serialize the signal for JSON-backed persistence."""
        return {
            "signal_id": self.signal_id,
            "campaign_id": self.campaign_id,
            "source_kind": self.source_kind,
            "source_ref": self.source_ref,
            "signal_type": self.signal_type,
            "category": self.category.value,
            "severity": self.severity.value,
            "state": self.state.value,
            "dedupe_key": self.dedupe_key,
            "summary": self.summary,
            "context_refs": list(self.context_refs),
            "account_id": self.account_id,
            "community_id": self.community_id,
            "conversation_id": self.conversation_id,
            "first_happened_at": self.first_happened_at.isoformat(),
            "last_happened_at": self.last_happened_at.isoformat(),
            "occurrence_count": self.occurrence_count,
            "review_eligible": self.review_eligible,
            "last_reviewed_at": self.last_reviewed_at.isoformat() if self.last_reviewed_at else "",
            "last_review_result_ref": self.last_review_result_ref,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "CampaignSignalRecord":
        """Hydrate one campaign signal from JSON."""
        payload = payload or {}
        raw_category = str(payload.get("category", CampaignSignalCategory.RISK.value))
        raw_severity = str(payload.get("severity", CampaignSignalSeverity.MEDIUM.value))
        raw_state = str(payload.get("state", CampaignSignalState.UNRESOLVED.value))
        raw_refs = payload.get("context_refs", [])
        return cls(
            signal_id=str(payload.get("signal_id", "")).strip(),
            campaign_id=str(payload.get("campaign_id", "")).strip(),
            source_kind=str(payload.get("source_kind", "")).strip(),
            source_ref=str(payload.get("source_ref", "")).strip(),
            signal_type=str(payload.get("signal_type", "")).strip(),
            category=CampaignSignalCategory._value2member_map_.get(raw_category, CampaignSignalCategory.RISK),
            severity=CampaignSignalSeverity._value2member_map_.get(raw_severity, CampaignSignalSeverity.MEDIUM),
            state=CampaignSignalState._value2member_map_.get(raw_state, CampaignSignalState.UNRESOLVED),
            dedupe_key=str(payload.get("dedupe_key", "")).strip(),
            summary=str(payload.get("summary", "")).strip(),
            context_refs=[str(value).strip() for value in raw_refs if isinstance(raw_refs, list) and str(value).strip()],
            account_id=str(payload.get("account_id", "")).strip(),
            community_id=str(payload.get("community_id", "")).strip(),
            conversation_id=str(payload.get("conversation_id", "")).strip(),
            first_happened_at=parse_datetime(str(payload.get("first_happened_at", "")).strip()) or utc_now(),
            last_happened_at=parse_datetime(str(payload.get("last_happened_at", "")).strip()) or utc_now(),
            occurrence_count=max(int(payload.get("occurrence_count", 1) or 1), 1),
            review_eligible=bool(payload.get("review_eligible", False)),
            last_reviewed_at=parse_datetime(str(payload.get("last_reviewed_at", "")).strip()),
            last_review_result_ref=str(payload.get("last_review_result_ref", "")).strip(),
            created_at=parse_datetime(str(payload.get("created_at", "")).strip()) or utc_now(),
            updated_at=parse_datetime(str(payload.get("updated_at", "")).strip()) or utc_now(),
        )


_OPPORTUNITY_SIGNAL_TYPES = frozenset(
    {
        "clarified_need",
        "conversation_high_intent_shift",
        "conversation_promoted_for_deep_review",
        "conversion_ready_thread",
        "cta_accepted",
        "objection_resolved",
        "pricing_interest",
        "public_to_dm_transition",
    }
)
_YIELD_SIGNAL_TYPES = frozenset({"handoff_delivered"})


def infer_signal_category(signal_type: str) -> CampaignSignalCategory:
    """Return the default category for one signal type."""
    normalized = signal_type.strip().lower()
    if normalized in _YIELD_SIGNAL_TYPES:
        return CampaignSignalCategory.YIELD
    if normalized in _OPPORTUNITY_SIGNAL_TYPES:
        return CampaignSignalCategory.OPPORTUNITY
    return CampaignSignalCategory.RISK
