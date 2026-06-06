from __future__ import annotations

from datetime import UTC, datetime

from telegram_app.autonomous_send import AutonomousSendManager, AutonomousSendMode, AutonomousSendService
from telegram_app.campaigns import CampaignManager
from telegram_app.engagement import (
    EngagementEventKind,
    EngagementEventRecord,
    EngagementRoutingStatus,
    ManagedAccountEngagementStore,
)
from telegram_app.engagement_brain import (
    ConversationReviewDispatcher,
    EngagementBrainActionType,
    EngagementBrainContextBuilder,
    EngagementBrainCoordinator,
    EngagementBrainDecision,
    EngagementBrainProposal,
    EngagementBrainRunDisposition,
)
from telegram_app.engagement_triage import CheapInboundTriageService, TriagePromotionDecision
from telegram_app.external_conversations import (
    ConsentPosture,
    ConversationReviewTriggerType,
    ExternalConversationManager,
    ExternalConversationRecord,
    ExternalConversationStatus,
    FollowUpWindowType,
    ThreadOrigin,
)
from telegram_app.live_execution import LiveActionType, LiveExecutionManager, LiveExecutionService


def _build_autonomous_send_service(campaigns_root, *, group_reply_allowed: bool = False, dm_reply_allowed: bool = False):  # noqa: ANN001
    manager = AutonomousSendManager(campaigns_root)
    manager.update_posture(
        "cmp-1",
        group_reply_mode=AutonomousSendMode.AUTONOMOUS_ALLOWED if group_reply_allowed else AutonomousSendMode.MANUAL_ONLY,
        dm_reply_mode=AutonomousSendMode.AUTONOMOUS_ALLOWED if dm_reply_allowed else AutonomousSendMode.MANUAL_ONLY,
        updated_by="tests",
    )
    return AutonomousSendService(manager)


class FakeBrainService:
    def __init__(self, proposal: EngagementBrainProposal) -> None:
        self._proposal = proposal

    def propose(self, _context) -> EngagementBrainProposal:  # noqa: ANN001
        return self._proposal


def _build_triage_service(campaign_manager, conversation_manager, engagement_store):  # noqa: ANN001
    return CheapInboundTriageService(
        EngagementBrainContextBuilder(campaign_manager, conversation_manager, engagement_store),
        conversation_manager,
    )


def test_conversation_review_claims_one_inbound_moment_once_until_new_inbound(tmp_path) -> None:
    manager = ExternalConversationManager(tmp_path / "campaigns")
    manager.save(
        ExternalConversationRecord(
            conversation_id="conv-inbound-1",
            campaign_id="cmp-1",
            account_id="reader-1",
            peer_id="user-42",
            chat_id="user-42",
            thread_origin=ThreadOrigin.DIRECT_INBOUND_DM,
            consent_posture=ConsentPosture.INBOUND_ONLY,
            status=ExternalConversationStatus.ACTIVE,
            external_user_messaged_first=True,
            last_event_id="evt-1",
            last_inbound_at=datetime(2026, 5, 24, 12, 0, tzinfo=UTC),
            next_action_type="review_inbound",
            next_action_reason="Fresh inbound needs review.",
        )
    )

    claimed = manager.claim_next_review(
        owner_id="worker-review-1",
        claim_ttl_seconds=300,
        now=datetime(2026, 5, 24, 12, 1, tzinfo=UTC),
    )

    assert claimed is not None
    assert claimed.trigger_type is ConversationReviewTriggerType.INBOUND
    assert claimed.trigger_key == "inbound:evt-1"
    assert manager.claim_next_review(
        owner_id="worker-review-2",
        claim_ttl_seconds=300,
        now=datetime(2026, 5, 24, 12, 2, tzinfo=UTC),
    ) is None

    completed = manager.complete_review_claim(
        "cmp-1",
        "conv-inbound-1",
        trigger=claimed,
        disposition="no_action",
        summary="Nothing to send.",
    )
    assert completed is not None
    assert completed.last_completed_review_trigger_key == "inbound:evt-1"
    assert completed.review_claimed_by == ""
    assert manager.claim_next_review(
        owner_id="worker-review-3",
        claim_ttl_seconds=300,
        now=datetime(2026, 5, 24, 12, 3, tzinfo=UTC),
    ) is None

    completed.last_event_id = "evt-2"
    completed.last_inbound_at = datetime(2026, 5, 24, 12, 4, tzinfo=UTC)
    completed.next_action_type = "review_inbound"
    manager.save(completed)

    claimed_again = manager.claim_next_review(
        owner_id="worker-review-4",
        claim_ttl_seconds=300,
        now=datetime(2026, 5, 24, 12, 5, tzinfo=UTC),
    )

    assert claimed_again is not None
    assert claimed_again.trigger_key == "inbound:evt-2"


def test_conversation_review_dispatcher_enqueues_due_follow_up_without_clearing_window(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    campaign_manager = CampaignManager(campaigns_root)
    campaign_manager.ensure_campaign(
        "operator-1",
        campaign_id="cmp-1",
        workspace_path=str(campaigns_root / "cmp-1"),
    )
    conversation_manager = ExternalConversationManager(campaigns_root)
    conversation_manager.save(
        ExternalConversationRecord(
            conversation_id="conv-group-follow-up",
            campaign_id="cmp-1",
            account_id="reader-1",
            peer_id="member-9",
            chat_id="-100123",
            community_id="-100123",
            thread_origin=ThreadOrigin.GROUP_REPLY,
            consent_posture=ConsentPosture.GROUP_CONTEXT_ONLY,
            status=ExternalConversationStatus.ACTIVE,
            reply_target_message_id="777",
            last_event_id="evt-group-1",
            follow_up_due_at=datetime(2026, 5, 24, 11, 0, tzinfo=UTC),
            follow_up_window_type=FollowUpWindowType.GROUP_FOLLOW_UP,
            next_action_type="scheduled_group_follow_up_window",
            next_action_reason="Review this group thread for a follow-up.",
        )
    )
    engagement_store = ManagedAccountEngagementStore(tmp_path)
    coordinator = EngagementBrainCoordinator(
        EngagementBrainContextBuilder(campaign_manager, conversation_manager, engagement_store),
        conversation_manager,
        LiveExecutionService(
            LiveExecutionManager(campaigns_root),
            conversation_manager=conversation_manager,
            campaign_manager=campaign_manager,
            worker_id="worker-live-queue",
        ),
        _build_autonomous_send_service(campaigns_root, group_reply_allowed=True),
        brain_service=FakeBrainService(
            EngagementBrainProposal(
                decision=EngagementBrainDecision.REPLY,
                action_type=EngagementBrainActionType.SEND_GROUP_REPLY,
                draft_text="Circling back with one more thought.",
                goal="follow_up_interest",
            )
        ),
    )
    dispatcher = ConversationReviewDispatcher(
        conversation_manager,
        coordinator,
        worker_id="worker-review-dispatch",
        claim_ttl_seconds=300,
    )

    outcome = dispatcher.dispatch_next_review(now=datetime(2026, 5, 24, 12, 0, tzinfo=UTC))

    assert outcome is not None
    assert outcome.status == "completed"
    assert outcome.run_result is not None
    assert outcome.run_result.disposition is EngagementBrainRunDisposition.ENQUEUED

    updated_conversation = conversation_manager.get("cmp-1", "conv-group-follow-up")
    queued_actions = LiveExecutionManager(campaigns_root).list_for_campaign("cmp-1")

    assert updated_conversation is not None
    assert updated_conversation.follow_up_due_at == datetime(2026, 5, 24, 11, 0, tzinfo=UTC)
    assert updated_conversation.review_claimed_by == ""
    assert updated_conversation.last_completed_review_disposition == "enqueued"
    assert len(queued_actions) == 1
    assert queued_actions[0].action_type is LiveActionType.SEND_GROUP_REPLY
    assert queued_actions[0].payload["approval_context"]["review_trigger"]["trigger_type"] == "follow_up_due"


def test_conversation_review_dispatcher_clears_due_window_after_no_action(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    campaign_manager = CampaignManager(campaigns_root)
    campaign_manager.ensure_campaign(
        "operator-1",
        campaign_id="cmp-1",
        workspace_path=str(campaigns_root / "cmp-1"),
    )
    conversation_manager = ExternalConversationManager(campaigns_root)
    conversation_manager.save(
        ExternalConversationRecord(
            conversation_id="conv-dm-follow-up",
            campaign_id="cmp-1",
            account_id="reader-1",
            peer_id="user-42",
            chat_id="user-42",
            thread_origin=ThreadOrigin.DIRECT_INBOUND_DM,
            consent_posture=ConsentPosture.INBOUND_ONLY,
            status=ExternalConversationStatus.ACTIVE,
            external_user_messaged_first=True,
            last_event_id="evt-dm-1",
            follow_up_due_at=datetime(2026, 5, 24, 11, 0, tzinfo=UTC),
            follow_up_window_type=FollowUpWindowType.DM_FOLLOW_UP,
            next_action_type="scheduled_dm_follow_up_window",
            next_action_reason="Review this DM thread for a follow-up.",
        )
    )
    engagement_store = ManagedAccountEngagementStore(tmp_path)
    coordinator = EngagementBrainCoordinator(
        EngagementBrainContextBuilder(campaign_manager, conversation_manager, engagement_store),
        conversation_manager,
        LiveExecutionService(
            LiveExecutionManager(campaigns_root),
            conversation_manager=conversation_manager,
            campaign_manager=campaign_manager,
            worker_id="worker-live-ignore",
        ),
        _build_autonomous_send_service(campaigns_root),
        brain_service=FakeBrainService(
            EngagementBrainProposal(
                decision=EngagementBrainDecision.IGNORE,
                goal="leave_space",
            )
        ),
    )
    dispatcher = ConversationReviewDispatcher(
        conversation_manager,
        coordinator,
        worker_id="worker-review-ignore",
        claim_ttl_seconds=300,
    )

    outcome = dispatcher.dispatch_next_review(now=datetime(2026, 5, 24, 12, 0, tzinfo=UTC))

    assert outcome is not None
    assert outcome.run_result is not None
    assert outcome.run_result.disposition is EngagementBrainRunDisposition.NO_ACTION

    updated_conversation = conversation_manager.get("cmp-1", "conv-dm-follow-up")

    assert updated_conversation is not None
    assert updated_conversation.follow_up_due_at is None
    assert updated_conversation.follow_up_window_type is None
    assert updated_conversation.last_completed_review_disposition == "no_action"
    assert updated_conversation.last_completed_review_source == "scheduled_dm_follow_up_window"


def test_conversation_review_dispatcher_completes_low_signal_inbound_in_triage(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    campaign_manager = CampaignManager(campaigns_root)
    campaign_manager.ensure_campaign(
        "operator-1",
        campaign_id="cmp-1",
        workspace_path=str(campaigns_root / "cmp-1"),
    )
    conversation_manager = ExternalConversationManager(campaigns_root)
    conversation_manager.save(
        ExternalConversationRecord(
            conversation_id="conv-low-signal",
            campaign_id="cmp-1",
            account_id="reader-1",
            peer_id="user-42",
            chat_id="user-42",
            thread_origin=ThreadOrigin.DIRECT_INBOUND_DM,
            consent_posture=ConsentPosture.INBOUND_ONLY,
            status=ExternalConversationStatus.ACTIVE,
            external_user_messaged_first=True,
            last_event_id="evt-low-1",
            last_inbound_at=datetime(2026, 5, 24, 12, 0, tzinfo=UTC),
            next_action_type="review_inbound",
            next_action_reason="Fresh inbound needs review.",
            recent_message_refs=["event:evt-low-1"],
        )
    )
    engagement_store = ManagedAccountEngagementStore(tmp_path)
    engagement_store.append_inbound_event(
        EngagementEventRecord(
            event_id="evt-low-1",
            dedupe_key="dedupe-low-1",
            account_id="reader-1",
            event_kind=EngagementEventKind.INBOUND_DM,
            chat_id="user-42",
            peer_id="user-42",
            sender_id="user-42",
            message_id="401",
            text="ok thanks",
            occurred_at=datetime(2026, 5, 24, 12, 0, tzinfo=UTC),
            campaign_id="cmp-1",
            routing_status=EngagementRoutingStatus.ROUTED,
        )
    )
    coordinator = EngagementBrainCoordinator(
        EngagementBrainContextBuilder(campaign_manager, conversation_manager, engagement_store),
        conversation_manager,
        LiveExecutionService(
            LiveExecutionManager(campaigns_root),
            conversation_manager=conversation_manager,
            campaign_manager=campaign_manager,
            worker_id="worker-live-low-signal",
        ),
        _build_autonomous_send_service(campaigns_root, dm_reply_allowed=True),
        brain_service=FakeBrainService(
            EngagementBrainProposal(
                decision=EngagementBrainDecision.REPLY,
                action_type=EngagementBrainActionType.SEND_DM_REPLY,
                draft_text="This should never queue.",
                goal="should_not_run",
            )
        ),
    )
    dispatcher = ConversationReviewDispatcher(
        conversation_manager,
        coordinator,
        triage_service=_build_triage_service(campaign_manager, conversation_manager, engagement_store),
        worker_id="worker-review-triage",
        claim_ttl_seconds=300,
    )

    outcome = dispatcher.dispatch_next_review(now=datetime(2026, 5, 24, 12, 1, tzinfo=UTC))

    updated_conversation = conversation_manager.get("cmp-1", "conv-low-signal")
    queued_actions = LiveExecutionManager(campaigns_root).list_for_campaign("cmp-1")

    assert outcome is not None
    assert outcome.status == "completed"
    assert outcome.triage_result is not None
    assert outcome.run_result is None
    assert updated_conversation is not None
    assert updated_conversation.last_completed_review_disposition == "triage_complete"
    assert updated_conversation.triage_state.low_signal_chatter is True
    assert (
        updated_conversation.triage_state.promotion_decision
        is TriagePromotionDecision.COMPLETE_IN_TRIAGE
    )
    assert queued_actions == []


def test_conversation_review_dispatcher_promotes_thread_before_deep_review(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    campaign_manager = CampaignManager(campaigns_root)
    campaign_manager.ensure_campaign(
        "operator-1",
        campaign_id="cmp-1",
        workspace_path=str(campaigns_root / "cmp-1"),
    )
    conversation_manager = ExternalConversationManager(campaigns_root)
    conversation_manager.save(
        ExternalConversationRecord(
            conversation_id="conv-promote",
            campaign_id="cmp-1",
            account_id="reader-1",
            peer_id="user-42",
            chat_id="user-42",
            thread_origin=ThreadOrigin.DIRECT_INBOUND_DM,
            consent_posture=ConsentPosture.INBOUND_ONLY,
            status=ExternalConversationStatus.ACTIVE,
            external_user_messaged_first=True,
            last_event_id="evt-promote-1",
            last_inbound_at=datetime(2026, 5, 24, 12, 0, tzinfo=UTC),
            next_action_type="review_inbound",
            next_action_reason="Fresh inbound needs review.",
            recent_message_refs=["event:evt-promote-1"],
        )
    )
    engagement_store = ManagedAccountEngagementStore(tmp_path)
    engagement_store.append_inbound_event(
        EngagementEventRecord(
            event_id="evt-promote-1",
            dedupe_key="dedupe-promote-1",
            account_id="reader-1",
            event_kind=EngagementEventKind.INBOUND_DM,
            chat_id="user-42",
            peer_id="user-42",
            sender_id="user-42",
            message_id="402",
            text="Can you send pricing details today? I am interested.",
            occurred_at=datetime(2026, 5, 24, 12, 0, tzinfo=UTC),
            campaign_id="cmp-1",
            routing_status=EngagementRoutingStatus.ROUTED,
        )
    )
    coordinator = EngagementBrainCoordinator(
        EngagementBrainContextBuilder(campaign_manager, conversation_manager, engagement_store),
        conversation_manager,
        LiveExecutionService(
            LiveExecutionManager(campaigns_root),
            conversation_manager=conversation_manager,
            campaign_manager=campaign_manager,
            worker_id="worker-live-promote",
        ),
        _build_autonomous_send_service(campaigns_root, dm_reply_allowed=True),
        brain_service=FakeBrainService(
            EngagementBrainProposal(
                decision=EngagementBrainDecision.REPLY,
                action_type=EngagementBrainActionType.SEND_DM_REPLY,
                draft_text="Happy to share pricing details here.",
                goal="answer_interest",
            )
        ),
    )
    dispatcher = ConversationReviewDispatcher(
        conversation_manager,
        coordinator,
        triage_service=_build_triage_service(campaign_manager, conversation_manager, engagement_store),
        worker_id="worker-review-promote",
        claim_ttl_seconds=300,
    )

    outcome = dispatcher.dispatch_next_review(now=datetime(2026, 5, 24, 12, 1, tzinfo=UTC))

    updated_conversation = conversation_manager.get("cmp-1", "conv-promote")
    queued_actions = LiveExecutionManager(campaigns_root).list_for_campaign("cmp-1")

    assert outcome is not None
    assert outcome.status == "completed"
    assert outcome.triage_result is not None
    assert outcome.run_result is not None
    assert outcome.run_result.disposition is EngagementBrainRunDisposition.ENQUEUED
    assert updated_conversation is not None
    assert (
        updated_conversation.triage_state.promotion_decision
        is TriagePromotionDecision.PROMOTE_TO_DEEP_REVIEW
    )
    assert updated_conversation.triage_state.promoted_to_deep_review is True
    assert updated_conversation.last_completed_review_disposition == "enqueued"
    assert len(queued_actions) == 1
    assert queued_actions[0].action_type is LiveActionType.SEND_DM_REPLY
