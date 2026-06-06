"""Authorization service for bounded autonomous sends."""

from __future__ import annotations

from hashlib import sha256
from typing import TYPE_CHECKING

from telegram_app.autonomous_send.manager import AutonomousSendManager
from telegram_app.autonomous_send.models import (
    AutonomousSendDecision,
    AutonomousSendDecisionType,
    AutonomousSendMode,
    AutonomousSendReviewRecord,
    AutonomousSendReviewStatus,
    utc_now,
)
from telegram_app.external_conversations import ConversationReviewTrigger, ExternalConversationManager
from telegram_app.live_execution import LiveActionType, LiveExecutionService

if TYPE_CHECKING:
    from telegram_app.engagement_brain.models import EngagementBrainContext, EngagementBrainProposal

_SUPPORTED_ACTION_TYPES = frozenset(
    {
        LiveActionType.SEND_GROUP_MESSAGE,
        LiveActionType.SEND_GROUP_REPLY,
        LiveActionType.SEND_DM_REPLY,
    }
)


class AutonomousSendService:
    """Authorize grounded engagement-brain proposals before they become live sends."""

    def __init__(
        self,
        manager: AutonomousSendManager,
        *,
        conversation_manager: ExternalConversationManager | None = None,
        live_execution_service: LiveExecutionService | None = None,
    ) -> None:
        self._manager = manager
        self._conversation_manager = conversation_manager
        self._live_execution_service = live_execution_service

    def authorize(
        self,
        context: EngagementBrainContext,
        proposal: EngagementBrainProposal,
        *,
        action_type: LiveActionType,
        trigger: ConversationReviewTrigger | None = None,
    ) -> AutonomousSendDecision:
        """Return whether one proposal may count as an approved autonomous send."""
        conversation = context.conversation
        if action_type not in _SUPPORTED_ACTION_TYPES:
            return AutonomousSendDecision(
                decision=AutonomousSendDecisionType.BLOCKED,
                reason_codes=["unsupported_action_family"],
                summary="Blocked an autonomous send proposal because this action family is not supported yet.",
                action_type=action_type.value,
                campaign_id=conversation.campaign_id,
                conversation_id=conversation.conversation_id,
            )

        if not conversation.campaign_id:
            return AutonomousSendDecision(
                decision=AutonomousSendDecisionType.BLOCKED,
                reason_codes=["missing_campaign_context"],
                summary="Blocked an autonomous send proposal because no campaign context was available.",
                action_type=action_type.value,
                conversation_id=conversation.conversation_id,
            )

        if not conversation.conversation_id:
            return AutonomousSendDecision(
                decision=AutonomousSendDecisionType.BLOCKED,
                reason_codes=["missing_conversation_context"],
                summary="Blocked an autonomous send proposal because no conversation context was available.",
                action_type=action_type.value,
                campaign_id=conversation.campaign_id,
            )

        context_fingerprint = self.build_context_fingerprint(
            context,
            proposal,
            action_type=action_type,
            trigger=trigger,
        )
        trigger_key = trigger.trigger_key if trigger is not None else conversation.last_event_id
        posture = self._manager.get_posture(conversation.campaign_id)
        autonomous_send_mode = posture.mode_for_action(action_type.value)

        if autonomous_send_mode is not AutonomousSendMode.AUTONOMOUS_ALLOWED:
            review = self._persist_review(
                context,
                proposal,
                action_type=action_type,
                trigger=trigger,
                context_fingerprint=context_fingerprint,
                reason_codes=["autonomous_send_disabled", autonomous_send_mode.value],
                summary="Autonomous sending is disabled for this campaign posture, so operator review is required.",
                autonomous_send_mode=autonomous_send_mode,
            )
            return AutonomousSendDecision(
                decision=AutonomousSendDecisionType.BLOCKED,
                reason_codes=["autonomous_send_disabled"],
                summary="Autonomous sending is disabled for this campaign posture.",
                action_type=action_type.value,
                campaign_id=conversation.campaign_id,
                conversation_id=conversation.conversation_id,
                trigger_key=trigger_key,
                context_fingerprint=context_fingerprint,
                recommended_operator_action="review_autonomous_send",
                review_record_id=review.review_id,
            )

        if context.community_risk_level.value == "restricted":
            review = self._persist_review(
                context,
                proposal,
                action_type=action_type,
                trigger=trigger,
                context_fingerprint=context_fingerprint,
                reason_codes=["community_requires_manual_review"],
                summary="This community is risk-restricted, so operator review is required before sending.",
                autonomous_send_mode=autonomous_send_mode,
            )
            return AutonomousSendDecision(
                decision=AutonomousSendDecisionType.BLOCKED,
                reason_codes=["community_requires_manual_review"],
                summary="This community is currently too risky for autonomous sending.",
                action_type=action_type.value,
                campaign_id=conversation.campaign_id,
                conversation_id=conversation.conversation_id,
                trigger_key=trigger_key,
                context_fingerprint=context_fingerprint,
                recommended_operator_action="review_autonomous_send",
                review_record_id=review.review_id,
            )

        if proposal.risk_level.value == "high" or proposal.conversation_risk_level.value == "high_stakes":
            review = self._persist_review(
                context,
                proposal,
                action_type=action_type,
                trigger=trigger,
                context_fingerprint=context_fingerprint,
                reason_codes=["conversation_requires_manual_review"],
                summary="This proposal is too risky for autonomous sending and requires operator review.",
                autonomous_send_mode=autonomous_send_mode,
            )
            return AutonomousSendDecision(
                decision=AutonomousSendDecisionType.BLOCKED,
                reason_codes=["conversation_requires_manual_review"],
                summary="This proposal is too risky for autonomous sending.",
                action_type=action_type.value,
                campaign_id=conversation.campaign_id,
                conversation_id=conversation.conversation_id,
                trigger_key=trigger_key,
                context_fingerprint=context_fingerprint,
                recommended_operator_action="review_autonomous_send",
                review_record_id=review.review_id,
            )

        self._manager.supersede_pending_reviews(
            conversation.campaign_id,
            conversation.conversation_id,
            action_type=action_type.value,
            resolution_note="Superseded because this supported reply send now flows directly after bounded authorization.",
        )
        approval_context: dict[str, object] = {
            "approved": True,
            "approval_mode": "autonomous",
            "approval_source": "engagement_brain_authorizer",
            "authorization_decision": "allowed",
            "authorized_action_type": action_type.value,
            "campaign_id": conversation.campaign_id,
            "conversation_id": conversation.conversation_id,
            "trigger_key": trigger_key,
            "context_fingerprint": context_fingerprint,
            "brain_decision": proposal.decision.value,
            "goal": proposal.goal,
            "autonomous_send_mode": autonomous_send_mode.value,
            "community_risk_level": proposal.community_risk_level.value,
            "conversation_risk_level": proposal.conversation_risk_level.value,
            "approved_claim_ids_used": list(proposal.approved_claim_ids_used),
            "tone_contract_fingerprint": proposal.tone_contract_fingerprint or context.tone_contract_fingerprint,
            "authorized_at": utc_now().isoformat(),
        }
        if trigger is not None:
            approval_context["review_trigger"] = {
                "trigger_key": trigger.trigger_key,
                "trigger_source": trigger.trigger_source,
                "trigger_type": trigger.trigger_type.value,
            }
        return AutonomousSendDecision(
            decision=AutonomousSendDecisionType.ALLOWED,
            reason_codes=["autonomous_send_allowed"],
            summary="Authorized a bounded autonomous send from the engagement brain.",
            action_type=action_type.value,
            campaign_id=conversation.campaign_id,
            conversation_id=conversation.conversation_id,
            trigger_key=trigger_key,
            context_fingerprint=context_fingerprint,
            approval_context=approval_context,
        )

    def _persist_review(
        self,
        context: EngagementBrainContext,
        proposal: EngagementBrainProposal,
        *,
        action_type: LiveActionType,
        trigger: ConversationReviewTrigger | None,
        context_fingerprint: str,
        reason_codes: list[str],
        summary: str,
        autonomous_send_mode: AutonomousSendMode,
    ) -> AutonomousSendReviewRecord:
        trigger_key = trigger.trigger_key if trigger is not None else context.conversation.last_event_id
        review = AutonomousSendReviewRecord(
            review_id=f"review-{context_fingerprint[:16]}",
            campaign_id=context.conversation.campaign_id,
            conversation_id=context.conversation.conversation_id,
            account_id=context.conversation.account_id,
            action_type=action_type.value,
            status=AutonomousSendReviewStatus.PENDING,
            draft_text=proposal.draft_text,
            goal=proposal.goal,
            qualification_state=proposal.qualification_state.value,
            presentation_hints=list(proposal.presentation_hints),
            approved_claim_ids_used=list(proposal.approved_claim_ids_used),
            community_risk_level=proposal.community_risk_level.value,
            conversation_risk_level=proposal.conversation_risk_level.value,
            autonomous_send_mode=autonomous_send_mode.value,
            trigger_key=trigger_key,
            trigger_source=trigger.trigger_source if trigger is not None else "conversation_review",
            context_fingerprint=context_fingerprint,
            reason_codes=list(reason_codes),
            summary=summary,
        )
        return self._manager.save_review(review)

    def build_context_fingerprint(
        self,
        context: EngagementBrainContext,
        proposal: EngagementBrainProposal,
        *,
        action_type: LiveActionType,
        trigger: ConversationReviewTrigger | None = None,
    ) -> str:
        """Build a stable fingerprint for one bounded proposal context."""
        conversation = context.conversation
        key_material = "|".join(
            [
                conversation.campaign_id.strip(),
                conversation.conversation_id.strip(),
                action_type.value,
                trigger.trigger_key if trigger is not None else conversation.last_event_id.strip(),
                conversation.last_event_id.strip(),
                conversation.last_inbound_message_id.strip(),
                conversation.reply_target_message_id.strip(),
                proposal.draft_text.strip(),
            ]
        )
        return sha256(key_material.encode("utf-8")).hexdigest()

    def materialize_review(
        self,
        campaign_id: str,
        review_id: str,
        *,
        operator_id: str,
    ) -> str:
        """Queue one pending review record as an operator-approved live action."""
        review = self._manager.get_review(campaign_id, review_id)
        if review is None:
            return f"I could not find autonomous review `{review_id}`."
        if review.status is not AutonomousSendReviewStatus.PENDING:
            return f"Autonomous review `{review.review_id}` is already `{review.status.value}`."
        if self._conversation_manager is None or self._live_execution_service is None:
            return "Autonomous review approval is not available in this runtime yet."

        conversation = self._conversation_manager.get(campaign_id, review.conversation_id)
        if conversation is None:
            return (
                f"I could not materialize `{review.review_id}` because conversation "
                f"`{review.conversation_id}` no longer exists."
            )

        current_fingerprint = self._build_review_fingerprint(review, conversation)
        if review.context_fingerprint and current_fingerprint != review.context_fingerprint:
            return (
                f"I did not approve `{review.review_id}` because the conversation moved since that draft was created. "
                "Please review the latest live state first."
            )

        approval_context = {
            "approved": True,
            "approval_mode": "operator",
            "approval_source": "telegram_live_ops",
            "approval_reason": "autonomous_review_approved",
            "review_id": review.review_id,
            "campaign_id": review.campaign_id,
            "conversation_id": review.conversation_id,
            "context_fingerprint": review.context_fingerprint,
            "approved_at": utc_now().isoformat(),
            "approved_by": operator_id.strip(),
            "autonomous_send_mode": review.autonomous_send_mode,
            "approved_claim_ids_used": list(review.approved_claim_ids_used),
        }
        if review.trigger_key:
            approval_context["trigger_key"] = review.trigger_key

        payload: dict[str, object] = {
            "chat_id": conversation.chat_id,
            "text": review.draft_text,
            "approval_context": approval_context,
        }
        if conversation.reply_target_message_id:
            payload["reply_to_message_id"] = conversation.reply_target_message_id

        action = self._live_execution_service.enqueue_action(
            campaign_id=review.campaign_id,
            account_id=review.account_id,
            action_type=LiveActionType(review.action_type),
            payload=payload,
            conversation_id=review.conversation_id,
            idempotency_key=f"autonomous-review:{review.review_id}",
        )
        review.status = AutonomousSendReviewStatus.MATERIALIZED
        review.resolved_at = utc_now()
        review.resolved_by = operator_id.strip()
        review.resolution_note = "Approved from Telegram live ops."
        review.materialized_action_id = action.action_id
        self._manager.save_review(review)
        self._conversation_manager.clear_pending_autonomous_review(campaign_id, review.conversation_id)
        self._conversation_manager.update_next_action(
            campaign_id,
            review.conversation_id,
            next_action_type=f"queued_{review.action_type}",
            next_action_reason="Operator approved the pending autonomous draft and queued it for send.",
            status_reason="operator_approved",
        )
        return (
            f"Approved `{review.review_id}` and queued `{review.action_type}` as `{action.action_id}`."
        )

    def dismiss_review(
        self,
        campaign_id: str,
        review_id: str,
        *,
        operator_id: str,
        note: str = "",
    ) -> str:
        """Dismiss one pending autonomous review and clear its conversation linkage."""
        review = self._manager.get_review(campaign_id, review_id)
        if review is None:
            return f"I could not find autonomous review `{review_id}`."
        if review.status is not AutonomousSendReviewStatus.PENDING:
            return f"Autonomous review `{review.review_id}` is already `{review.status.value}`."

        review.status = AutonomousSendReviewStatus.DISMISSED
        review.resolved_at = utc_now()
        review.resolved_by = operator_id.strip()
        review.resolution_note = note.strip() or "Dismissed from Telegram live ops."
        self._manager.save_review(review)
        if self._conversation_manager is not None:
            self._conversation_manager.clear_pending_autonomous_review(campaign_id, review.conversation_id)
            self._conversation_manager.update_next_action(
                campaign_id,
                review.conversation_id,
                next_action_type="operator_review",
                next_action_reason="Operator dismissed the pending autonomous draft.",
                status_reason="operator_dismissed",
            )
        return f"Dismissed `{review.review_id}`."

    def _build_review_fingerprint(
        self,
        review: AutonomousSendReviewRecord,
        conversation,
    ) -> str:
        trigger_key = review.trigger_key or conversation.last_event_id
        key_material = "|".join(
            [
                review.campaign_id.strip(),
                review.conversation_id.strip(),
                review.action_type.strip(),
                trigger_key.strip(),
                conversation.last_event_id.strip(),
                conversation.last_inbound_message_id.strip(),
                conversation.reply_target_message_id.strip(),
                review.draft_text.strip(),
            ]
        )
        return sha256(key_material.encode("utf-8")).hexdigest()
