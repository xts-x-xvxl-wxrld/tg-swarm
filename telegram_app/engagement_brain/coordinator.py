"""Runtime bridge from engagement-brain proposals into queued live actions."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from typing import TYPE_CHECKING
from uuid import uuid4

from telegram_app.autonomous_send import AutonomousSendService
from telegram_app.campaign_memory.operational_notes import NEXT_ACTIONS_DESTINATION
from telegram_app.compiled_intents import (
    CompiledIntentApplicator,
    CompiledIntentApplicationError,
    CompiledIntentStore,
    compile_conversation_belief_update,
    compile_engagement_next_move,
    compile_memory_note,
    compile_output_proposals,
    validate_compiled_intent,
)
from telegram_app.engagement_brain.context_builder import EngagementBrainContextBuilder
from telegram_app.engagement_brain.models import (
    EngagementBrainActionType,
    EngagementBrainContext,
    EngagementBrainDecision,
    EngagementBrainProposal,
    EngagementBrainReview,
    EngagementBrainRunDisposition,
    EngagementBrainRunResult,
)
from telegram_app.engagement_brain.service import EngagementBrainService
from telegram_app.external_conversations import ConversationReviewTrigger, ExternalConversationManager
from telegram_app.live_execution import LiveActionRecord, LiveActionType, LiveExecutionService
from telegram_app.qualification import QualificationService

if TYPE_CHECKING:
    from telegram_app.engagement_policy.service import CampaignEngagementPolicyService

_SEND_ACTION_TYPE_MAP = {
    EngagementBrainActionType.SEND_GROUP_REPLY: LiveActionType.SEND_GROUP_REPLY,
    EngagementBrainActionType.SEND_DM_REPLY: LiveActionType.SEND_DM_REPLY,
}
_NO_ACTION_TYPE_MAP = {
    EngagementBrainDecision.WAIT: "brain_wait",
    EngagementBrainDecision.IGNORE: "brain_ignore",
    EngagementBrainDecision.ESCALATE: "brain_escalate",
}


class EngagementBrainCoordinator:
    """Build context, run the brain, and queue allowed live actions."""

    def __init__(
        self,
        context_builder: EngagementBrainContextBuilder,
        conversation_manager: ExternalConversationManager,
        live_execution_service: LiveExecutionService,
        autonomous_send_service: AutonomousSendService,
        qualification_service: QualificationService | None = None,
        *,
        brain_service: EngagementBrainService | None = None,
        compiled_intent_store: CompiledIntentStore | None = None,
        compiled_intent_applicator: CompiledIntentApplicator | None = None,
        engagement_policy_service: CampaignEngagementPolicyService | None = None,
    ) -> None:
        self._context_builder = context_builder
        self._conversation_manager = conversation_manager
        self._live_execution_service = live_execution_service
        self._autonomous_send_service = autonomous_send_service
        self._qualification_service = qualification_service
        self._brain_service = brain_service or EngagementBrainService()
        self._compiled_intent_store = compiled_intent_store
        self._compiled_intent_applicator = compiled_intent_applicator
        self._engagement_policy_service = engagement_policy_service

    def review_conversation(
        self,
        campaign_id: str,
        conversation_id: str,
        *,
        trigger: ConversationReviewTrigger | None = None,
        now: datetime | None = None,
    ) -> EngagementBrainRunResult | None:
        """Run the engagement brain for one conversation and persist the next outcome."""
        context = self._context_builder.build(campaign_id, conversation_id)
        if context is None:
            return None

        review, proposal = self._review_and_propose(context)
        qualification_review = (
            self._qualification_service.record_proposal(
                context,
                proposal,
                belief_state=review.belief_state if review is not None else None,
            )
            if self._qualification_service is not None
            else None
        )
        self._persist_review_outputs(
            context,
            proposal,
            review=review,
            qualification_review=qualification_review,
        )
        if proposal.action_type is EngagementBrainActionType.NONE:
            return self._record_non_send_outcome(context, proposal)

        live_action_type = _SEND_ACTION_TYPE_MAP.get(proposal.action_type)
        if live_action_type is None:
            return self._record_non_send_outcome(context, proposal)

        authorization_decision = self._autonomous_send_service.authorize(
            context,
            proposal,
            action_type=live_action_type,
            trigger=trigger,
        )
        if authorization_decision.decision.value == "blocked":
            if authorization_decision.review_record_id:
                self._conversation_manager.set_pending_autonomous_review(
                    campaign_id,
                    conversation_id,
                    review_id=authorization_decision.review_record_id,
                )
            else:
                self._conversation_manager.clear_pending_autonomous_review(campaign_id, conversation_id)
            self._conversation_manager.update_next_action(
                campaign_id,
                conversation_id,
                next_action_type=(
                    authorization_decision.recommended_operator_action or "autonomous_send_blocked"
                ),
                next_action_reason=authorization_decision.summary,
                status_reason=authorization_decision.primary_reason_code(),
            )
            self._mark_handoff_blocked_if_needed(
                campaign_id,
                conversation_id,
                qualification_review,
                summary=authorization_decision.summary,
                action_id="",
            )
            return EngagementBrainRunResult(
                conversation_id=conversation_id,
                proposal=proposal,
                disposition=EngagementBrainRunDisposition.BLOCKED_BY_AUTHORIZATION,
                authorization_reason_codes=list(authorization_decision.reason_codes),
                review_record_id=authorization_decision.review_record_id,
                summary=authorization_decision.summary,
            )

        candidate = self._build_candidate_action(
            context,
            proposal,
            action_type=live_action_type,
            approval_context=self._merge_approval_context(
                authorization_decision.approval_context,
                qualification_review.approval_context if qualification_review is not None else {},
            ),
        )
        policy_decision = self._live_execution_service.evaluate_policy(candidate)
        if policy_decision.decision.value != "allowed":
            self._conversation_manager.clear_pending_autonomous_review(campaign_id, conversation_id)
            self._conversation_manager.update_next_action(
                campaign_id,
                conversation_id,
                next_action_type="policy_hold",
                next_action_reason=policy_decision.summary,
                status_reason=policy_decision.primary_reason_code(),
            )
            self._mark_handoff_blocked_if_needed(
                campaign_id,
                conversation_id,
                qualification_review,
                summary=policy_decision.summary,
                action_id="",
            )
            return EngagementBrainRunResult(
                conversation_id=conversation_id,
                proposal=proposal,
                disposition=EngagementBrainRunDisposition.BLOCKED_BY_POLICY,
                policy_reason_codes=list(policy_decision.reason_codes),
                summary=policy_decision.summary,
            )

        timing_decision = (
            self._engagement_policy_service.plan_reply(
                context,
                proposal,
                trigger=trigger,
                now=now,
            )
            if self._engagement_policy_service is not None
            else None
        )
        if timing_decision is not None and timing_decision.decision_type.value == "suppress":
            summary = timing_decision.suppression_reason or "Suppressed a reply based on campaign policy."
            self._conversation_manager.clear_pending_autonomous_review(campaign_id, conversation_id)
            self._conversation_manager.update_next_action(
                campaign_id,
                conversation_id,
                next_action_type="policy_suppressed_reply",
                next_action_reason=summary,
                status_reason=timing_decision.suppression_reason,
            )
            self._mark_handoff_blocked_if_needed(
                campaign_id,
                conversation_id,
                qualification_review,
                summary=summary,
                action_id="",
            )
            return EngagementBrainRunResult(
                conversation_id=conversation_id,
                proposal=proposal,
                disposition=EngagementBrainRunDisposition.NO_ACTION,
                summary=summary,
            )

        action = self._live_execution_service.enqueue_action(
            campaign_id,
            context.conversation.account_id,
            action_type=live_action_type,
            conversation_id=conversation_id,
            payload=self._build_action_payload(
                context,
                proposal,
                approval_context=self._merge_approval_context(
                    authorization_decision.approval_context,
                    qualification_review.approval_context if qualification_review is not None else {},
                ),
                timing_decision=timing_decision,
            ),
            idempotency_key=self._build_idempotency_key(
                context,
                proposal,
                action_type=live_action_type,
                trigger=trigger,
            ),
            next_attempt_at=(
                timing_decision.execute_at
                if timing_decision is not None and timing_decision.decision_type.value == "delay"
                else None
            ),
        )
        self._conversation_manager.clear_pending_autonomous_review(campaign_id, conversation_id)
        self._conversation_manager.update_next_action(
            campaign_id,
            conversation_id,
            next_action_type=f"queued_{live_action_type.value}",
            next_action_reason=f"Queued by engagement brain for {proposal.goal or proposal.decision.value}.",
            status_reason="",
        )
        return EngagementBrainRunResult(
            conversation_id=conversation_id,
            proposal=proposal,
            disposition=EngagementBrainRunDisposition.ENQUEUED,
            action_id=action.action_id,
            authorization_reason_codes=list(authorization_decision.reason_codes),
            summary=f"Queued {live_action_type.value} from a brain proposal.",
        )

    def _review_and_propose(
        self,
        context: EngagementBrainContext,
    ) -> tuple[EngagementBrainReview | None, EngagementBrainProposal]:
        review_method = getattr(self._brain_service, "review", None)
        proposal_from_review = getattr(self._brain_service, "proposal_from_review", None)
        if callable(review_method) and callable(proposal_from_review):
            review = review_method(context)
            return review, proposal_from_review(context, review)
        return None, self._brain_service.propose(context)

    def _persist_review_outputs(
        self,
        context: EngagementBrainContext,
        proposal: EngagementBrainProposal,
        *,
        review: EngagementBrainReview | None,
        qualification_review,  # noqa: ANN001
    ) -> None:
        resolved_belief_state = (
            qualification_review.belief_state
            if qualification_review is not None and qualification_review.belief_state is not None
            else review.belief_state if review is not None else None
        )
        learning_note = review.learning_note if review is not None else ""
        if self._compiled_intent_store is None or self._compiled_intent_applicator is None:
            if resolved_belief_state is not None and self._qualification_service is None:
                self._conversation_manager.update_belief_state(
                    context.conversation.campaign_id,
                    context.conversation.conversation_id,
                    belief_state=resolved_belief_state,
                    summary=resolved_belief_state.last_meaningful_shift,
                )
            return

        compiled_intents = self._build_review_compiled_intents(
            context,
            proposal,
            resolved_belief_state=resolved_belief_state,
            learning_note=learning_note,
            review=review,
        )

        for compiled_intent in compiled_intents:
            self._persist_compiled_intent(compiled_intent)

    def _build_review_compiled_intents(
        self,
        context: EngagementBrainContext,
        proposal: EngagementBrainProposal,
        *,
        resolved_belief_state,
        learning_note: str,
        review: EngagementBrainReview | None,
    ) -> list:
        grounding_refs = self._build_grounding_refs(context)
        raw_output_proposals = self._enrich_review_output_proposals(
            context,
            proposal,
            resolved_belief_state=resolved_belief_state,
            learning_note=learning_note,
            review=review,
        )
        if raw_output_proposals:
            return compile_output_proposals(
                context.conversation.campaign_id,
                raw_output_proposals,
                source_role="engagement_brain",
                grounding_refs=grounding_refs,
            )

        compiled_intents = []
        next_move_intent = compile_engagement_next_move(
            context.conversation.campaign_id,
            proposal_payload=self._build_next_move_payload(
                context,
                proposal,
                resolved_belief_state=resolved_belief_state,
            ),
            source_role="engagement_brain",
            grounding_refs=grounding_refs,
        )
        if next_move_intent is not None:
            compiled_intents.append(next_move_intent)
        if resolved_belief_state is not None:
            compiled_intents.append(
                compile_conversation_belief_update(
                    context.conversation.campaign_id,
                    conversation_id=context.conversation.conversation_id,
                    belief_state=resolved_belief_state,
                    summary=resolved_belief_state.last_meaningful_shift,
                    source_role="engagement_brain",
                    grounding_refs=grounding_refs,
                )
            )
        if learning_note.strip():
            compiled_intents.append(
                compile_memory_note(
                    context.conversation.campaign_id,
                    destination=NEXT_ACTIONS_DESTINATION,
                    line=learning_note,
                    summary="Save a campaign learning note from promoted-thread review.",
                    source_role="engagement_brain",
                    category="engagement_review",
                    dedupe_key=(
                        f"{context.conversation.conversation_id}:{context.conversation.last_event_id}:learning"
                    ),
                    grounding_refs=grounding_refs,
                )
            )
        return compiled_intents

    def _enrich_review_output_proposals(
        self,
        context: EngagementBrainContext,
        proposal: EngagementBrainProposal,
        *,
        resolved_belief_state,
        learning_note: str,
        review: EngagementBrainReview | None,
    ) -> list[dict[str, object]]:
        if review is None or not review.compiled_proposal_payloads:
            return []

        next_move_payload = self._build_next_move_payload(
            context,
            proposal,
            resolved_belief_state=resolved_belief_state,
        )
        enriched: list[dict[str, object]] = []
        for raw_proposal in review.compiled_proposal_payloads:
            proposal_payload = dict(raw_proposal)
            kind = str(proposal_payload.get("kind", "")).strip()
            payload = proposal_payload.get("payload")
            if not isinstance(payload, dict):
                continue
            merged_payload = dict(payload)
            if kind == "engagement.next_move":
                merged_payload = {
                    **merged_payload,
                    **next_move_payload,
                }
            elif kind == "conversation.update_belief_state" and resolved_belief_state is not None:
                merged_payload.setdefault("conversation_id", context.conversation.conversation_id)
                merged_payload["belief_state"] = resolved_belief_state.to_dict()
                merged_payload.setdefault("summary", resolved_belief_state.last_meaningful_shift)
            elif kind == "memory.note" and learning_note.strip():
                merged_payload.setdefault("destination", NEXT_ACTIONS_DESTINATION)
                merged_payload.setdefault("line", learning_note)
                merged_payload.setdefault("category", "engagement_review")
                merged_payload.setdefault(
                    "dedupe_key",
                    f"{context.conversation.conversation_id}:{context.conversation.last_event_id}:learning",
                )
            proposal_payload["payload"] = merged_payload
            enriched.append(proposal_payload)
        return enriched

    def _build_next_move_payload(
        self,
        context: EngagementBrainContext,
        proposal: EngagementBrainProposal,
        *,
        resolved_belief_state,
    ) -> dict[str, object]:
        return {
            "conversation_id": context.conversation.conversation_id,
            "decision": proposal.decision.value,
            "action_type": proposal.action_type.value,
            "goal": proposal.goal,
            "qualification_state": proposal.qualification_state.value,
            "risk_level": proposal.risk_level.value,
            "community_risk_level": proposal.community_risk_level.value,
            "conversation_risk_level": proposal.conversation_risk_level.value,
            "resolution_strategy": proposal.resolution_strategy.value,
            "escalation_reason": proposal.escalation_reason,
            "review_summary": (
                resolved_belief_state.last_meaningful_shift if resolved_belief_state is not None else ""
            ),
            "facts_used": list(proposal.facts_used),
            "missing_facts": list(proposal.missing_facts),
            "approved_claim_ids_used": list(proposal.approved_claim_ids_used),
            "presentation_hints": list(proposal.presentation_hints),
            "draft_text": proposal.draft_text,
        }

    def _record_non_send_outcome(
        self,
        context: EngagementBrainContext,
        proposal: EngagementBrainProposal,
    ) -> EngagementBrainRunResult:
        next_action_type = _NO_ACTION_TYPE_MAP.get(proposal.decision, "brain_hold")
        next_action_reason = proposal.escalation_reason or proposal.goal or proposal.decision.value
        self._conversation_manager.clear_pending_autonomous_review(
            context.conversation.campaign_id,
            context.conversation.conversation_id,
        )
        self._conversation_manager.update_next_action(
            context.conversation.campaign_id,
            context.conversation.conversation_id,
            next_action_type=next_action_type,
            next_action_reason=next_action_reason,
        )
        return EngagementBrainRunResult(
            conversation_id=context.conversation.conversation_id,
            proposal=proposal,
            disposition=EngagementBrainRunDisposition.NO_ACTION,
            summary=next_action_reason,
        )

    def _build_candidate_action(
        self,
        context: EngagementBrainContext,
        proposal: EngagementBrainProposal,
        *,
        action_type: LiveActionType,
        approval_context: dict[str, object],
    ) -> LiveActionRecord:
        return LiveActionRecord(
            action_id=f"preview::{uuid4()}",
            campaign_id=context.conversation.campaign_id,
            account_id=context.conversation.account_id,
            action_type=action_type,
            conversation_id=context.conversation.conversation_id,
            payload=self._build_action_payload(context, proposal, approval_context=approval_context),
        )

    def _build_action_payload(
        self,
        context: EngagementBrainContext,
        proposal: EngagementBrainProposal,
        *,
        approval_context: dict[str, object],
        timing_decision=None,  # noqa: ANN001
    ) -> dict[str, object]:
        resolved_approval_context = dict(approval_context)
        if context.community_guidance is not None:
            community_key = context.community_guidance.community_id.strip() or context.community_guidance.chat_id.strip()
            community_type = context.community_guidance.community_type.strip()
        else:
            community_key = context.conversation.community_id.strip() or context.conversation.chat_id.strip()
            community_type = ""
        return {
            "chat_id": context.conversation.chat_id,
            "text": proposal.draft_text,
            "approval_context": resolved_approval_context,
            "engagement_policy_context": (
                {
                    **timing_decision.to_metadata(),
                    "community_key": community_key,
                    "community_type": community_type,
                    "objection_hints": list(context.conversation.triage_state.objection_hints),
                }
                if timing_decision is not None
                else {}
            ),
        }

    def _build_idempotency_key(
        self,
        context: EngagementBrainContext,
        proposal: EngagementBrainProposal,
        *,
        action_type: LiveActionType,
        trigger: ConversationReviewTrigger | None = None,
    ) -> str:
        key_material = "|".join(
            [
                "engagement_brain",
                context.conversation.campaign_id,
                context.conversation.conversation_id,
                trigger.trigger_key if trigger is not None else context.conversation.last_event_id,
                action_type.value,
                proposal.draft_text,
            ]
        )
        return sha256(key_material.encode("utf-8")).hexdigest()

    def _merge_approval_context(
        self,
        approval_context: dict[str, object],
        qualification_context: dict[str, object],
    ) -> dict[str, object]:
        return {
            **dict(approval_context),
            **dict(qualification_context),
        }

    def _mark_handoff_blocked_if_needed(
        self,
        campaign_id: str,
        conversation_id: str,
        qualification_review,  # noqa: ANN001
        *,
        summary: str,
        action_id: str,
    ) -> None:
        if self._qualification_service is None or qualification_review is None:
            return
        if not qualification_review.approval_context.get("handoff_intent", False):
            return
        self._qualification_service.mark_handoff_blocked(
            campaign_id,
            conversation_id,
            action_id=action_id,
            summary=summary,
        )

    def _persist_compiled_intent(self, intent) -> None:  # noqa: ANN001
        if self._compiled_intent_store is None or self._compiled_intent_applicator is None:
            return
        self._compiled_intent_store.save(intent)
        validation_error = validate_compiled_intent(intent)
        if validation_error is not None:
            intent.mark_rejected(validation_error)
            self._compiled_intent_store.save(intent)
            return
        intent.mark_accepted()
        self._compiled_intent_store.save(intent)
        try:
            result = self._compiled_intent_applicator.apply(intent)
        except CompiledIntentApplicationError as exc:
            intent.mark_blocked(str(exc))
            self._compiled_intent_store.save(intent)
            return
        intent.mark_applied(result)
        self._compiled_intent_store.save(intent)

    def _build_grounding_refs(self, context: EngagementBrainContext) -> list[str]:
        refs = [
            f"campaign:{context.conversation.campaign_id}",
            f"conversation:{context.conversation.conversation_id}",
        ]
        if context.conversation.last_event_id:
            refs.append(f"event:{context.conversation.last_event_id}")
        refs.extend(context.conversation.recent_message_refs[-3:])
        return refs
