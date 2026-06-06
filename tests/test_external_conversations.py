from __future__ import annotations

from datetime import UTC, datetime

from telegram_app.campaign_signals import (
    CampaignSignalBridge,
    CampaignSignalManager,
    ObservationWorkRefresher,
)
from telegram_app.engagement import EngagementEventKind, EngagementEventRecord, EngagementRoutingStatus
from telegram_app.external_conversations import (
    ConversationBeliefState,
    ConsentPosture,
    ExternalConversationManager,
    ExternalConversationRecord,
    ExternalConversationProjector,
    ExternalConversationStatus,
    ThreadOrigin,
)
from telegram_app.work_items import WorkItemManager


def test_projector_creates_group_reply_thread_from_routed_event(tmp_path) -> None:
    manager = ExternalConversationManager(tmp_path / "campaigns")
    projector = ExternalConversationProjector(manager)
    event = EngagementEventRecord(
        event_id="evt-1",
        dedupe_key="dedupe-1",
        account_id="reader-1",
        event_kind=EngagementEventKind.GROUP_REPLY,
        chat_id="-100123",
        peer_id="member-9",
        sender_id="member-9",
        message_id="778",
        reply_to_message_id="777",
        text="replying to your post",
        occurred_at=datetime(2026, 5, 23, 12, 5, tzinfo=UTC),
        campaign_id="cmp-1",
        community_id="-100123",
        routing_status=EngagementRoutingStatus.ROUTED,
    )

    conversation = projector.project_inbound_event(event)
    reloaded = manager.get("cmp-1", conversation.conversation_id if conversation else "")
    by_peer = manager.find_by_account_peer("cmp-1", account_id="reader-1", peer_id="member-9")
    by_thread = manager.find_group_reply_thread(
        "cmp-1",
        account_id="reader-1",
        chat_id="-100123",
        reply_target_message_id="777",
    )

    assert conversation is not None
    assert conversation.thread_origin is ThreadOrigin.GROUP_REPLY
    assert conversation.status is ExternalConversationStatus.ACTIVE
    assert conversation.consent_posture is ConsentPosture.GROUP_CONTEXT_ONLY
    assert conversation.last_inbound_message_id == "778"
    assert conversation.reply_target_message_id == "777"
    assert conversation.last_event_id == "evt-1"
    assert conversation.summary.startswith("Group reply thread")
    assert reloaded is not None
    assert by_peer is not None
    assert by_thread is not None
    assert by_thread.conversation_id == conversation.conversation_id


def test_projector_is_idempotent_for_replayed_event(tmp_path) -> None:
    manager = ExternalConversationManager(tmp_path / "campaigns")
    projector = ExternalConversationProjector(manager)
    event = EngagementEventRecord(
        event_id="evt-1",
        dedupe_key="dedupe-1",
        account_id="reader-1",
        event_kind=EngagementEventKind.GROUP_REPLY,
        chat_id="-100123",
        peer_id="member-9",
        sender_id="member-9",
        message_id="778",
        reply_to_message_id="777",
        text="replying to your post",
        occurred_at=datetime(2026, 5, 23, 12, 5, tzinfo=UTC),
        campaign_id="cmp-1",
        community_id="-100123",
        routing_status=EngagementRoutingStatus.ROUTED,
    )

    first = projector.project_inbound_event(event)
    reloaded_projector = ExternalConversationProjector(ExternalConversationManager(tmp_path / "campaigns"))
    second = reloaded_projector.project_inbound_event(event)
    conversations = manager.list_for_campaign("cmp-1")

    assert first is not None
    assert second is not None
    assert second.conversation_id == first.conversation_id
    assert len(conversations) == 1
    assert conversations[0].recent_message_refs == [f"event:{event.event_id}"]


def test_projector_creates_direct_dm_thread_when_campaign_is_known(tmp_path) -> None:
    manager = ExternalConversationManager(tmp_path / "campaigns")
    projector = ExternalConversationProjector(manager)
    event = EngagementEventRecord(
        event_id="evt-dm-1",
        dedupe_key="dedupe-dm-1",
        account_id="reader-1",
        event_kind=EngagementEventKind.INBOUND_DM,
        chat_id="user-42",
        peer_id="user-42",
        sender_id="user-42",
        message_id="401",
        text="hello from a DM",
        occurred_at=datetime(2026, 5, 23, 12, 0, tzinfo=UTC),
        campaign_id="cmp-1",
        routing_status=EngagementRoutingStatus.ROUTED,
    )

    conversation = projector.project_inbound_event(event)
    by_peer = manager.find_by_account_peer("cmp-1", account_id="reader-1", peer_id="user-42")

    assert conversation is not None
    assert conversation.thread_origin is ThreadOrigin.DIRECT_INBOUND_DM
    assert conversation.consent_posture is ConsentPosture.INBOUND_ONLY
    assert conversation.external_user_messaged_first is True
    assert conversation.last_inbound_message_id == "401"
    assert by_peer is not None
    assert by_peer.conversation_id == conversation.conversation_id


def test_projector_preserves_paused_status_on_new_inbound_event(tmp_path) -> None:
    manager = ExternalConversationManager(tmp_path / "campaigns")
    projector = ExternalConversationProjector(manager)
    first_event = EngagementEventRecord(
        event_id="evt-dm-1",
        dedupe_key="dedupe-dm-1",
        account_id="reader-1",
        event_kind=EngagementEventKind.INBOUND_DM,
        chat_id="user-42",
        peer_id="user-42",
        sender_id="user-42",
        message_id="401",
        text="hello from a DM",
        occurred_at=datetime(2026, 5, 23, 12, 0, tzinfo=UTC),
        campaign_id="cmp-1",
        routing_status=EngagementRoutingStatus.ROUTED,
    )
    conversation = projector.project_inbound_event(first_event)
    assert conversation is not None

    conversation.status = ExternalConversationStatus.PAUSED
    conversation.operator_hold_reason = "operator_pause"
    manager.save(conversation)

    follow_up_event = EngagementEventRecord(
        event_id="evt-dm-2",
        dedupe_key="dedupe-dm-2",
        account_id="reader-1",
        event_kind=EngagementEventKind.INBOUND_DM,
        chat_id="user-42",
        peer_id="user-42",
        sender_id="user-42",
        message_id="402",
        text="checking back in",
        occurred_at=datetime(2026, 5, 23, 12, 10, tzinfo=UTC),
        campaign_id="cmp-1",
        routing_status=EngagementRoutingStatus.ROUTED,
    )

    refreshed = projector.project_inbound_event(follow_up_event)

    assert refreshed is not None
    assert refreshed.status is ExternalConversationStatus.PAUSED
    assert refreshed.operator_hold_reason == "operator_pause"
    assert refreshed.last_inbound_message_id == "402"


def test_projector_emits_signal_for_repeated_group_reply_pressure(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    manager = ExternalConversationManager(campaigns_root)
    signal_manager = CampaignSignalManager(campaigns_root)
    work_item_manager = WorkItemManager(campaigns_root)
    projector = ExternalConversationProjector(
        manager,
        signal_bridge=CampaignSignalBridge(
            signal_manager,
            observation_work_refresher=ObservationWorkRefresher(signal_manager, work_item_manager),
        ),
    )
    first_event = EngagementEventRecord(
        event_id="evt-repeat-1",
        dedupe_key="dedupe-repeat-1",
        account_id="reader-1",
        event_kind=EngagementEventKind.GROUP_REPLY,
        chat_id="-100123",
        peer_id="member-9",
        sender_id="member-9",
        message_id="778",
        reply_to_message_id="777",
        text="first reply to your post",
        occurred_at=datetime(2026, 5, 23, 12, 5, tzinfo=UTC),
        campaign_id="cmp-1",
        community_id="-100123",
        routing_status=EngagementRoutingStatus.ROUTED,
    )
    second_event = EngagementEventRecord(
        event_id="evt-repeat-2",
        dedupe_key="dedupe-repeat-2",
        account_id="reader-1",
        event_kind=EngagementEventKind.GROUP_REPLY,
        chat_id="-100123",
        peer_id="member-9",
        sender_id="member-9",
        message_id="779",
        reply_to_message_id="777",
        text="following up again on that post",
        occurred_at=datetime(2026, 5, 23, 12, 7, tzinfo=UTC),
        campaign_id="cmp-1",
        community_id="-100123",
        routing_status=EngagementRoutingStatus.ROUTED,
    )

    first = projector.project_inbound_event(first_event)
    second = projector.project_inbound_event(second_event)
    signals = signal_manager.list_for_campaign("cmp-1")
    observation_item = work_item_manager.find_latest("cmp-1", work_type="observation")

    assert first is not None
    assert second is not None
    assert len(signals) == 1
    assert signals[0].signal_type == "conversation_high_intent_shift"
    assert signals[0].conversation_id == second.conversation_id
    assert signals[0].summary.startswith(f"Conversation `{second.conversation_id}` received repeated inbound")
    assert observation_item is not None
    assert observation_item.refresh_reason == signals[0].summary


def test_projector_emits_signal_when_paused_conversation_receives_inbound(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    manager = ExternalConversationManager(campaigns_root)
    signal_manager = CampaignSignalManager(campaigns_root)
    work_item_manager = WorkItemManager(campaigns_root)
    projector = ExternalConversationProjector(
        manager,
        signal_bridge=CampaignSignalBridge(
            signal_manager,
            observation_work_refresher=ObservationWorkRefresher(signal_manager, work_item_manager),
        ),
    )
    first_event = EngagementEventRecord(
        event_id="evt-paused-1",
        dedupe_key="dedupe-paused-1",
        account_id="reader-1",
        event_kind=EngagementEventKind.GROUP_REPLY,
        chat_id="-100123",
        peer_id="member-9",
        sender_id="member-9",
        message_id="778",
        reply_to_message_id="777",
        text="first reply to your post",
        occurred_at=datetime(2026, 5, 23, 12, 5, tzinfo=UTC),
        campaign_id="cmp-1",
        community_id="-100123",
        routing_status=EngagementRoutingStatus.ROUTED,
    )

    created = projector.project_inbound_event(first_event)
    assert created is not None
    manager.update_status(
        "cmp-1",
        created.conversation_id,
        status=ExternalConversationStatus.PAUSED,
        operator_hold_reason="operator_pause",
        status_reason="Waiting for manual review before replying again.",
        next_action_type="operator_review",
        next_action_reason="Paused for manual review.",
    )

    follow_up_event = EngagementEventRecord(
        event_id="evt-paused-2",
        dedupe_key="dedupe-paused-2",
        account_id="reader-1",
        event_kind=EngagementEventKind.GROUP_REPLY,
        chat_id="-100123",
        peer_id="member-9",
        sender_id="member-9",
        message_id="779",
        reply_to_message_id="777",
        text="checking back in while paused",
        occurred_at=datetime(2026, 5, 23, 12, 10, tzinfo=UTC),
        campaign_id="cmp-1",
        community_id="-100123",
        routing_status=EngagementRoutingStatus.ROUTED,
    )

    refreshed = projector.project_inbound_event(follow_up_event)
    signals = signal_manager.list_for_campaign("cmp-1")

    assert refreshed is not None
    assert len(signals) == 1
    assert signals[0].signal_type == "conversation_escalated"
    assert "received new inbound while it remained `paused`" in signals[0].summary
    assert "Waiting for manual review before replying again." in signals[0].summary


def test_manager_records_outbound_delivery_and_outbound_lookup(tmp_path) -> None:
    manager = ExternalConversationManager(tmp_path / "campaigns")
    conversation = manager.save(
        ExternalConversationRecord(
            conversation_id="conv-1",
            campaign_id="cmp-1",
            account_id="reader-1",
            peer_id="user-42",
            chat_id="user-42",
            thread_origin=ThreadOrigin.DIRECT_INBOUND_DM,
            consent_posture=ConsentPosture.INBOUND_ONLY,
            status=ExternalConversationStatus.ACTIVE,
            external_user_messaged_first=True,
        )
    )

    updated = manager.record_outbound_delivery(
        "cmp-1",
        conversation.conversation_id,
        message_id="501",
        sent_at=datetime(2026, 5, 23, 12, 30, tzinfo=UTC),
    )
    by_outbound_message = manager.find_by_outbound_message(
        "cmp-1",
        account_id="reader-1",
        chat_id="user-42",
        message_id="501",
    )

    assert updated is not None
    assert updated.status is ExternalConversationStatus.ACTIVE
    assert updated.last_outbound_message_id == "501"
    assert updated.next_action_type == "wait_for_inbound"
    assert "outbound:501" in updated.recent_message_refs
    assert by_outbound_message is not None
    assert by_outbound_message.conversation_id == conversation.conversation_id


def test_manager_persists_status_reason_on_status_updates(tmp_path) -> None:
    manager = ExternalConversationManager(tmp_path / "campaigns")
    conversation = manager.save(
        ExternalConversationRecord(
            conversation_id="conv-status-reason",
            campaign_id="cmp-1",
            account_id="reader-1",
            peer_id="user-42",
            chat_id="user-42",
            thread_origin=ThreadOrigin.DIRECT_INBOUND_DM,
            consent_posture=ConsentPosture.INBOUND_ONLY,
            status=ExternalConversationStatus.ACTIVE,
            external_user_messaged_first=True,
        )
    )

    updated = manager.update_status(
        "cmp-1",
        conversation.conversation_id,
        status=ExternalConversationStatus.PAUSED,
        operator_hold_reason="operator_pause",
        status_reason="policy asked the runtime to wait for manual review",
        next_action_type="operator_review",
        next_action_reason="Conversation is paused.",
    )
    reloaded = manager.get("cmp-1", conversation.conversation_id)

    assert updated is not None
    assert updated.status_reason == "policy asked the runtime to wait for manual review"
    assert reloaded is not None
    assert reloaded.status_reason == "policy asked the runtime to wait for manual review"


def test_manager_persists_nested_belief_state(tmp_path) -> None:
    manager = ExternalConversationManager(tmp_path / "campaigns")
    conversation = manager.save(
        ExternalConversationRecord(
            conversation_id="conv-belief-state",
            campaign_id="cmp-1",
            account_id="reader-1",
            peer_id="user-42",
            chat_id="user-42",
            thread_origin=ThreadOrigin.DIRECT_INBOUND_DM,
            consent_posture=ConsentPosture.INBOUND_ONLY,
            status=ExternalConversationStatus.ACTIVE,
            external_user_messaged_first=True,
            belief_state=ConversationBeliefState(
                intent_posture="evaluating_fit",
                known_fit_signals=["asked about pricing"],
                unanswered_questions=["What pricing details are approved for this conversation?"],
                commercial_stage="potential_fit",
                last_meaningful_shift="Conversation shows potential fit.",
                suggested_next_move="Ask one grounded question to confirm fit and buying intent.",
            ),
        )
    )

    reloaded = manager.get("cmp-1", conversation.conversation_id)

    assert reloaded is not None
    assert reloaded.belief_state.intent_posture == "evaluating_fit"
    assert reloaded.belief_state.known_fit_signals == ["asked about pricing"]
    assert reloaded.belief_state.commercial_stage == "potential_fit"
