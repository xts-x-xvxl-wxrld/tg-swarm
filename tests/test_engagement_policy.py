from __future__ import annotations

from datetime import UTC, datetime

from telegram_app.engagement_brain import (
    EngagementBrainActionType,
    EngagementBrainCommunityGuidance,
    EngagementBrainContext,
    EngagementBrainDecision,
    EngagementBrainProposal,
)
from telegram_app.engagement_policy import (
    CampaignEngagementPolicy,
    CampaignEngagementPolicyManager,
    CampaignEngagementPolicyService,
    CommunityBehaviorPolicy,
    QuietHoursPolicy,
    ReplyLatencyTier,
    ReplyTimingDecisionType,
)
from telegram_app.engagement_triage import ConversationTriageState
from telegram_app.external_conversations import (
    ConsentPosture,
    ConversationReviewTrigger,
    ConversationReviewTriggerType,
    ExternalConversationRecord,
    ExternalConversationStatus,
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


def _group_context() -> EngagementBrainContext:
    return EngagementBrainContext(
        conversation=ExternalConversationRecord(
            conversation_id="conv-group-policy",
            campaign_id="cmp-1",
            account_id="reader-1",
            peer_id="member-9",
            chat_id="-100123",
            community_id="-100123",
            thread_origin=ThreadOrigin.GROUP_REPLY,
            consent_posture=ConsentPosture.GROUP_CONTEXT_ONLY,
            status=ExternalConversationStatus.ACTIVE,
            reply_target_message_id="777",
        ),
        community_guidance=EngagementBrainCommunityGuidance(
            community_id="-100123",
            chat_id="-100123",
            community_type="crypto",
        ),
    )


def _dm_context(*, low_signal: bool = False, hostile: bool = False, follow_up_attempt_count: int = 0) -> EngagementBrainContext:
    return EngagementBrainContext(
        conversation=ExternalConversationRecord(
            conversation_id="conv-dm-policy",
            campaign_id="cmp-1",
            account_id="reader-1",
            peer_id="user-42",
            chat_id="user-42",
            thread_origin=ThreadOrigin.DIRECT_INBOUND_DM,
            consent_posture=ConsentPosture.INBOUND_ONLY,
            status=ExternalConversationStatus.ACTIVE,
            external_user_messaged_first=True,
            follow_up_attempt_count=follow_up_attempt_count,
            triage_state=ConversationTriageState(
                low_signal_chatter=low_signal,
                hostile_signal=hostile,
                objection_hints=["pricing_concern"] if low_signal else [],
            ),
        )
    )


def test_policy_service_delays_near_immediate_crypto_reply_out_of_campaign_quiet_hours(tmp_path) -> None:
    manager = CampaignEngagementPolicyManager(tmp_path / "campaigns")
    manager.save_policy(
        "cmp-1",
        CampaignEngagementPolicy(
            quiet_hours=QuietHoursPolicy(
                timezone_name="Europe/Budapest",
                start_hour=0,
                end_hour=8,
                wakeup_min_delay_seconds=300,
                wakeup_max_delay_seconds=300,
            ),
            community_type_defaults={
                "crypto": CommunityBehaviorPolicy(
                    reply_latency_tier=ReplyLatencyTier.NEAR_IMMEDIATE,
                    negative_signal_tolerance="high",
                )
            },
        ),
    )
    service = CampaignEngagementPolicyService(manager, sample_int=SequenceSampler(45, 300))

    decision = service.plan_reply(
        _group_context(),
        EngagementBrainProposal(
            decision=EngagementBrainDecision.REPLY,
            action_type=EngagementBrainActionType.SEND_GROUP_REPLY,
            draft_text="Interesting angle.",
            goal="advance_thread",
        ),
        now=datetime(2026, 5, 23, 22, 10, tzinfo=UTC),
    )

    assert decision.decision_type is ReplyTimingDecisionType.DELAY
    assert decision.latency_tier is ReplyLatencyTier.NEAR_IMMEDIATE
    assert decision.execute_at == datetime(2026, 5, 24, 6, 5, 0, tzinfo=UTC)
    assert decision.quiet_hours_profile == "europe_budapest_0000_0800"
    metrics = manager.get_metrics("cmp-1")
    assert metrics.decision_counts["delay"] == 1
    assert metrics.latency_tier_counts["near_immediate"] >= 1
    assert metrics.community_counts["-100123"]["delay"] == 1


def test_policy_service_suppresses_low_signal_dm_follow_up(tmp_path) -> None:
    manager = CampaignEngagementPolicyManager(tmp_path / "campaigns")
    service = CampaignEngagementPolicyService(manager)

    decision = service.plan_reply(
        _dm_context(low_signal=True, follow_up_attempt_count=1),
        EngagementBrainProposal(
            decision=EngagementBrainDecision.REPLY,
            action_type=EngagementBrainActionType.SEND_DM_REPLY,
            draft_text="Checking back in.",
            goal="follow_up_interest",
        ),
        trigger=ConversationReviewTrigger(
            campaign_id="cmp-1",
            conversation_id="conv-dm-policy",
            trigger_type=ConversationReviewTriggerType.FOLLOW_UP_DUE,
            trigger_source="scheduled_dm_follow_up_window",
            trigger_key="follow_up:dm_follow_up:2026-05-24T12:00:00+00:00:1",
            eligible_at=datetime(2026, 5, 24, 12, 0, tzinfo=UTC),
        ),
        now=datetime(2026, 5, 24, 12, 0, tzinfo=UTC),
    )

    assert decision.decision_type is ReplyTimingDecisionType.SUPPRESS
    assert decision.latency_tier is ReplyLatencyTier.NO_REPLY
    assert decision.suppression_reason == "low_signal_chatter"
    metrics = manager.get_metrics("cmp-1")
    assert metrics.decision_counts["suppress"] == 1
    assert metrics.suppression_reason_counts["low_signal_chatter"] == 1
    assert metrics.objection_counts["pricing_concern"]["suppress"] == 1
