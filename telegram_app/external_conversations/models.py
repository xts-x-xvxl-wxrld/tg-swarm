"""Runtime records for campaign-linked external conversation state."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from telegram_app.engagement_triage.models import ConversationTriageState


def utc_now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(UTC)


def parse_datetime(value: str | None) -> datetime | None:
    """Parse an ISO 8601 datetime, returning None when the value is empty."""
    if not value:
        return None
    return datetime.fromisoformat(value)


class ThreadOrigin(StrEnum):
    """How the current external conversation thread began."""

    DIRECT_INBOUND_DM = "direct_inbound_dm"
    GROUP_REPLY = "group_reply"


class ExternalConversationStatus(StrEnum):
    """Operational lifecycle states for one external conversation."""

    ACTIVE = "active"
    COOLING_DOWN = "cooling_down"
    PAUSED = "paused"
    BLOCKED = "blocked"
    ESCALATED = "escalated"
    CLOSED = "closed"


class ConsentPosture(StrEnum):
    """Contact posture that constrains how the runtime may continue the thread."""

    INBOUND_ONLY = "inbound_only"
    GROUP_CONTEXT_ONLY = "group_context_only"
    DO_NOT_CONTACT = "do_not_contact"
    OPERATOR_OVERRIDE = "operator_override"


class FollowUpWindowType(StrEnum):
    """Supported follow-up scheduling windows for one conversation."""

    GROUP_FOLLOW_UP = "group_follow_up"
    DM_FOLLOW_UP = "dm_follow_up"


class ConversationReviewTriggerType(StrEnum):
    """Supported automatic review trigger types for one conversation moment."""

    INBOUND = "inbound"
    FOLLOW_UP_DUE = "follow_up_due"


@dataclass(slots=True)
class ConversationReviewTrigger:
    """One durable review trigger claimed by a background worker."""

    campaign_id: str
    conversation_id: str
    trigger_type: ConversationReviewTriggerType
    trigger_source: str
    trigger_key: str
    eligible_at: datetime
    summary: str = ""


@dataclass(slots=True)
class ConversationBeliefState:
    """Deeper accumulated commercial meaning for one conversation."""

    intent_posture: str = ""
    known_objections: list[str] = field(default_factory=list)
    known_fit_signals: list[str] = field(default_factory=list)
    unanswered_questions: list[str] = field(default_factory=list)
    commercial_stage: str = ""
    last_meaningful_shift: str = ""
    suggested_next_move: str = ""
    last_belief_update_at: datetime | None = None

    def __post_init__(self) -> None:
        self.known_objections = _string_list(self.known_objections)
        self.known_fit_signals = _string_list(self.known_fit_signals)
        self.unanswered_questions = _string_list(self.unanswered_questions)
        self.intent_posture = self.intent_posture.strip()
        self.commercial_stage = self.commercial_stage.strip()
        self.last_meaningful_shift = self.last_meaningful_shift.strip()
        self.suggested_next_move = self.suggested_next_move.strip()

    def to_dict(self) -> dict[str, Any]:
        """Serialize the belief state for JSON persistence."""
        return {
            "intent_posture": self.intent_posture,
            "known_objections": list(self.known_objections),
            "known_fit_signals": list(self.known_fit_signals),
            "unanswered_questions": list(self.unanswered_questions),
            "commercial_stage": self.commercial_stage,
            "last_meaningful_shift": self.last_meaningful_shift,
            "suggested_next_move": self.suggested_next_move,
            "last_belief_update_at": self.last_belief_update_at.isoformat() if self.last_belief_update_at else "",
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "ConversationBeliefState":
        """Hydrate durable belief state from JSON."""
        payload = payload or {}
        return cls(
            intent_posture=str(payload.get("intent_posture", "")).strip(),
            known_objections=_string_list(payload.get("known_objections")),
            known_fit_signals=_string_list(payload.get("known_fit_signals")),
            unanswered_questions=_string_list(payload.get("unanswered_questions")),
            commercial_stage=str(payload.get("commercial_stage", "")).strip(),
            last_meaningful_shift=str(payload.get("last_meaningful_shift", "")).strip(),
            suggested_next_move=str(payload.get("suggested_next_move", "")).strip(),
            last_belief_update_at=parse_datetime(str(payload.get("last_belief_update_at", "")).strip()),
        )


@dataclass(slots=True)
class ExternalConversationRecord:
    """Compact durable thread state for one campaign-linked external conversation."""

    conversation_id: str
    campaign_id: str
    account_id: str
    peer_id: str
    chat_id: str = ""
    community_id: str = ""
    thread_origin: ThreadOrigin = ThreadOrigin.DIRECT_INBOUND_DM
    external_user_id: str = ""
    status: ExternalConversationStatus = ExternalConversationStatus.ACTIVE
    consent_posture: ConsentPosture = ConsentPosture.INBOUND_ONLY
    last_inbound_at: datetime | None = None
    last_outbound_at: datetime | None = None
    last_inbound_message_id: str = ""
    last_outbound_message_id: str = ""
    last_event_id: str = ""
    reply_target_message_id: str = ""
    next_action_type: str = ""
    next_action_reason: str = ""
    operator_hold_reason: str = ""
    status_reason: str = ""
    summary: str = ""
    recent_message_refs: list[str] = field(default_factory=list)
    external_user_messaged_first: bool = False
    follow_up_due_at: datetime | None = None
    follow_up_window_type: FollowUpWindowType | None = None
    follow_up_attempt_count: int = 0
    timing_profile: str = ""
    quiet_hours_profile: str = ""
    review_claimed_by: str = ""
    review_claimed_at: datetime | None = None
    review_claim_expires_at: datetime | None = None
    review_claim_trigger_key: str = ""
    last_completed_review_trigger_key: str = ""
    last_completed_review_at: datetime | None = None
    last_completed_review_source: str = ""
    last_completed_review_disposition: str = ""
    last_completed_review_summary: str = ""
    last_completed_review_action_id: str = ""
    pending_autonomous_review_id: str = ""
    qualification_status: str = ""
    qualification_summary: str = ""
    handoff_status: str = ""
    handoff_summary: str = ""
    last_handoff_action_id: str = ""
    last_handoff_attempted_at: datetime | None = None
    last_handoff_completed_at: datetime | None = None
    triage_state: ConversationTriageState = field(default_factory=ConversationTriageState)
    belief_state: ConversationBeliefState = field(default_factory=ConversationBeliefState)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the conversation record for JSON persistence."""
        return {
            "account_id": self.account_id,
            "campaign_id": self.campaign_id,
            "chat_id": self.chat_id,
            "community_id": self.community_id,
            "consent_posture": self.consent_posture.value,
            "conversation_id": self.conversation_id,
            "created_at": self.created_at.isoformat(),
            "external_user_id": self.external_user_id,
            "external_user_messaged_first": self.external_user_messaged_first,
            "follow_up_attempt_count": self.follow_up_attempt_count,
            "follow_up_due_at": self.follow_up_due_at.isoformat() if self.follow_up_due_at else "",
            "follow_up_window_type": self.follow_up_window_type.value if self.follow_up_window_type else "",
            "handoff_status": self.handoff_status,
            "handoff_summary": self.handoff_summary,
            "last_event_id": self.last_event_id,
            "last_handoff_action_id": self.last_handoff_action_id,
            "last_handoff_attempted_at": self.last_handoff_attempted_at.isoformat() if self.last_handoff_attempted_at else "",
            "last_handoff_completed_at": self.last_handoff_completed_at.isoformat() if self.last_handoff_completed_at else "",
            "last_inbound_at": self.last_inbound_at.isoformat() if self.last_inbound_at else "",
            "last_inbound_message_id": self.last_inbound_message_id,
            "last_completed_review_action_id": self.last_completed_review_action_id,
            "last_completed_review_at": self.last_completed_review_at.isoformat() if self.last_completed_review_at else "",
            "last_completed_review_disposition": self.last_completed_review_disposition,
            "last_completed_review_source": self.last_completed_review_source,
            "last_completed_review_summary": self.last_completed_review_summary,
            "last_completed_review_trigger_key": self.last_completed_review_trigger_key,
            "last_outbound_at": self.last_outbound_at.isoformat() if self.last_outbound_at else "",
            "last_outbound_message_id": self.last_outbound_message_id,
            "next_action_reason": self.next_action_reason,
            "next_action_type": self.next_action_type,
            "operator_hold_reason": self.operator_hold_reason,
            "pending_autonomous_review_id": self.pending_autonomous_review_id,
            "peer_id": self.peer_id,
            "qualification_status": self.qualification_status,
            "qualification_summary": self.qualification_summary,
            "quiet_hours_profile": self.quiet_hours_profile,
            "recent_message_refs": list(self.recent_message_refs),
            "reply_target_message_id": self.reply_target_message_id,
            "review_claim_expires_at": self.review_claim_expires_at.isoformat() if self.review_claim_expires_at else "",
            "review_claim_trigger_key": self.review_claim_trigger_key,
            "review_claimed_at": self.review_claimed_at.isoformat() if self.review_claimed_at else "",
            "review_claimed_by": self.review_claimed_by,
            "status": self.status.value,
            "status_reason": self.status_reason,
            "summary": self.summary,
            "timing_profile": self.timing_profile,
            "thread_origin": self.thread_origin.value,
            "triage_state": self.triage_state.to_dict(),
            "belief_state": self.belief_state.to_dict(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "ExternalConversationRecord":
        """Hydrate one conversation record from JSON."""
        payload = payload or {}
        raw_origin = str(payload.get("thread_origin", ThreadOrigin.DIRECT_INBOUND_DM.value))
        raw_status = str(payload.get("status", ExternalConversationStatus.ACTIVE.value))
        raw_consent = str(payload.get("consent_posture", ConsentPosture.INBOUND_ONLY.value))
        raw_follow_up_window_type = str(payload.get("follow_up_window_type", "")).strip()
        raw_refs = payload.get("recent_message_refs", [])
        return cls(
            conversation_id=str(payload.get("conversation_id", "")).strip(),
            campaign_id=str(payload.get("campaign_id", "")).strip(),
            account_id=str(payload.get("account_id", "")).strip(),
            peer_id=str(payload.get("peer_id", "")).strip(),
            chat_id=str(payload.get("chat_id", "")).strip(),
            community_id=str(payload.get("community_id", "")).strip(),
            thread_origin=ThreadOrigin._value2member_map_.get(raw_origin, ThreadOrigin.DIRECT_INBOUND_DM),
            external_user_id=str(payload.get("external_user_id", "")).strip(),
            status=ExternalConversationStatus._value2member_map_.get(raw_status, ExternalConversationStatus.ACTIVE),
            consent_posture=ConsentPosture._value2member_map_.get(raw_consent, ConsentPosture.INBOUND_ONLY),
            last_inbound_at=parse_datetime(str(payload.get("last_inbound_at", "")).strip()),
            last_outbound_at=parse_datetime(str(payload.get("last_outbound_at", "")).strip()),
            last_inbound_message_id=str(payload.get("last_inbound_message_id", "")).strip(),
            last_outbound_message_id=str(payload.get("last_outbound_message_id", "")).strip(),
            last_event_id=str(payload.get("last_event_id", "")).strip(),
            qualification_status=str(payload.get("qualification_status", "")).strip(),
            qualification_summary=str(payload.get("qualification_summary", "")).strip(),
            handoff_status=str(payload.get("handoff_status", "")).strip(),
            handoff_summary=str(payload.get("handoff_summary", "")).strip(),
            last_handoff_action_id=str(payload.get("last_handoff_action_id", "")).strip(),
            last_handoff_attempted_at=parse_datetime(str(payload.get("last_handoff_attempted_at", "")).strip()),
            last_handoff_completed_at=parse_datetime(str(payload.get("last_handoff_completed_at", "")).strip()),
            triage_state=ConversationTriageState.from_dict(payload.get("triage_state")),
            belief_state=ConversationBeliefState.from_dict(payload.get("belief_state")),
            reply_target_message_id=str(payload.get("reply_target_message_id", "")).strip(),
            next_action_type=str(payload.get("next_action_type", "")).strip(),
            next_action_reason=str(payload.get("next_action_reason", "")).strip(),
            operator_hold_reason=str(payload.get("operator_hold_reason", "")).strip(),
            pending_autonomous_review_id=str(payload.get("pending_autonomous_review_id", "")).strip(),
            status_reason=str(payload.get("status_reason", "")).strip(),
            summary=str(payload.get("summary", "")),
            recent_message_refs=[
                str(value).strip()
                for value in raw_refs
                if isinstance(raw_refs, list) and str(value).strip()
            ],
            external_user_messaged_first=bool(payload.get("external_user_messaged_first", False)),
            follow_up_due_at=parse_datetime(str(payload.get("follow_up_due_at", "")).strip()),
            follow_up_window_type=FollowUpWindowType._value2member_map_.get(raw_follow_up_window_type),
            follow_up_attempt_count=max(int(payload.get("follow_up_attempt_count", 0) or 0), 0),
            timing_profile=str(payload.get("timing_profile", "")).strip(),
            quiet_hours_profile=str(payload.get("quiet_hours_profile", "")).strip(),
            review_claimed_by=str(payload.get("review_claimed_by", "")).strip(),
            review_claimed_at=parse_datetime(str(payload.get("review_claimed_at", "")).strip()),
            review_claim_expires_at=parse_datetime(str(payload.get("review_claim_expires_at", "")).strip()),
            review_claim_trigger_key=str(payload.get("review_claim_trigger_key", "")).strip(),
            last_completed_review_trigger_key=str(payload.get("last_completed_review_trigger_key", "")).strip(),
            last_completed_review_at=parse_datetime(str(payload.get("last_completed_review_at", "")).strip()),
            last_completed_review_source=str(payload.get("last_completed_review_source", "")).strip(),
            last_completed_review_disposition=str(payload.get("last_completed_review_disposition", "")).strip(),
            last_completed_review_summary=str(payload.get("last_completed_review_summary", "")).strip(),
            last_completed_review_action_id=str(payload.get("last_completed_review_action_id", "")).strip(),
            created_at=parse_datetime(str(payload.get("created_at", "")).strip()) or utc_now(),
            updated_at=parse_datetime(str(payload.get("updated_at", "")).strip()) or utc_now(),
        )


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
