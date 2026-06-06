"""Promoted-thread commercial reasoning plus bounded live-reply drafting."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
import json
import logging
import os
from pathlib import Path
import re
from typing import Protocol

try:
    import anthropic
except ImportError:  # pragma: no cover - exercised only in stripped-down environments.
    anthropic = None

from telegram_app.engagement_brain.models import (
    EngagementBrainActionType,
    EngagementBrainApprovedClaim,
    EngagementBrainCommunityGuidance,
    EngagementBrainCommunityRiskLevel,
    EngagementBrainContext,
    EngagementBrainConversationRiskLevel,
    EngagementBrainDecision,
    EngagementBrainMode,
    EngagementBrainProposal,
    EngagementBrainQualificationState,
    EngagementBrainResolutionStrategy,
    EngagementBrainReview,
    EngagementBrainRiskLevel,
)
from telegram_app.engagement_brain.drafting_skills import (
    AnthropicDraftingSkillSelector,
    DeterministicDraftingSkillSelector,
    DraftingSkillSelection,
    DraftingSkillSelector,
)
from telegram_app.external_conversations import ConversationBeliefState
from telegram_app.llm import resolve_model
from telegram_app.workflow_validation import parse_marked_json_block, parse_output_proposal_list

logger = logging.getLogger(__name__)

ENGAGEMENT_BRAIN_REVIEW_JSON_MARKER = "ENGAGEMENT_BRAIN_REVIEW_JSON"
ENGAGEMENT_BRAIN_DRAFT_JSON_MARKER = "ENGAGEMENT_BRAIN_JSON"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_GROUP_MAX_CHARS = 240
DEFAULT_DM_MAX_CHARS = 320

_LOW_SIGNAL_MESSAGES = frozenset(
    {
        "k",
        "kk",
        "ok",
        "okay",
        "nice",
        "cool",
        "thanks",
        "thank you",
        "thx",
        "yes",
        "yep",
        "sure",
    }
)
_CONVERSION_READY_KEYWORDS = (
    "buy",
    "price",
    "pricing",
    "cost",
    "how much",
    "interested",
    "ready",
    "sign up",
    "start",
    "details",
    "demo",
    "call",
    "link",
)
_OBJECTION_KEYWORDS = (
    "expensive",
    "too much",
    "scam",
    "legit",
    "trust",
    "skeptical",
    "unsure",
    "not sure",
    "confused",
    "unclear",
    "why should",
)
_POTENTIAL_FIT_KEYWORDS = (
    "need",
    "looking for",
    "want to",
    "trying to",
    "can you help",
    "does this",
    "does this work",
    "work for",
    "how does",
)
_HIGH_STAKES_KEYWORDS = (
    "guarantee",
    "refund",
    "legal",
    "contract",
    "compliance",
    "invoice",
    "terms",
    "policy",
)
_PRICING_KEYWORDS = ("price", "pricing", "cost", "how much", "budget")
_DEFAULT_FORBIDDEN_PATTERNS = (
    re.compile(r"\bguarantee(?:d)?\b", re.IGNORECASE),
    re.compile(r"\brefund(?:s)?\b", re.IGNORECASE),
    re.compile(r"\bcompliance\b", re.IGNORECASE),
    re.compile(r"\blegal\b", re.IGNORECASE),
    re.compile(r"\b100%\b", re.IGNORECASE),
)


def _load_prompt(name: str) -> str:
    return (REPO_ROOT / "prompts" / name).read_text(encoding="utf-8")


@dataclass(slots=True)
class DraftGenerationRequest:
    """Input contract for bounded draft generation."""

    context: EngagementBrainContext
    decision: EngagementBrainDecision
    qualification_state: EngagementBrainQualificationState
    goal: str
    missing_facts: list[str] = field(default_factory=list)
    risk_level: EngagementBrainRiskLevel = EngagementBrainRiskLevel.LOW
    conversation_risk_level: EngagementBrainConversationRiskLevel = EngagementBrainConversationRiskLevel.LOW
    drafting_skill_selection: DraftingSkillSelection | None = None


@dataclass(slots=True)
class DraftGenerationResult:
    """Bounded draft output used to populate a proposal."""

    text: str
    facts_used: list[str] = field(default_factory=list)
    approved_claim_ids_used: list[str] = field(default_factory=list)
    presentation_hints: list[str] = field(default_factory=list)


class CommercialReasoningReviewer(Protocol):
    """Protocol for the deeper promoted-thread commercial reasoner."""

    def review(self, context: EngagementBrainContext) -> EngagementBrainReview | None:
        """Return structured promoted-thread commercial reasoning or None on failure."""


class DraftTextGenerator(Protocol):
    """Protocol for engagement-brain draft writers."""

    def generate(self, request: DraftGenerationRequest) -> DraftGenerationResult | None:
        """Return a bounded reply draft or None when generation fails."""


class AnthropicCommercialReasoningReviewer:
    """Use a higher-capability model for promoted-thread commercial reasoning."""

    def __init__(self) -> None:
        self._client = anthropic.Anthropic() if anthropic is not None else None

    def review(self, context: EngagementBrainContext) -> EngagementBrainReview | None:
        if self._client is None or not os.getenv("ANTHROPIC_API_KEY", "").strip():
            return None

        payload = {
            "conversation_mode": context.mode.value,
            "conversation_posture": context.conversation_posture,
            "campaign_brief": context.campaign_brief,
            "qualification_posture": context.qualification_posture,
            "conversation_summary": context.conversation_summary,
            "triage_state": context.conversation.triage_state.to_dict(),
            "belief_state": context.conversation.belief_state.to_dict(),
            "latest_inbound_text": context.latest_inbound_text(),
            "recent_messages": [
                {
                    "direction": message.direction.value,
                    "text": message.text,
                    "sent_at": message.sent_at.isoformat() if message.sent_at is not None else "",
                    "asset_refs": list(message.asset_refs),
                }
                for message in context.recent_messages[-6:]
            ],
            "approved_offer_facts": list(context.approved_offer_facts),
            "strategy_notes": list(context.strategy_notes),
            "community_notes": list(context.community_notes),
            "voice_profile": context.voice_profile.normalized_dict(),
            "community_guidance": (
                context.community_guidance.normalized_dict()
                if context.community_guidance is not None
                else {}
            ),
            "community_risk_level": context.community_risk_level.value,
            "approved_claims": [claim.normalized_dict() for claim in context.allowed_claims()],
            "forbidden_claims": [claim.normalized_dict() for claim in context.effective_forbidden_claims()],
            "conversion_target_summary": context.conversion_target_summary,
            "conversion_target_kind": context.conversion_target_kind,
            "conversion_target_value": context.conversion_target_value,
            "output_contract": {
                "allowed_decisions": [decision.value for decision in EngagementBrainDecision],
                "allowed_qualification_states": [
                    state.value for state in EngagementBrainQualificationState
                ],
                "allowed_risk_levels": [level.value for level in EngagementBrainRiskLevel],
                "allowed_conversation_risk_levels": [
                    level.value for level in EngagementBrainConversationRiskLevel
                ],
                "allowed_resolution_strategies": [
                    strategy.value for strategy in EngagementBrainResolutionStrategy
                ],
            },
        }
        try:
            response = self._client.messages.create(
                model=resolve_model("commercial_reasoning"),
                max_tokens=1600,
                system=[
                    {"type": "text", "text": _load_prompt("live_engagement_review.md")},
                ],
                messages=[
                    {
                        "role": "user",
                        "content": json.dumps(payload, ensure_ascii=True),
                    }
                ],
            )
        except Exception as exc:  # pragma: no cover - network/runtime failures are environment-specific.
            logger.warning("Promoted-thread commercial reasoning fell back after Anthropic error: %s", exc)
            return None

        output_text = "".join(block.text for block in response.content if hasattr(block, "text")).strip()
        parsed = parse_marked_json_block(output_text, ENGAGEMENT_BRAIN_REVIEW_JSON_MARKER)
        if not isinstance(parsed, dict):
            return None
        return _review_from_payload(
            parsed,
            context,
            compiled_proposal_payloads=parse_output_proposal_list(output_text) or [],
        )


class AnthropicDraftTextGenerator:
    """Use a bounded Anthropic call to draft live replies from structured context."""

    def __init__(self) -> None:
        self._client = anthropic.Anthropic() if anthropic is not None else None

    def generate(self, request: DraftGenerationRequest) -> DraftGenerationResult | None:
        if self._client is None or not os.getenv("ANTHROPIC_API_KEY", "").strip():
            return None

        payload = {
            "decision": request.decision.value,
            "conversation_mode": request.context.mode.value,
            "goal": request.goal,
            "qualification_state": request.qualification_state.value,
            "community_risk_level": request.context.community_risk_level.value,
            "conversation_risk_level": request.conversation_risk_level.value,
            "campaign_brief": request.context.campaign_brief,
            "conversation_summary": request.context.conversation_summary,
            "triage_state": request.context.conversation.triage_state.to_dict(),
            "belief_state": request.context.conversation.belief_state.to_dict(),
            "latest_inbound_text": request.context.latest_inbound_text(),
            "recent_messages": [
                {
                    "direction": message.direction.value,
                    "text": message.text,
                }
                for message in request.context.recent_messages[-4:]
            ],
            "voice_profile": request.context.voice_profile.normalized_dict(),
            "community_guidance": (
                request.context.community_guidance.normalized_dict()
                if request.context.community_guidance is not None
                else {}
            ),
            "approved_claims": [claim.normalized_dict() for claim in request.context.allowed_claims()],
            "forbidden_claims": [claim.normalized_dict() for claim in request.context.effective_forbidden_claims()],
            "conversion_target_summary": request.context.conversion_target_summary,
            "conversion_target_kind": request.context.conversion_target_kind,
            "conversion_target_value": request.context.conversion_target_value,
            "missing_facts": list(request.missing_facts),
            "drafting_skill_selection": (
                request.drafting_skill_selection.normalized_dict()
                if request.drafting_skill_selection is not None
                else {}
            ),
            "draft_constraints": {
                "max_chars": DEFAULT_GROUP_MAX_CHARS
                if request.context.mode is EngagementBrainMode.GROUP
                else DEFAULT_DM_MAX_CHARS,
                "one_question_max": True,
                "no_new_claims": True,
                "no_guarantees": True,
                "group_replies_should_stay_public_safe": request.context.mode is EngagementBrainMode.GROUP,
            },
        }
        try:
            response = self._client.messages.create(
                model=resolve_model(),
                max_tokens=1200,
                system=[
                    {"type": "text", "text": _load_prompt("live_engagement.md")},
                ],
                messages=[
                    {
                        "role": "user",
                        "content": json.dumps(payload, ensure_ascii=True),
                    }
                ],
            )
        except Exception as exc:  # pragma: no cover - network/runtime failures are environment-specific.
            logger.warning("Engagement brain drafting fell back after Anthropic error: %s", exc)
            return None

        output_text = "".join(block.text for block in response.content if hasattr(block, "text")).strip()
        parsed = parse_marked_json_block(output_text, ENGAGEMENT_BRAIN_DRAFT_JSON_MARKER)
        if not isinstance(parsed, dict):
            return None

        text = str(parsed.get("draft_text", "")).strip()
        if not text:
            return None
        return DraftGenerationResult(
            text=text,
            facts_used=_string_list(parsed.get("facts_used")),
            approved_claim_ids_used=_string_list(parsed.get("approved_claim_ids_used")),
            presentation_hints=_string_list(parsed.get("presentation_hints")),
        )


class DeterministicFallbackDraftTextGenerator:
    """Conservative non-LLM fallback used in tests or no-key environments."""

    def generate(self, request: DraftGenerationRequest) -> DraftGenerationResult | None:
        claim_text, claim_ids = _select_primary_claim(request.context.allowed_claims())
        handoff_hint = _conversion_handoff_hint(request.context)
        guidance = request.context.community_guidance

        if request.decision is EngagementBrainDecision.ASK_CLARIFYING_QUESTION:
            if request.context.mode is EngagementBrainMode.GROUP:
                text = f"{claim_text or 'Could be relevant here.'} What are you mainly trying to solve?"
                hints = ["telegram_formatting_ok", "public_safe_question"]
            else:
                text = f"{claim_text or 'Happy to help.'} What are you mainly trying to get done right now?"
                hints = ["telegram_formatting_ok"]
            if guidance is not None and guidance.tone_guidance:
                text = f"{text} {guidance.tone_guidance}".strip()
            return DraftGenerationResult(
                text=text,
                facts_used=[claim_text] if claim_text else [],
                approved_claim_ids_used=claim_ids,
                presentation_hints=hints,
            )

        if request.context.mode is EngagementBrainMode.GROUP:
            opening = claim_text or "Could be relevant."
            if request.qualification_state is EngagementBrainQualificationState.CONVERSION_READY and handoff_hint:
                text = f"{opening} {handoff_hint}"
            elif request.qualification_state is EngagementBrainQualificationState.OBJECTION_OR_UNCLEAR:
                text = f"{opening} Fair question. The right setup matters more than hype."
            else:
                text = f"{opening} Usually it works best when the fit is clear."
            hints = ["telegram_formatting_ok", "public_safe_question"]
        else:
            opening = claim_text or "Happy to share more."
            if request.qualification_state is EngagementBrainQualificationState.CONVERSION_READY and handoff_hint:
                text = f"{opening} {handoff_hint}"
            elif request.qualification_state is EngagementBrainQualificationState.OBJECTION_OR_UNCLEAR:
                text = f"{opening} What part feels unclear or risky to you?"
            else:
                text = f"{opening} What are you mainly trying to solve right now?"
            hints = ["telegram_formatting_ok"]

        return DraftGenerationResult(
            text=text,
            facts_used=[claim_text] if claim_text else [],
            approved_claim_ids_used=claim_ids,
            presentation_hints=hints,
        )


class DeterministicCommercialReasoningReviewer:
    """Conservative review fallback that keeps the deeper path structured in no-key environments."""

    def review(self, context: EngagementBrainContext) -> EngagementBrainReview | None:
        latest_inbound_text = context.latest_inbound_text()
        previous_belief = context.conversation.belief_state
        if not latest_inbound_text:
            return EngagementBrainReview(
                decision=EngagementBrainDecision.WAIT,
                goal="await_clear_inbound_signal",
                community_risk_level=context.community_risk_level,
                belief_state=_refresh_belief_state(
                    previous_belief,
                    intent_posture=previous_belief.intent_posture or "waiting_for_signal",
                    commercial_stage=previous_belief.commercial_stage or "awaiting_inbound",
                    last_meaningful_shift=previous_belief.last_meaningful_shift or "No fresh inbound signal was available.",
                    suggested_next_move=previous_belief.suggested_next_move or "Wait for a clearer inbound signal before acting.",
                ),
            )

        normalized_text = _normalize_text(latest_inbound_text)
        if _is_low_signal_message(normalized_text):
            return EngagementBrainReview(
                decision=EngagementBrainDecision.IGNORE,
                goal="avoid_needy_follow_up",
                community_risk_level=context.community_risk_level,
                belief_state=_refresh_belief_state(
                    previous_belief,
                    intent_posture=previous_belief.intent_posture or "low_signal",
                    commercial_stage=previous_belief.commercial_stage or "low_signal",
                    last_meaningful_shift="Low-signal chatter did not warrant a deeper commercial move.",
                    suggested_next_move="Leave space and wait for a more meaningful inbound signal.",
                ),
            )

        qualification_state = _classify_qualification_state(normalized_text)
        missing_facts = _collect_missing_facts(normalized_text, context)
        conversation_risk_level = _classify_conversation_risk_level(
            normalized_text,
            qualification_state=qualification_state,
            missing_facts=missing_facts,
        )
        if (
            conversation_risk_level is EngagementBrainConversationRiskLevel.LOW
            and context.mode is EngagementBrainMode.GROUP
            and context.community_risk_level in {EngagementBrainCommunityRiskLevel.HIGH, EngagementBrainCommunityRiskLevel.RESTRICTED}
            and qualification_state in {
                EngagementBrainQualificationState.POTENTIAL_FIT,
                EngagementBrainQualificationState.CONVERSION_READY,
            }
        ):
            conversation_risk_level = EngagementBrainConversationRiskLevel.SENSITIVE

        if conversation_risk_level is EngagementBrainConversationRiskLevel.HIGH_STAKES:
            return self._build_review(
                context,
                previous_belief=previous_belief,
                decision=EngagementBrainDecision.ESCALATE,
                qualification_state=qualification_state,
                goal="protect_high_stakes_conversation",
                missing_facts=missing_facts,
                conversation_risk_level=conversation_risk_level,
                risk_level=EngagementBrainRiskLevel.HIGH,
                resolution_strategy=EngagementBrainResolutionStrategy.OPERATOR_ESCALATION,
                escalation_reason="high_stakes_request",
            )

        if _should_ask_clarifying_question(
            context,
            qualification_state=qualification_state,
            missing_facts=missing_facts,
        ):
            return self._build_review(
                context,
                previous_belief=previous_belief,
                decision=EngagementBrainDecision.ASK_CLARIFYING_QUESTION,
                qualification_state=qualification_state,
                goal="narrow_buying_context" if context.mode is EngagementBrainMode.DIRECT_DM else "keep_public_reply_safe",
                missing_facts=missing_facts,
                conversation_risk_level=conversation_risk_level,
                risk_level=EngagementBrainRiskLevel.MEDIUM,
                resolution_strategy=EngagementBrainResolutionStrategy.ASK_NARROWING_QUESTION,
            )

        risk_level = (
            EngagementBrainRiskLevel.MEDIUM
            if context.community_risk_level in {EngagementBrainCommunityRiskLevel.GUARDED, EngagementBrainCommunityRiskLevel.HIGH}
            or conversation_risk_level is EngagementBrainConversationRiskLevel.SENSITIVE
            else EngagementBrainRiskLevel.LOW
        )
        return self._build_review(
            context,
            previous_belief=previous_belief,
            decision=EngagementBrainDecision.REPLY,
            qualification_state=qualification_state,
            goal=_goal_for_reply(context.mode, qualification_state),
            missing_facts=missing_facts,
            conversation_risk_level=conversation_risk_level,
            risk_level=risk_level,
            resolution_strategy=EngagementBrainResolutionStrategy.ANSWER_SAFE_PORTION,
        )

    def _build_review(
        self,
        context: EngagementBrainContext,
        *,
        previous_belief: ConversationBeliefState,
        decision: EngagementBrainDecision,
        qualification_state: EngagementBrainQualificationState,
        goal: str,
        missing_facts: list[str],
        conversation_risk_level: EngagementBrainConversationRiskLevel,
        risk_level: EngagementBrainRiskLevel,
        resolution_strategy: EngagementBrainResolutionStrategy,
        escalation_reason: str = "",
    ) -> EngagementBrainReview:
        latest_inbound_text = _normalize_text(context.latest_inbound_text())
        belief_state = ConversationBeliefState(
            intent_posture=_intent_posture_for(qualification_state, decision),
            known_objections=_merge_unique(
                previous_belief.known_objections,
                _extract_objection_hints(latest_inbound_text, qualification_state),
            )[:4],
            known_fit_signals=_merge_unique(
                previous_belief.known_fit_signals,
                _extract_fit_signals(latest_inbound_text, qualification_state, context),
            )[:4],
            unanswered_questions=_merge_unique(
                previous_belief.unanswered_questions,
                _build_unanswered_questions(missing_facts, goal),
            )[:4],
            commercial_stage=_commercial_stage_for(qualification_state, decision),
            last_meaningful_shift=_last_meaningful_shift_for(qualification_state, decision, missing_facts),
            suggested_next_move=_suggested_next_move_for(goal, decision),
            last_belief_update_at=datetime.now(UTC),
        )
        facts_used = _extract_grounded_facts(context)
        return EngagementBrainReview(
            decision=decision,
            qualification_state=qualification_state,
            goal=goal,
            missing_facts=missing_facts,
            facts_used=facts_used[:4],
            risk_level=risk_level,
            community_risk_level=context.community_risk_level,
            conversation_risk_level=conversation_risk_level,
            resolution_strategy=resolution_strategy,
            escalation_reason=escalation_reason,
            belief_state=belief_state,
            learning_note=_build_learning_note(qualification_state, latest_inbound_text),
        )


class EngagementBrainService:
    """Run promoted-thread review first, then bounded drafting only when needed."""

    def __init__(
        self,
        reviewer: CommercialReasoningReviewer | None = None,
        draft_generator: DraftTextGenerator | None = None,
        drafting_skill_selector: DraftingSkillSelector | None = None,
    ) -> None:
        self._reviewer = reviewer or AnthropicCommercialReasoningReviewer()
        self._fallback_reviewer = DeterministicCommercialReasoningReviewer()
        self._draft_generator = draft_generator or DeterministicFallbackDraftTextGenerator()
        self._fallback_generator = DeterministicFallbackDraftTextGenerator()
        self._drafting_skill_selector = drafting_skill_selector or AnthropicDraftingSkillSelector()
        self._fallback_skill_selector = DeterministicDraftingSkillSelector()

    def review(self, context: EngagementBrainContext) -> EngagementBrainReview:
        """Return structured promoted-thread reasoning before any draft is written."""
        review = self._reviewer.review(context)
        if review is not None:
            return review
        fallback = self._fallback_reviewer.review(context)
        if fallback is None:
            raise ValueError("A fallback commercial reviewer is required for promoted-thread reasoning.")
        return fallback

    def proposal_from_review(
        self,
        context: EngagementBrainContext,
        review: EngagementBrainReview,
    ) -> EngagementBrainProposal:
        """Turn one structured commercial review into a send-or-hold proposal."""
        if review.decision in {
            EngagementBrainDecision.WAIT,
            EngagementBrainDecision.IGNORE,
            EngagementBrainDecision.ESCALATE,
        }:
            return EngagementBrainProposal(
                decision=review.decision,
                goal=review.goal,
                qualification_state=review.qualification_state,
                missing_facts=list(review.missing_facts),
                facts_used=list(review.facts_used),
                risk_level=review.risk_level,
                community_risk_level=review.community_risk_level,
                conversation_risk_level=review.conversation_risk_level,
                resolution_strategy=review.resolution_strategy,
                escalation_reason=review.escalation_reason,
                tone_contract_fingerprint=context.tone_contract_fingerprint,
            )

        generation_request = DraftGenerationRequest(
            context=context,
            decision=review.decision,
            qualification_state=review.qualification_state,
            goal=review.goal,
            missing_facts=list(review.missing_facts),
            risk_level=review.risk_level,
            conversation_risk_level=review.conversation_risk_level,
        )
        generation_request = replace(
            generation_request,
            drafting_skill_selection=self._select_drafting_skill(generation_request),
        )
        draft = self._generate_draft(generation_request)
        draft_text, draft_facts_used, claim_ids_used, presentation_hints = self._sanitize_draft(
            draft,
            request=generation_request,
        )
        return EngagementBrainProposal(
            decision=review.decision,
            action_type=_action_type_for_mode(context.mode),
            draft_text=draft_text,
            presentation_hints=presentation_hints,
            goal=review.goal,
            qualification_state=review.qualification_state,
            facts_used=_merge_unique(review.facts_used, draft_facts_used),
            missing_facts=list(review.missing_facts),
            approved_claim_ids_used=claim_ids_used,
            risk_level=review.risk_level,
            community_risk_level=review.community_risk_level,
            conversation_risk_level=review.conversation_risk_level,
            resolution_strategy=review.resolution_strategy,
            escalation_reason=review.escalation_reason,
            tone_contract_fingerprint=context.tone_contract_fingerprint,
        )

    def propose(self, context: EngagementBrainContext) -> EngagementBrainProposal:
        """Compatibility helper for callers that still want proposal-only behavior."""
        review = self.review(context)
        return self.proposal_from_review(context, review)

    def _generate_draft(self, request: DraftGenerationRequest) -> DraftGenerationResult:
        generated = self._draft_generator.generate(request)
        if generated is not None:
            return generated
        fallback = self._fallback_generator.generate(request)
        if fallback is None:
            raise ValueError("A fallback draft generator is required for send decisions.")
        return fallback

    def _select_drafting_skill(self, request: DraftGenerationRequest) -> DraftingSkillSelection | None:
        selected = self._drafting_skill_selector.select(
            request.context,
            decision=request.decision,
            qualification_state=request.qualification_state,
            goal=request.goal,
            missing_facts=list(request.missing_facts),
            risk_level=request.risk_level,
            conversation_risk_level=request.conversation_risk_level,
        )
        if selected is not None:
            return selected
        return self._fallback_skill_selector.select(
            request.context,
            decision=request.decision,
            qualification_state=request.qualification_state,
            goal=request.goal,
            missing_facts=list(request.missing_facts),
            risk_level=request.risk_level,
            conversation_risk_level=request.conversation_risk_level,
        )

    def _sanitize_draft(
        self,
        draft: DraftGenerationResult,
        *,
        request: DraftGenerationRequest,
    ) -> tuple[str, list[str], list[str], list[str]]:
        text = " ".join(draft.text.split())
        facts_used = [value.strip() for value in draft.facts_used if value.strip()]
        approved_claim_ids_used = [value.strip() for value in draft.approved_claim_ids_used if value.strip()]
        max_chars = DEFAULT_GROUP_MAX_CHARS if request.context.mode is EngagementBrainMode.GROUP else DEFAULT_DM_MAX_CHARS
        allowed_claim_map = {claim.claim_id: claim for claim in request.context.allowed_claims()}
        valid_claim_ids = [claim_id for claim_id in approved_claim_ids_used if claim_id in allowed_claim_map]
        valid_fact_text = {claim.text for claim in allowed_claim_map.values()}
        facts_used = [fact for fact in facts_used if fact in valid_fact_text]

        if not text or len(text) > max_chars or _contains_forbidden_claim(text):
            fallback = self._fallback_generator.generate(request)
            if fallback is None:
                raise ValueError("Could not produce a safe fallback draft.")
            text = " ".join(fallback.text.split())
            facts_used = [value.strip() for value in fallback.facts_used if value.strip()]
            valid_claim_ids = [
                claim_id
                for claim_id in fallback.approved_claim_ids_used
                if claim_id in allowed_claim_map
            ]
            presentation_hints = list(fallback.presentation_hints)
        else:
            presentation_hints = list(draft.presentation_hints)

        if request.decision is EngagementBrainDecision.ASK_CLARIFYING_QUESTION and "?" not in text:
            text = f"{text.rstrip('.')}?"

        if request.context.mode is EngagementBrainMode.GROUP and "telegram_formatting_ok" not in presentation_hints:
            presentation_hints.append("telegram_formatting_ok")
        if request.context.mode is EngagementBrainMode.GROUP and "light_emoji_ok" not in presentation_hints:
            presentation_hints.append("light_emoji_ok")
        if request.context.mode is EngagementBrainMode.GROUP and "optional_media_consideration" not in presentation_hints:
            presentation_hints.append("optional_media_consideration")
        if request.context.mode is EngagementBrainMode.GROUP and "public_safe_question" not in presentation_hints:
            presentation_hints.append("public_safe_question")
        if request.context.mode is EngagementBrainMode.DIRECT_DM and "telegram_formatting_ok" not in presentation_hints:
            presentation_hints.append("telegram_formatting_ok")
        if (
            request.drafting_skill_selection is not None
            and request.drafting_skill_selection.primary_skill is not None
        ):
            skill_hint = f"drafting_skill:{request.drafting_skill_selection.primary_skill.skill_name}"
            if skill_hint not in presentation_hints:
                presentation_hints.append(skill_hint)

        return text[:max_chars].strip(), facts_used, valid_claim_ids, presentation_hints


def _review_from_payload(
    payload: dict[str, object],
    context: EngagementBrainContext,
    *,
    compiled_proposal_payloads: list[dict[str, object]] | None = None,
) -> EngagementBrainReview | None:
    decision = EngagementBrainDecision._value2member_map_.get(str(payload.get("decision", "")).strip())
    qualification_state = EngagementBrainQualificationState._value2member_map_.get(
        str(payload.get("qualification_state", "")).strip(),
        EngagementBrainQualificationState.CURIOUS,
    )
    risk_level = EngagementBrainRiskLevel._value2member_map_.get(
        str(payload.get("risk_level", "")).strip(),
        EngagementBrainRiskLevel.LOW,
    )
    conversation_risk_level = EngagementBrainConversationRiskLevel._value2member_map_.get(
        str(payload.get("conversation_risk_level", "")).strip(),
        EngagementBrainConversationRiskLevel.LOW,
    )
    resolution_strategy = EngagementBrainResolutionStrategy._value2member_map_.get(
        str(payload.get("resolution_strategy", "")).strip(),
        EngagementBrainResolutionStrategy.NONE,
    )
    if decision is None:
        return None

    raw_belief_state = payload.get("belief_state")
    if not isinstance(raw_belief_state, dict):
        return None
    belief_state = ConversationBeliefState.from_dict(raw_belief_state)
    if belief_state.last_belief_update_at is None:
        belief_state = replace(belief_state, last_belief_update_at=datetime.now(UTC))
    if not belief_state.last_meaningful_shift:
        belief_state = replace(
            belief_state,
            last_meaningful_shift=str(payload.get("review_summary", "")).strip(),
        )

    return EngagementBrainReview(
        decision=decision,
        qualification_state=qualification_state,
        goal=str(payload.get("goal", "")).strip() or _default_goal_for(decision, qualification_state, context.mode),
        missing_facts=_string_list(payload.get("missing_facts")),
        facts_used=_string_list(payload.get("facts_used")),
        risk_level=risk_level,
        community_risk_level=context.community_risk_level,
        conversation_risk_level=conversation_risk_level,
        resolution_strategy=resolution_strategy,
        escalation_reason=str(payload.get("escalation_reason", "")).strip(),
        belief_state=belief_state,
        learning_note=str(payload.get("learning_note", "")).strip(),
        compiled_proposal_payloads=compiled_proposal_payloads or [],
    )


def _default_goal_for(
    decision: EngagementBrainDecision,
    qualification_state: EngagementBrainQualificationState,
    mode: EngagementBrainMode,
) -> str:
    if decision is EngagementBrainDecision.WAIT:
        return "await_clear_inbound_signal"
    if decision is EngagementBrainDecision.IGNORE:
        return "avoid_needy_follow_up"
    if decision is EngagementBrainDecision.ESCALATE:
        return "protect_high_stakes_conversation"
    if decision is EngagementBrainDecision.ASK_CLARIFYING_QUESTION:
        return "narrow_buying_context" if mode is EngagementBrainMode.DIRECT_DM else "keep_public_reply_safe"
    return _goal_for_reply(mode, qualification_state)


def _goal_for_reply(
    mode: EngagementBrainMode,
    qualification_state: EngagementBrainQualificationState,
) -> str:
    if mode is EngagementBrainMode.GROUP:
        if qualification_state is EngagementBrainQualificationState.CONVERSION_READY:
            return "keep_public_reply_safe"
        return "create_interest_without_overpitching"
    if qualification_state is EngagementBrainQualificationState.CONVERSION_READY:
        return "advance_to_conversion"
    if qualification_state is EngagementBrainQualificationState.OBJECTION_OR_UNCLEAR:
        return "handle_objection"
    return "qualify_interest"


def _action_type_for_mode(mode: EngagementBrainMode) -> EngagementBrainActionType:
    if mode is EngagementBrainMode.GROUP:
        return EngagementBrainActionType.SEND_GROUP_REPLY
    return EngagementBrainActionType.SEND_DM_REPLY


def _classify_qualification_state(normalized_text: str) -> EngagementBrainQualificationState:
    if _contains_any(normalized_text, _CONVERSION_READY_KEYWORDS):
        return EngagementBrainQualificationState.CONVERSION_READY
    if _contains_any(normalized_text, _OBJECTION_KEYWORDS):
        return EngagementBrainQualificationState.OBJECTION_OR_UNCLEAR
    if _contains_any(normalized_text, _POTENTIAL_FIT_KEYWORDS):
        return EngagementBrainQualificationState.POTENTIAL_FIT
    return EngagementBrainQualificationState.CURIOUS


def _classify_conversation_risk_level(
    normalized_text: str,
    *,
    qualification_state: EngagementBrainQualificationState,
    missing_facts: list[str],
) -> EngagementBrainConversationRiskLevel:
    if _contains_any(normalized_text, _HIGH_STAKES_KEYWORDS):
        return EngagementBrainConversationRiskLevel.HIGH_STAKES
    if missing_facts:
        return EngagementBrainConversationRiskLevel.NEEDS_CLARIFICATION
    if qualification_state is EngagementBrainQualificationState.OBJECTION_OR_UNCLEAR or _contains_any(
        normalized_text,
        _PRICING_KEYWORDS,
    ):
        return EngagementBrainConversationRiskLevel.SENSITIVE
    return EngagementBrainConversationRiskLevel.LOW


def _collect_missing_facts(
    normalized_text: str,
    context: EngagementBrainContext,
) -> list[str]:
    missing_facts: list[str] = []
    approved_facts_text = " ".join(context.approved_offer_facts).lower()
    allowed_claim_text = " ".join(claim.text.lower() for claim in context.allowed_claims())
    known_fact_space = " ".join([approved_facts_text, allowed_claim_text]).strip()

    if _contains_any(normalized_text, _PRICING_KEYWORDS):
        if not _contains_any(known_fact_space, _PRICING_KEYWORDS) and not _contains_pricing_signal(known_fact_space):
            missing_facts.append("pricing_details")

    if "refund" in normalized_text and "refund" not in known_fact_space:
        missing_facts.append("refund_policy")
    return missing_facts


def _should_ask_clarifying_question(
    context: EngagementBrainContext,
    *,
    qualification_state: EngagementBrainQualificationState,
    missing_facts: list[str],
) -> bool:
    if missing_facts:
        return True
    if (
        context.mode is EngagementBrainMode.GROUP
        and context.community_risk_level in {EngagementBrainCommunityRiskLevel.HIGH, EngagementBrainCommunityRiskLevel.RESTRICTED}
        and qualification_state in {
            EngagementBrainQualificationState.POTENTIAL_FIT,
            EngagementBrainQualificationState.CONVERSION_READY,
            EngagementBrainQualificationState.OBJECTION_OR_UNCLEAR,
        }
    ):
        return True
    return False


def _contains_pricing_signal(text: str) -> bool:
    return bool(re.search(r"[$\u20ac\u00a3]\s*\d|\b\d+\s*(usd|eur|gbp|dollars|euros)\b", text))


def _contains_forbidden_claim(text: str) -> bool:
    return any(pattern.search(text) for pattern in _DEFAULT_FORBIDDEN_PATTERNS)


def _is_low_signal_message(normalized_text: str) -> bool:
    if normalized_text in _LOW_SIGNAL_MESSAGES:
        return True
    stripped = re.sub(r"[\W_]+", "", normalized_text)
    return len(stripped) <= 1


def _contains_any(text: str, keywords: tuple[str, ...] | frozenset[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _normalize_text(text: str) -> str:
    return " ".join(text.lower().split())


def _extract_objection_hints(
    latest_inbound_text: str,
    qualification_state: EngagementBrainQualificationState,
) -> list[str]:
    hints: list[str] = []
    hint_rules = (
        (("expensive", "too much", "budget"), "pricing_concern"),
        (("scam", "legit", "trust", "skeptical"), "trust_concern"),
        (("not sure", "unsure", "confused", "unclear"), "clarity_concern"),
    )
    for keywords, label in hint_rules:
        if any(keyword in latest_inbound_text for keyword in keywords):
            hints.append(label)
    if qualification_state is EngagementBrainQualificationState.OBJECTION_OR_UNCLEAR and not hints:
        hints.append("objection_or_unclear")
    return hints


def _extract_fit_signals(
    latest_inbound_text: str,
    qualification_state: EngagementBrainQualificationState,
    context: EngagementBrainContext,
) -> list[str]:
    signals: list[str] = []
    if any(keyword in latest_inbound_text for keyword in ("interested", "ready", "sign up", "start", "connect me")):
        signals.append("explicit buying intent")
    if any(keyword in latest_inbound_text for keyword in ("price", "pricing", "cost", "how much")):
        signals.append("asked about pricing")
    if any(keyword in latest_inbound_text for keyword in ("demo", "call", "link")):
        signals.append("asked for next-step logistics")
    if qualification_state is EngagementBrainQualificationState.POTENTIAL_FIT:
        signals.append("potential fit signal")
    if qualification_state is EngagementBrainQualificationState.CONVERSION_READY:
        signals.append("conversion-ready signal")
    if context.conversion_target_summary and qualification_state is EngagementBrainQualificationState.CONVERSION_READY:
        signals.append(f"conversion path available: {context.conversion_target_summary}")
    return signals[:4]


def _build_unanswered_questions(missing_facts: list[str], goal: str) -> list[str]:
    missing_fact_map = {
        "pricing_details": "What pricing details are approved for this conversation?",
        "refund_policy": "What refund policy details are approved for this conversation?",
    }
    questions = [missing_fact_map[key] for key in missing_facts if key in missing_fact_map]
    if goal == "narrow_buying_context":
        questions.append("What outcome is the lead mainly trying to solve right now?")
    return questions[:4]


def _intent_posture_for(
    qualification_state: EngagementBrainQualificationState,
    decision: EngagementBrainDecision,
) -> str:
    if decision is EngagementBrainDecision.ESCALATE:
        return "needs_operator_attention"
    if qualification_state is EngagementBrainQualificationState.CONVERSION_READY:
        return "ready_for_conversion"
    if qualification_state is EngagementBrainQualificationState.POTENTIAL_FIT:
        return "evaluating_fit"
    if qualification_state is EngagementBrainQualificationState.OBJECTION_OR_UNCLEAR:
        return "resolve_objection_or_uncertainty"
    if decision is EngagementBrainDecision.IGNORE:
        return "low_signal"
    return "early_curiosity"


def _commercial_stage_for(
    qualification_state: EngagementBrainQualificationState,
    decision: EngagementBrainDecision,
) -> str:
    if decision is EngagementBrainDecision.ESCALATE:
        return "operator_escalation"
    if decision is EngagementBrainDecision.IGNORE:
        return "low_signal"
    return qualification_state.value


def _last_meaningful_shift_for(
    qualification_state: EngagementBrainQualificationState,
    decision: EngagementBrainDecision,
    missing_facts: list[str],
) -> str:
    if decision is EngagementBrainDecision.ESCALATE:
        return "A high-stakes request appeared and should move to the operator."
    if missing_facts:
        return "The thread showed real intent, but key commercial facts are still missing."
    if decision is EngagementBrainDecision.ASK_CLARIFYING_QUESTION:
        return "The thread looks promising enough to narrow the buying context with one question."
    if qualification_state is EngagementBrainQualificationState.CONVERSION_READY:
        return "The thread now shows clear buying intent and can move toward conversion."
    if qualification_state is EngagementBrainQualificationState.POTENTIAL_FIT:
        return "The thread shows potential fit and deserves a grounded reply."
    if qualification_state is EngagementBrainQualificationState.OBJECTION_OR_UNCLEAR:
        return "The thread surfaced objections or uncertainty that should be handled carefully."
    return "The thread is still early and needs lightweight qualification."


def _suggested_next_move_for(goal: str, decision: EngagementBrainDecision) -> str:
    if decision is EngagementBrainDecision.ESCALATE:
        return "Escalate this conversation to the operator."
    goal_map = {
        "advance_to_conversion": "Move the conversation toward the conversion step.",
        "handle_objection": "Resolve the objection before pushing for conversion.",
        "qualify_interest": "Ask one grounded question to confirm fit and buying intent.",
        "narrow_buying_context": "Ask one narrow question to fill the missing commercial context.",
        "keep_public_reply_safe": "Keep the reply public-safe without overpitching.",
        "create_interest_without_overpitching": "Answer helpfully without pushing too hard in public.",
        "protect_high_stakes_conversation": "Pause automation and escalate to the operator.",
        "avoid_needy_follow_up": "Leave space and wait for a more meaningful inbound signal.",
        "await_clear_inbound_signal": "Wait for a clearer inbound signal before acting.",
    }
    return goal_map.get(goal, goal.replace("_", " ").strip().capitalize())


def _extract_grounded_facts(context: EngagementBrainContext) -> list[str]:
    facts = list(context.approved_offer_facts)
    facts.extend(claim.text for claim in context.allowed_claims())
    return _merge_unique([], facts)[:6]


def _build_learning_note(
    qualification_state: EngagementBrainQualificationState,
    latest_inbound_text: str,
) -> str:
    if qualification_state is EngagementBrainQualificationState.OBJECTION_OR_UNCLEAR:
        return f"Objection-bearing inbound worth remembering: {latest_inbound_text[:160]}".strip()
    if qualification_state is EngagementBrainQualificationState.CONVERSION_READY:
        return "The thread showed explicit conversion intent."
    return ""


def _refresh_belief_state(
    belief_state: ConversationBeliefState,
    *,
    intent_posture: str,
    commercial_stage: str,
    last_meaningful_shift: str,
    suggested_next_move: str,
) -> ConversationBeliefState:
    return replace(
        belief_state,
        intent_posture=intent_posture,
        commercial_stage=commercial_stage,
        last_meaningful_shift=last_meaningful_shift,
        suggested_next_move=suggested_next_move,
        last_belief_update_at=datetime.now(UTC),
    )


def _conversion_handoff_hint(context: EngagementBrainContext) -> str:
    summary = context.conversion_target_summary.strip()
    if not summary or summary == "Conversion target is not set.":
        return ""

    target_value = context.conversion_target_value.strip()
    if context.conversion_target_kind == "external_website":
        return f"If it helps, I can share the signup path here: {target_value or summary}."
    if context.conversion_target_kind == "telegram_bot":
        return f"If you want, I can point you to the bot next: {target_value or summary}."
    if context.conversion_target_kind == "telegram_group":
        return f"If it makes sense, I can send the group route next: {target_value or summary}."
    if context.conversion_target_kind == "telegram_channel":
        return f"If you want, I can send the channel link next: {target_value or summary}."
    if context.conversion_target_kind == "telegram_dm":
        return f"If it makes sense, I can connect you there next: {target_value or summary}."
    return ""


def _select_primary_claim(claims: list[EngagementBrainApprovedClaim]) -> tuple[str, list[str]]:
    if not claims:
        return "", []
    primary = claims[0]
    return primary.text.strip(), [primary.claim_id]


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _merge_unique(existing: list[str], incoming: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for value in [*existing, *incoming]:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        merged.append(normalized)
    return merged
