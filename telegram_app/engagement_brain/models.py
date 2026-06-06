"""Structured decision contracts for the live-engagement brain."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from hashlib import sha256

from telegram_app.external_conversations import ConversationBeliefState, ExternalConversationRecord, ThreadOrigin


class EngagementBrainDecision(StrEnum):
    """The small set of next-move decisions the brain may return."""

    REPLY = "reply"
    ASK_CLARIFYING_QUESTION = "ask_clarifying_question"
    WAIT = "wait"
    IGNORE = "ignore"
    ESCALATE = "escalate"


class EngagementBrainActionType(StrEnum):
    """Normalized live-execution action types proposed by the brain."""

    NONE = "none"
    SEND_GROUP_REPLY = "send_group_reply"
    SEND_DM_REPLY = "send_dm_reply"


class EngagementBrainMode(StrEnum):
    """Reasoning mode derived from the live conversation posture."""

    GROUP = "group"
    DIRECT_DM = "direct_dm"


class EngagementBrainQualificationState(StrEnum):
    """Lightweight commercial signal states for one conversation moment."""

    CURIOUS = "curious"
    POTENTIAL_FIT = "potential_fit"
    OBJECTION_OR_UNCLEAR = "objection_or_unclear"
    CONVERSION_READY = "conversion_ready"


class EngagementBrainRiskLevel(StrEnum):
    """Coarse risk labels for proposal review and routing."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class EngagementBrainCommunityRiskLevel(StrEnum):
    """Community-level live-reply posture used by the engagement brain."""

    LOW = "low"
    GUARDED = "guarded"
    HIGH = "high"
    RESTRICTED = "restricted"


class EngagementBrainConversationRiskLevel(StrEnum):
    """Conversation-level reply risk used for routing and authorization."""

    LOW = "low"
    NEEDS_CLARIFICATION = "needs_clarification"
    SENSITIVE = "sensitive"
    HIGH_STAKES = "high_stakes"


class EngagementBrainResolutionStrategy(StrEnum):
    """How the brain wants to handle uncertainty or ambiguity."""

    NONE = "none"
    ANSWER_SAFE_PORTION = "answer_safe_portion"
    ASK_NARROWING_QUESTION = "ask_narrowing_question"
    REDIRECT_TO_NEXT_STEP = "redirect_to_next_step"
    OPERATOR_ESCALATION = "operator_escalation"


class EngagementBrainRunDisposition(StrEnum):
    """What happened after the runtime evaluated one brain proposal."""

    ENQUEUED = "enqueued"
    NO_ACTION = "no_action"
    BLOCKED_BY_AUTHORIZATION = "blocked_by_authorization"
    BLOCKED_BY_POLICY = "blocked_by_policy"


class EngagementBrainMessageDirection(StrEnum):
    """Whether a recent message came from the external side or from us."""

    INBOUND = "inbound"
    OUTBOUND = "outbound"


@dataclass(slots=True)
class EngagementBrainMessage:
    """Compact recent-message context for one live conversation moment."""

    direction: EngagementBrainMessageDirection
    text: str = ""
    message_id: str = ""
    sent_at: datetime | None = None
    asset_refs: list[str] = field(default_factory=list)


@dataclass(slots=True)
class EngagementBrainVoiceProfile:
    """Campaign-owned tone contract for human-feeling live replies."""

    brand_name: str = ""
    tone_descriptors: list[str] = field(default_factory=list)
    style_do: list[str] = field(default_factory=list)
    style_avoid: list[str] = field(default_factory=list)
    cta_style: str = ""
    emoji_policy: str = ""
    evidence_style: str = ""

    def normalized_dict(self) -> dict[str, object]:
        """Return a JSON-safe normalized representation."""
        return {
            "brand_name": self.brand_name.strip(),
            "tone_descriptors": [value.strip() for value in self.tone_descriptors if value.strip()],
            "style_do": [value.strip() for value in self.style_do if value.strip()],
            "style_avoid": [value.strip() for value in self.style_avoid if value.strip()],
            "cta_style": self.cta_style.strip(),
            "emoji_policy": self.emoji_policy.strip(),
            "evidence_style": self.evidence_style.strip(),
        }


@dataclass(slots=True)
class EngagementBrainApprovedClaim:
    """One approved claim the brain may use while drafting replies."""

    claim_id: str
    text: str
    evidence_basis: str = ""
    usage_notes: str = ""

    def normalized_dict(self) -> dict[str, str]:
        """Return a JSON-safe normalized representation."""
        return {
            "claim_id": self.claim_id.strip(),
            "text": self.text.strip(),
            "evidence_basis": self.evidence_basis.strip(),
            "usage_notes": self.usage_notes.strip(),
        }


@dataclass(slots=True)
class EngagementBrainForbiddenClaim:
    """One forbidden claim category or phrase family for live replies."""

    label: str
    instruction: str

    def normalized_dict(self) -> dict[str, str]:
        """Return a JSON-safe normalized representation."""
        return {
            "label": self.label.strip(),
            "instruction": self.instruction.strip(),
        }


@dataclass(slots=True)
class EngagementBrainCommunityGuidance:
    """Community-specific tone and safety guidance."""

    community_id: str = ""
    chat_id: str = ""
    community_name: str = ""
    community_type: str = ""
    tone_guidance: str = ""
    response_posture: str = ""
    allowed_cta: str = ""
    direct_response_rule: str = ""
    clarifying_question_rule: str = ""
    escalation_rule: str = ""
    risk_notes: str = ""
    reply_latency_tier: str = ""
    negative_signal_tolerance: str = ""
    risky_topics: list[str] = field(default_factory=list)
    approved_claim_ids: list[str] = field(default_factory=list)
    forbidden_claim_labels: list[str] = field(default_factory=list)
    community_risk_level: EngagementBrainCommunityRiskLevel = EngagementBrainCommunityRiskLevel.LOW

    def normalized_dict(self) -> dict[str, object]:
        """Return a JSON-safe normalized representation."""
        return {
            "community_id": self.community_id.strip(),
            "chat_id": self.chat_id.strip(),
            "community_name": self.community_name.strip(),
            "community_type": self.community_type.strip(),
            "tone_guidance": self.tone_guidance.strip(),
            "response_posture": self.response_posture.strip(),
            "allowed_cta": self.allowed_cta.strip(),
            "direct_response_rule": self.direct_response_rule.strip(),
            "clarifying_question_rule": self.clarifying_question_rule.strip(),
            "escalation_rule": self.escalation_rule.strip(),
            "risk_notes": self.risk_notes.strip(),
            "reply_latency_tier": self.reply_latency_tier.strip(),
            "negative_signal_tolerance": self.negative_signal_tolerance.strip(),
            "risky_topics": [value.strip() for value in self.risky_topics if value.strip()],
            "approved_claim_ids": [value.strip() for value in self.approved_claim_ids if value.strip()],
            "forbidden_claim_labels": [value.strip() for value in self.forbidden_claim_labels if value.strip()],
            "community_risk_level": self.community_risk_level.value,
        }


@dataclass(slots=True)
class EngagementBrainContext:
    """Bounded input context for one brain proposal."""

    conversation: ExternalConversationRecord
    campaign_brief: str = ""
    conversion_target_summary: str = ""
    conversion_target_kind: str = ""
    conversion_target_value: str = ""
    qualification_posture: str = ""
    approved_offer_facts: list[str] = field(default_factory=list)
    strategy_notes: list[str] = field(default_factory=list)
    community_notes: list[str] = field(default_factory=list)
    voice_profile: EngagementBrainVoiceProfile = field(default_factory=EngagementBrainVoiceProfile)
    approved_claims: list[EngagementBrainApprovedClaim] = field(default_factory=list)
    forbidden_claims: list[EngagementBrainForbiddenClaim] = field(default_factory=list)
    community_guidance: EngagementBrainCommunityGuidance | None = None
    community_risk_level: EngagementBrainCommunityRiskLevel = EngagementBrainCommunityRiskLevel.LOW
    conversation_posture: str = ""
    tone_contract_fingerprint: str = ""
    conversation_summary: str = ""
    recent_messages: list[EngagementBrainMessage] = field(default_factory=list)

    @property
    def mode(self) -> EngagementBrainMode:
        """Derive the reasoning mode from the conversation origin."""
        if self.conversation.thread_origin is ThreadOrigin.GROUP_REPLY:
            return EngagementBrainMode.GROUP
        return EngagementBrainMode.DIRECT_DM

    def latest_inbound_message(self) -> EngagementBrainMessage | None:
        """Return the most recent inbound message when one exists."""
        for message in reversed(self.recent_messages):
            if message.direction is EngagementBrainMessageDirection.INBOUND:
                return message
        return None

    def latest_inbound_text(self) -> str:
        """Return the latest inbound text or an empty string."""
        latest = self.latest_inbound_message()
        return latest.text.strip() if latest is not None else ""

    def allowed_claims(self) -> list[EngagementBrainApprovedClaim]:
        """Return the claims available in the current community context."""
        if self.community_guidance is None or not self.community_guidance.approved_claim_ids:
            return list(self.approved_claims)
        allowed_ids = set(self.community_guidance.approved_claim_ids)
        return [claim for claim in self.approved_claims if claim.claim_id in allowed_ids]

    def effective_forbidden_claims(self) -> list[EngagementBrainForbiddenClaim]:
        """Return the forbidden claim rules active in the current community."""
        if self.community_guidance is None or not self.community_guidance.forbidden_claim_labels:
            return list(self.forbidden_claims)
        labels = set(self.community_guidance.forbidden_claim_labels)
        return [claim for claim in self.forbidden_claims if claim.label in labels]

    @staticmethod
    def build_tone_contract_fingerprint(
        voice_profile: EngagementBrainVoiceProfile,
        approved_claims: list[EngagementBrainApprovedClaim],
        forbidden_claims: list[EngagementBrainForbiddenClaim],
        community_guidance: EngagementBrainCommunityGuidance | None,
    ) -> str:
        """Build a stable fingerprint for the active tone and claim contract."""
        material = repr(
            {
                "voice_profile": voice_profile.normalized_dict(),
                "approved_claims": [claim.normalized_dict() for claim in approved_claims],
                "forbidden_claims": [claim.normalized_dict() for claim in forbidden_claims],
                "community_guidance": community_guidance.normalized_dict() if community_guidance is not None else {},
            }
        )
        return sha256(material.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class EngagementBrainProposal:
    """One structured next-move proposal produced by the live-engagement brain."""

    decision: EngagementBrainDecision
    action_type: EngagementBrainActionType = EngagementBrainActionType.NONE
    draft_text: str = ""
    presentation_hints: list[str] = field(default_factory=list)
    goal: str = ""
    qualification_state: EngagementBrainQualificationState = EngagementBrainQualificationState.CURIOUS
    facts_used: list[str] = field(default_factory=list)
    missing_facts: list[str] = field(default_factory=list)
    approved_claim_ids_used: list[str] = field(default_factory=list)
    risk_level: EngagementBrainRiskLevel = EngagementBrainRiskLevel.LOW
    community_risk_level: EngagementBrainCommunityRiskLevel = EngagementBrainCommunityRiskLevel.LOW
    conversation_risk_level: EngagementBrainConversationRiskLevel = EngagementBrainConversationRiskLevel.LOW
    resolution_strategy: EngagementBrainResolutionStrategy = EngagementBrainResolutionStrategy.NONE
    escalation_reason: str = ""
    tone_contract_fingerprint: str = ""

    def __post_init__(self) -> None:
        self.draft_text = self.draft_text.strip()
        self.goal = self.goal.strip()
        self.escalation_reason = self.escalation_reason.strip()
        self.presentation_hints = [value.strip() for value in self.presentation_hints if value.strip()]
        self.facts_used = [value.strip() for value in self.facts_used if value.strip()]
        self.missing_facts = [value.strip() for value in self.missing_facts if value.strip()]
        self.approved_claim_ids_used = [value.strip() for value in self.approved_claim_ids_used if value.strip()]
        self.tone_contract_fingerprint = self.tone_contract_fingerprint.strip()

        if self.action_type is not EngagementBrainActionType.NONE and not self.draft_text:
            raise ValueError("Send proposals require non-empty draft text.")

        if self.decision in {
            EngagementBrainDecision.WAIT,
            EngagementBrainDecision.IGNORE,
            EngagementBrainDecision.ESCALATE,
        } and self.action_type is not EngagementBrainActionType.NONE:
            raise ValueError(f"{self.decision.value} proposals cannot include a send action.")

        if self.decision is EngagementBrainDecision.ESCALATE and not self.escalation_reason:
            raise ValueError("Escalation proposals require an escalation reason.")


@dataclass(slots=True)
class EngagementBrainReview:
    """Structured commercial reasoning result before any bounded draft is written."""

    decision: EngagementBrainDecision
    qualification_state: EngagementBrainQualificationState = EngagementBrainQualificationState.CURIOUS
    goal: str = ""
    missing_facts: list[str] = field(default_factory=list)
    facts_used: list[str] = field(default_factory=list)
    risk_level: EngagementBrainRiskLevel = EngagementBrainRiskLevel.LOW
    community_risk_level: EngagementBrainCommunityRiskLevel = EngagementBrainCommunityRiskLevel.LOW
    conversation_risk_level: EngagementBrainConversationRiskLevel = EngagementBrainConversationRiskLevel.LOW
    resolution_strategy: EngagementBrainResolutionStrategy = EngagementBrainResolutionStrategy.NONE
    escalation_reason: str = ""
    belief_state: ConversationBeliefState = field(default_factory=ConversationBeliefState)
    learning_note: str = ""
    compiled_proposal_payloads: list[dict[str, object]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.goal = self.goal.strip()
        self.missing_facts = [value.strip() for value in self.missing_facts if value.strip()]
        self.facts_used = [value.strip() for value in self.facts_used if value.strip()]
        self.escalation_reason = self.escalation_reason.strip()
        self.learning_note = self.learning_note.strip()
        self.compiled_proposal_payloads = [
            dict(value)
            for value in self.compiled_proposal_payloads
            if isinstance(value, dict)
        ]

        if self.decision is EngagementBrainDecision.ESCALATE and not self.escalation_reason:
            raise ValueError("Escalation reviews require an escalation reason.")


@dataclass(slots=True)
class EngagementBrainRunResult:
    """Outcome of one end-to-end brain evaluation against runtime state."""

    conversation_id: str
    proposal: EngagementBrainProposal
    disposition: EngagementBrainRunDisposition
    action_id: str = ""
    authorization_reason_codes: list[str] = field(default_factory=list)
    policy_reason_codes: list[str] = field(default_factory=list)
    review_record_id: str = ""
    summary: str = ""
