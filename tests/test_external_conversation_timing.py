from __future__ import annotations

from datetime import UTC, datetime

from telegram_app.campaigns import CampaignManager
from telegram_app.engagement_policy import CampaignEngagementPolicy, CampaignEngagementPolicyManager, CampaignEngagementPolicyService, QuietHoursPolicy
from telegram_app.engagement import EngagementEventKind, EngagementEventRecord, EngagementRoutingStatus
from telegram_app.external_conversations import (
    ConsentPosture,
    ExternalConversationManager,
    ExternalConversationProjector,
    ExternalConversationRecord,
    ExternalConversationStatus,
    ExternalConversationTimingService,
    FollowUpTimingPolicy,
    FollowUpWindowType,
    ThreadOrigin,
)


class SequenceSampler:
    def __init__(self, *values: int) -> None:
        self._values = list(values)

    def __call__(self, minimum_value: int, maximum_value: int) -> int:
        if not self._values:
            raise AssertionError("No sampler value remained for this test call.")
        value = self._values.pop(0)
        assert minimum_value <= value <= maximum_value
        return value


def test_group_follow_up_is_shifted_out_of_cet_quiet_hours(tmp_path) -> None:
    manager = ExternalConversationManager(tmp_path / "campaigns")
    conversation = manager.save(
        ExternalConversationRecord(
            conversation_id="conv-group-quiet-hours",
            campaign_id="cmp-1",
            account_id="reader-1",
            peer_id="member-9",
            chat_id="-100123",
            community_id="-100123",
            thread_origin=ThreadOrigin.GROUP_REPLY,
            consent_posture=ConsentPosture.GROUP_CONTEXT_ONLY,
            status=ExternalConversationStatus.ACTIVE,
        )
    )
    timing_service = ExternalConversationTimingService(
        manager,
        policy=FollowUpTimingPolicy(sample_int=SequenceSampler(24 * 3600, 23)),
    )

    scheduled = timing_service.schedule_group_follow_up(
        "cmp-1",
        conversation.conversation_id,
        silence_started_at=datetime(2026, 5, 22, 0, 40, tzinfo=UTC),
    )

    assert scheduled is not None
    assert scheduled.follow_up_window_type is FollowUpWindowType.GROUP_FOLLOW_UP
    assert scheduled.follow_up_due_at == datetime(2026, 5, 23, 7, 23, tzinfo=UTC)
    assert scheduled.quiet_hours_profile == "cet_0000_0800"
    assert scheduled.next_action_type == "scheduled_group_follow_up_window"


def test_group_follow_up_schedule_is_persisted_once_until_consumed(tmp_path) -> None:
    manager = ExternalConversationManager(tmp_path / "campaigns")
    conversation = manager.save(
        ExternalConversationRecord(
            conversation_id="conv-group-persisted",
            campaign_id="cmp-1",
            account_id="reader-1",
            peer_id="member-9",
            chat_id="-100123",
            community_id="-100123",
            thread_origin=ThreadOrigin.GROUP_REPLY,
            consent_posture=ConsentPosture.GROUP_CONTEXT_ONLY,
            status=ExternalConversationStatus.ACTIVE,
        )
    )
    timing_service = ExternalConversationTimingService(
        manager,
        policy=FollowUpTimingPolicy(sample_int=SequenceSampler(24 * 3600, 24 * 3600 + 600)),
    )

    first = timing_service.schedule_group_follow_up(
        "cmp-1",
        conversation.conversation_id,
        silence_started_at=datetime(2026, 5, 22, 12, 0, tzinfo=UTC),
    )
    second = timing_service.schedule_group_follow_up(
        "cmp-1",
        conversation.conversation_id,
        silence_started_at=datetime(2026, 5, 22, 14, 0, tzinfo=UTC),
    )

    assert first is not None
    assert second is not None
    assert second.follow_up_due_at == first.follow_up_due_at
    assert timing_service.is_follow_up_due(
        "cmp-1",
        conversation.conversation_id,
        now=datetime(2026, 5, 23, 11, 59, tzinfo=UTC),
    ) is False
    assert timing_service.is_follow_up_due(
        "cmp-1",
        conversation.conversation_id,
        now=datetime(2026, 5, 23, 12, 0, tzinfo=UTC),
    ) is True


def test_dm_follow_up_is_limited_to_one_autonomous_window_per_cycle(tmp_path) -> None:
    manager = ExternalConversationManager(tmp_path / "campaigns")
    conversation = manager.save(
        ExternalConversationRecord(
            conversation_id="conv-dm-limit",
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
    timing_service = ExternalConversationTimingService(
        manager,
        policy=FollowUpTimingPolicy(sample_int=SequenceSampler(24 * 3600)),
    )

    scheduled = timing_service.schedule_dm_follow_up(
        "cmp-1",
        conversation.conversation_id,
        silence_started_at=datetime(2026, 5, 22, 12, 0, tzinfo=UTC),
    )
    consumed = timing_service.mark_follow_up_sent("cmp-1", conversation.conversation_id)
    rescheduled = timing_service.schedule_dm_follow_up(
        "cmp-1",
        conversation.conversation_id,
        silence_started_at=datetime(2026, 5, 24, 12, 0, tzinfo=UTC),
    )

    assert scheduled is not None
    assert scheduled.follow_up_window_type is FollowUpWindowType.DM_FOLLOW_UP
    assert consumed is not None
    assert consumed.follow_up_attempt_count == 1
    assert consumed.follow_up_due_at is None
    assert rescheduled is not None
    assert rescheduled.follow_up_attempt_count == 1
    assert rescheduled.follow_up_due_at is None


def test_inbound_event_clears_pending_follow_up_and_resets_attempt_count(tmp_path) -> None:
    manager = ExternalConversationManager(tmp_path / "campaigns")
    timing_service = ExternalConversationTimingService(
        manager,
        policy=FollowUpTimingPolicy(sample_int=SequenceSampler(24 * 3600)),
    )
    projector = ExternalConversationProjector(manager)
    conversation = manager.save(
        ExternalConversationRecord(
            conversation_id="conv-dm-reset",
            campaign_id="cmp-1",
            account_id="reader-1",
            peer_id="user-42",
            chat_id="user-42",
            thread_origin=ThreadOrigin.DIRECT_INBOUND_DM,
            consent_posture=ConsentPosture.INBOUND_ONLY,
            status=ExternalConversationStatus.ACTIVE,
            external_user_messaged_first=True,
            follow_up_attempt_count=1,
        )
    )
    scheduled = timing_service.schedule_dm_follow_up(
        "cmp-1",
        conversation.conversation_id,
        silence_started_at=datetime(2026, 5, 22, 12, 0, tzinfo=UTC),
    )
    assert scheduled is not None

    refreshed = projector.project_inbound_event(
        EngagementEventRecord(
            event_id="evt-dm-reset",
            dedupe_key="dedupe-dm-reset",
            account_id="reader-1",
            event_kind=EngagementEventKind.INBOUND_DM,
            chat_id="user-42",
            peer_id="user-42",
            sender_id="user-42",
            message_id="901",
            text="checking back in",
            occurred_at=datetime(2026, 5, 23, 15, 0, tzinfo=UTC),
            campaign_id="cmp-1",
            routing_status=EngagementRoutingStatus.ROUTED,
        )
    )

    assert refreshed is not None
    assert refreshed.follow_up_due_at is None
    assert refreshed.follow_up_window_type is None
    assert refreshed.follow_up_attempt_count == 0
    assert refreshed.next_action_type == "review_inbound"


def test_group_follow_up_uses_campaign_quiet_hours_profile(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    CampaignManager(campaigns_root).ensure_campaign(
        "operator-1",
        campaign_id="cmp-1",
        workspace_path=str(campaigns_root / "cmp-1"),
    )
    manager = ExternalConversationManager(campaigns_root)
    conversation = manager.save(
        ExternalConversationRecord(
            conversation_id="conv-group-nyc-quiet-hours",
            campaign_id="cmp-1",
            account_id="reader-1",
            peer_id="member-9",
            chat_id="-100123",
            community_id="-100123",
            thread_origin=ThreadOrigin.GROUP_REPLY,
            consent_posture=ConsentPosture.GROUP_CONTEXT_ONLY,
            status=ExternalConversationStatus.ACTIVE,
        )
    )
    policy_manager = CampaignEngagementPolicyManager(campaigns_root)
    policy_manager.save_policy(
        "cmp-1",
        CampaignEngagementPolicy(
            quiet_hours=QuietHoursPolicy(
                timezone_name="America/New_York",
                start_hour=0,
                end_hour=8,
                wakeup_min_delay_seconds=600,
                wakeup_max_delay_seconds=600,
            )
        ),
    )
    timing_service = ExternalConversationTimingService(
        manager,
        policy=FollowUpTimingPolicy(sample_int=SequenceSampler(24 * 3600, 600)),
        engagement_policy_service=CampaignEngagementPolicyService(policy_manager),
    )

    scheduled = timing_service.schedule_group_follow_up(
        "cmp-1",
        conversation.conversation_id,
        silence_started_at=datetime(2026, 5, 22, 10, 30, tzinfo=UTC),
    )

    assert scheduled is not None
    assert scheduled.follow_up_due_at == datetime(2026, 5, 23, 12, 10, tzinfo=UTC)
    assert scheduled.quiet_hours_profile == "america_new_york_0000_0800"
