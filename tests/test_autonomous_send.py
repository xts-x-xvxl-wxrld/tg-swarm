from __future__ import annotations

from telegram_app.autonomous_send import (
    AutonomousSendDecisionType,
    AutonomousSendManager,
    AutonomousSendMode,
    AutonomousSendReviewRecord,
    AutonomousSendReviewStatus,
    AutonomousSendService,
)
from telegram_app.engagement_brain import (
    EngagementBrainActionType,
    EngagementBrainContext,
    EngagementBrainDecision,
    EngagementBrainProposal,
)
from telegram_app.external_conversations import (
    ConsentPosture,
    ExternalConversationRecord,
    ExternalConversationStatus,
    ThreadOrigin,
)
from telegram_app.live_execution import LiveActionType


def _build_context() -> EngagementBrainContext:
    return EngagementBrainContext(
        conversation=ExternalConversationRecord(
            conversation_id="conv-dm-1",
            campaign_id="cmp-1",
            account_id="reader-1",
            peer_id="user-42",
            chat_id="user-42",
            thread_origin=ThreadOrigin.DIRECT_INBOUND_DM,
            consent_posture=ConsentPosture.INBOUND_ONLY,
            status=ExternalConversationStatus.ACTIVE,
            external_user_messaged_first=True,
            last_event_id="evt-1",
            last_inbound_message_id="801",
        )
    )


def test_authorize_allows_bounded_dm_reply_when_campaign_posture_allows_it(tmp_path) -> None:
    manager = AutonomousSendManager(tmp_path / "campaigns")
    manager.update_posture(
        "cmp-1",
        dm_reply_mode=AutonomousSendMode.AUTONOMOUS_ALLOWED,
        updated_by="tests",
    )
    service = AutonomousSendService(manager)
    proposal = EngagementBrainProposal(
        decision=EngagementBrainDecision.REPLY,
        action_type=EngagementBrainActionType.SEND_DM_REPLY,
        draft_text="Happy to share more. What are you mainly trying to solve right now?",
        goal="qualify_interest",
    )

    decision = service.authorize(_build_context(), proposal, action_type=LiveActionType.SEND_DM_REPLY)

    assert decision.decision is AutonomousSendDecisionType.ALLOWED
    assert decision.approval_context["approved"] is True
    assert decision.approval_context["approval_mode"] == "autonomous"
    assert decision.context_fingerprint


def test_authorize_blocks_manual_only_reply_posture_and_persists_review_state(tmp_path) -> None:
    manager = AutonomousSendManager(tmp_path / "campaigns")
    manager.update_posture(
        "cmp-1",
        dm_reply_mode=AutonomousSendMode.MANUAL_ONLY,
        updated_by="tests",
    )
    service = AutonomousSendService(manager)
    proposal = EngagementBrainProposal(
        decision=EngagementBrainDecision.REPLY,
        action_type=EngagementBrainActionType.SEND_DM_REPLY,
        draft_text="Happy to share more. What are you mainly trying to solve right now?",
        goal="qualify_interest",
    )
    manager.save_review(
        AutonomousSendReviewRecord(
            review_id="review-1",
            campaign_id="cmp-1",
            conversation_id="conv-dm-1",
            account_id="reader-1",
            action_type=LiveActionType.SEND_DM_REPLY.value,
            draft_text="Old pending draft",
            goal="qualify_interest",
            status=AutonomousSendReviewStatus.PENDING,
        )
    )

    decision = service.authorize(_build_context(), proposal, action_type=LiveActionType.SEND_DM_REPLY)
    superseded_review = manager.get_review("cmp-1", "review-1")
    persisted_review = manager.get_review("cmp-1", decision.review_record_id)

    assert decision.decision is AutonomousSendDecisionType.BLOCKED
    assert decision.reason_codes == ["autonomous_send_disabled"]
    assert decision.recommended_operator_action == "review_autonomous_send"
    assert decision.review_record_id
    assert superseded_review is not None
    assert superseded_review.status is AutonomousSendReviewStatus.PENDING
    assert persisted_review is not None
    assert persisted_review.status is AutonomousSendReviewStatus.PENDING
    assert persisted_review.autonomous_send_mode == AutonomousSendMode.MANUAL_ONLY.value
    assert persisted_review.reason_codes == ["autonomous_send_disabled", AutonomousSendMode.MANUAL_ONLY.value]


def test_authorize_allows_group_outreach_when_campaign_posture_allows_it(tmp_path) -> None:
    manager = AutonomousSendManager(tmp_path / "campaigns")
    manager.update_posture(
        "cmp-1",
        group_outreach_mode=AutonomousSendMode.AUTONOMOUS_ALLOWED,
        updated_by="tests",
    )
    service = AutonomousSendService(manager)
    proposal = EngagementBrainProposal(
        decision=EngagementBrainDecision.REPLY,
        action_type=EngagementBrainActionType.SEND_DM_REPLY,
        draft_text="Quick follow-up.",
        goal="qualify_interest",
    )

    decision = service.authorize(_build_context(), proposal, action_type=LiveActionType.SEND_GROUP_MESSAGE)

    assert decision.decision is AutonomousSendDecisionType.ALLOWED
    assert decision.approval_context["approved"] is True
    assert decision.approval_context["approval_mode"] == "autonomous"
    assert decision.approval_context["authorized_action_type"] == LiveActionType.SEND_GROUP_MESSAGE.value


def test_authorize_blocks_manual_only_group_outreach_and_persists_review_state(tmp_path) -> None:
    manager = AutonomousSendManager(tmp_path / "campaigns")
    manager.update_posture(
        "cmp-1",
        group_outreach_mode=AutonomousSendMode.MANUAL_ONLY,
        updated_by="tests",
    )
    service = AutonomousSendService(manager)
    proposal = EngagementBrainProposal(
        decision=EngagementBrainDecision.REPLY,
        action_type=EngagementBrainActionType.SEND_DM_REPLY,
        draft_text="Quick follow-up.",
        goal="qualify_interest",
    )

    decision = service.authorize(_build_context(), proposal, action_type=LiveActionType.SEND_GROUP_MESSAGE)
    persisted_review = manager.get_review("cmp-1", decision.review_record_id)

    assert decision.decision is AutonomousSendDecisionType.BLOCKED
    assert decision.reason_codes == ["autonomous_send_disabled"]
    assert decision.recommended_operator_action == "review_autonomous_send"
    assert decision.review_record_id
    assert persisted_review is not None
    assert persisted_review.autonomous_send_mode == AutonomousSendMode.MANUAL_ONLY.value
    assert persisted_review.reason_codes == ["autonomous_send_disabled", AutonomousSendMode.MANUAL_ONLY.value]


def test_authorize_blocks_unsupported_action_family(tmp_path) -> None:
    manager = AutonomousSendManager(tmp_path / "campaigns")
    service = AutonomousSendService(manager)
    proposal = EngagementBrainProposal(
        decision=EngagementBrainDecision.REPLY,
        action_type=EngagementBrainActionType.SEND_DM_REPLY,
        draft_text="Quick follow-up.",
        goal="qualify_interest",
    )

    decision = service.authorize(_build_context(), proposal, action_type=LiveActionType.LEAVE_DIALOG)

    assert decision.decision is AutonomousSendDecisionType.BLOCKED
    assert decision.reason_codes == ["unsupported_action_family"]
