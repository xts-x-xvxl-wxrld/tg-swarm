from __future__ import annotations

from datetime import UTC, datetime, timedelta

from telegram_app.campaign_signals import CampaignSignalBridge, CampaignSignalManager, ObservationWorkRefresher
from telegram_app.campaigns import CampaignManager
from telegram_app.capabilities.base import CapabilityResult
from telegram_app.capabilities.mtproto.registry import AccountRecord, AccountRegistry
from telegram_app.engagement_policy import CampaignEngagementPolicyManager, CampaignEngagementPolicyService
from telegram_app.external_conversations import (
    ConsentPosture,
    ExternalConversationManager,
    ExternalConversationRecord,
    ExternalConversationStatus,
    ExternalConversationTimingService,
    FollowUpWindowType,
    FollowUpTimingPolicy,
    ThreadOrigin,
)
from telegram_app.live_execution import (
    LiveActionStatus,
    LiveActionType,
    LiveExecutionManager,
    LiveExecutionPolicyStateManager,
    LiveExecutionService,
)
from telegram_app.qualification import QualificationManager, QualificationService
from telegram_app.work_items import WorkItemManager


class FakeMembershipCapability:
    def __init__(self, result: CapabilityResult) -> None:
        self._result = result
        self.calls: list[tuple[str, str]] = []

    def join(self, account_id: str, community_id: str) -> CapabilityResult:
        self.calls.append((account_id, community_id))
        return self._result


class FakeMessagingCapability:
    def __init__(self, results: list[CapabilityResult]) -> None:
        self._results = list(results)
        self.send_calls: list[tuple[str, str, str, dict[str, object] | None]] = []
        self.reply_calls: list[tuple[str, str, str, str, dict[str, object] | None]] = []
        self.mark_read_calls: list[tuple[str, str, str | None]] = []
        self.leave_dialog_calls: list[tuple[str, str]] = []

    def send_message(
        self,
        account_id: str,
        chat_id: str,
        text: str,
        *,
        approval_context: dict[str, object] | None = None,
    ) -> CapabilityResult:
        self.send_calls.append((account_id, chat_id, text, dict(approval_context or {})))
        if not self._results:
            raise AssertionError("No fake messaging result was configured for this call.")
        return self._results.pop(0)

    def send_reply(
        self,
        account_id: str,
        chat_id: str,
        reply_to_message_id: str | int,
        text: str,
        *,
        approval_context: dict[str, object] | None = None,
    ) -> CapabilityResult:
        self.reply_calls.append(
            (account_id, chat_id, str(reply_to_message_id), text, dict(approval_context or {}))
        )
        if not self._results:
            raise AssertionError("No fake messaging result was configured for this call.")
        return self._results.pop(0)

    def mark_read(
        self,
        account_id: str,
        chat_id: str,
        message_id: str | int | None = None,
    ) -> CapabilityResult:
        self.mark_read_calls.append((account_id, chat_id, None if message_id is None else str(message_id)))
        if not self._results:
            raise AssertionError("No fake messaging result was configured for this call.")
        return self._results.pop(0)

    def leave_dialog(self, account_id: str, peer_id: str) -> CapabilityResult:
        self.leave_dialog_calls.append((account_id, peer_id))
        if not self._results:
            raise AssertionError("No fake messaging result was configured for this call.")
        return self._results.pop(0)


class SequenceSampler:
    def __init__(self, *values: int) -> None:
        self._values = list(values)

    def __call__(self, minimum_value: int, maximum_value: int) -> int:
        if not self._values:
            raise AssertionError("No sampler value remained for this test call.")
        value = self._values.pop(0)
        assert minimum_value <= value <= maximum_value
        return value


def _operator_approval_context(
    *,
    campaign_id: str = "cmp-1",
    conversation_id: str = "",
) -> dict[str, object]:
    context: dict[str, object] = {
        "approved": True,
        "approval_mode": "operator",
        "approval_source": "test_live_execution",
        "approval_reason": "test_fixture",
        "campaign_id": campaign_id,
        "approved_by": "operator-1",
        "approved_at": "2026-05-23T12:00:00+00:00",
    }
    if conversation_id:
        context["conversation_id"] = conversation_id
    return context


def test_live_execution_manager_dedupes_enqueue_by_idempotency_key(tmp_path) -> None:
    manager = LiveExecutionManager(tmp_path / "campaigns")

    first = manager.enqueue(
        "cmp-1",
        "reader-1",
        action_type=LiveActionType.JOIN_COMMUNITY,
        payload={"community_id": "@example_group"},
        idempotency_key="join:cmp-1:reader-1:@example_group",
    )
    reloaded_manager = LiveExecutionManager(tmp_path / "campaigns")
    second = reloaded_manager.enqueue(
        "cmp-1",
        "reader-1",
        action_type=LiveActionType.JOIN_COMMUNITY,
        payload={"community_id": "@example_group"},
        idempotency_key="join:cmp-1:reader-1:@example_group",
    )

    assert second.action_id == first.action_id
    assert len(reloaded_manager.list_for_campaign("cmp-1")) == 1
    assert reloaded_manager.find_by_idempotency_key(
        "join:cmp-1:reader-1:@example_group",
        campaign_id="cmp-1",
    ) is not None


def test_live_execution_service_dispatches_dm_reply_and_updates_conversation(tmp_path) -> None:
    manager = LiveExecutionManager(tmp_path / "campaigns")
    conversation_manager = ExternalConversationManager(tmp_path / "campaigns")
    timing_service = ExternalConversationTimingService(
        conversation_manager,
        policy=FollowUpTimingPolicy(sample_int=SequenceSampler(24 * 3600)),
    )
    conversation_manager.save(
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
    messaging_capability = FakeMessagingCapability(
        [
            CapabilityResult(
                success=True,
                data={
                    "message_id": "501",
                    "date": "2026-05-23T12:30:00+00:00",
                    "outcome_code": "success",
                },
            )
        ]
    )
    service = LiveExecutionService(
        manager,
        messaging_capability=messaging_capability,
        conversation_manager=conversation_manager,
        conversation_timing_service=timing_service,
        worker_id="worker-1",
    )
    action = service.enqueue_action(
        "cmp-1",
        "reader-1",
        action_type=LiveActionType.SEND_DM_REPLY,
        conversation_id="conv-1",
        payload={
            "chat_id": "user-42",
            "text": "Thanks for reaching out.",
            "approval_context": _operator_approval_context(conversation_id="conv-1"),
        },
    )

    processed = service.dispatch_next_ready(now=datetime(2026, 5, 23, 12, 30, tzinfo=UTC))
    reloaded_action = manager.get("cmp-1", action.action_id)
    reloaded_conversation = conversation_manager.get("cmp-1", "conv-1")
    attempts = manager.list_attempts("cmp-1", action_id=action.action_id)

    assert processed is not None
    assert processed.status is LiveActionStatus.SUCCEEDED
    assert reloaded_action is not None
    assert reloaded_action.status is LiveActionStatus.SUCCEEDED
    assert reloaded_conversation is not None
    assert reloaded_conversation.status is ExternalConversationStatus.ACTIVE
    assert reloaded_conversation.last_outbound_message_id == "501"
    assert reloaded_conversation.next_action_type == "scheduled_dm_follow_up_window"
    assert reloaded_conversation.follow_up_due_at == datetime(2026, 5, 24, 12, 30, tzinfo=UTC)
    assert len(attempts) == 1
    assert attempts[0].outcome_code == "success"
    assert len(messaging_capability.send_calls) == 1


def test_live_execution_service_records_engagement_policy_metrics(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    CampaignManager(campaigns_root).ensure_campaign(
        "operator-1",
        campaign_id="cmp-1",
        workspace_path=str(campaigns_root / "cmp-1"),
    )
    manager = LiveExecutionManager(campaigns_root)
    messaging_capability = FakeMessagingCapability(
        [
            CapabilityResult(
                success=True,
                data={
                    "message_id": "policy-1",
                    "date": "2026-05-23T12:30:00+00:00",
                    "outcome_code": "success",
                },
            )
        ]
    )
    policy_service = CampaignEngagementPolicyService(CampaignEngagementPolicyManager(campaigns_root))
    service = LiveExecutionService(
        manager,
        messaging_capability=messaging_capability,
        engagement_policy_service=policy_service,
        worker_id="worker-policy-metrics",
    )
    action = service.enqueue_action(
        "cmp-1",
        "reader-1",
        action_type=LiveActionType.SEND_GROUP_MESSAGE,
        payload={
            "chat_id": "-100123",
            "text": "Hello group",
            "approval_context": _operator_approval_context(),
            "engagement_policy_context": {
                "latency_tier": "short_delay",
                "community_key": "-100123",
                "objection_hints": ["pricing_concern"],
            },
        },
    )

    processed = service.dispatch_next_ready(now=datetime(2026, 5, 23, 12, 30, tzinfo=UTC))
    metrics = CampaignEngagementPolicyManager(campaigns_root).get_metrics("cmp-1")

    assert processed is not None
    assert processed.status is LiveActionStatus.SUCCEEDED
    assert action.action_id
    assert metrics.execution_outcome_counts["success"] == 1
    assert metrics.community_counts["-100123"]["success"] == 1
    assert metrics.objection_counts["pricing_concern"]["success"] == 1


def test_live_execution_service_dispatches_group_reply_and_updates_conversation(tmp_path) -> None:
    manager = LiveExecutionManager(tmp_path / "campaigns")
    conversation_manager = ExternalConversationManager(tmp_path / "campaigns")
    timing_service = ExternalConversationTimingService(
        conversation_manager,
        policy=FollowUpTimingPolicy(sample_int=SequenceSampler(24 * 3600)),
    )
    conversation_manager.save(
        ExternalConversationRecord(
            conversation_id="conv-group-1",
            campaign_id="cmp-1",
            account_id="reader-1",
            peer_id="member-9",
            chat_id="-100123",
            thread_origin=ThreadOrigin.GROUP_REPLY,
            consent_posture=ConsentPosture.GROUP_CONTEXT_ONLY,
            status=ExternalConversationStatus.ACTIVE,
            reply_target_message_id="777",
        )
    )
    messaging_capability = FakeMessagingCapability(
        [
            CapabilityResult(
                success=True,
                data={
                    "message_id": "778",
                    "date": "2026-05-23T12:35:00+00:00",
                    "outcome_code": "success",
                },
            )
        ]
    )
    service = LiveExecutionService(
        manager,
        messaging_capability=messaging_capability,
        conversation_manager=conversation_manager,
        conversation_timing_service=timing_service,
        worker_id="worker-group-reply",
    )
    action = service.enqueue_action(
        "cmp-1",
        "reader-1",
        action_type=LiveActionType.SEND_GROUP_REPLY,
        conversation_id="conv-group-1",
        payload={
            "chat_id": "-100123",
            "text": "Appreciate the reply.",
            "asset_refs": ["asset-creative-1"],
            "approval_context": _operator_approval_context(conversation_id="conv-group-1"),
        },
    )

    processed = service.dispatch_next_ready(now=datetime(2026, 5, 23, 12, 35, tzinfo=UTC))
    reloaded_action = manager.get("cmp-1", action.action_id)
    reloaded_conversation = conversation_manager.get("cmp-1", "conv-group-1")
    attempts = manager.list_attempts("cmp-1", action_id=action.action_id)

    assert processed is not None
    assert processed.status is LiveActionStatus.SUCCEEDED
    assert reloaded_action is not None
    assert reloaded_action.status is LiveActionStatus.SUCCEEDED
    assert reloaded_conversation is not None
    assert reloaded_conversation.last_outbound_message_id == "778"
    assert reloaded_conversation.next_action_type == "scheduled_group_follow_up_window"
    assert reloaded_conversation.follow_up_due_at == datetime(2026, 5, 24, 12, 35, tzinfo=UTC)
    assert len(attempts) == 1
    assert attempts[0].outcome_code == "success"
    assert messaging_capability.reply_calls == [
        (
            "reader-1",
            "-100123",
            "777",
            "Appreciate the reply.",
            {
                **_operator_approval_context(conversation_id="conv-group-1"),
                "asset_refs": ["asset-creative-1"],
            },
        )
    ]


def test_live_execution_service_consumes_due_group_follow_up_and_reopens_next_window(tmp_path) -> None:
    manager = LiveExecutionManager(tmp_path / "campaigns")
    conversation_manager = ExternalConversationManager(tmp_path / "campaigns")
    timing_service = ExternalConversationTimingService(
        conversation_manager,
        policy=FollowUpTimingPolicy(sample_int=SequenceSampler(24 * 3600, 24 * 3600)),
    )
    conversation_manager.save(
        ExternalConversationRecord(
            conversation_id="conv-group-2",
            campaign_id="cmp-1",
            account_id="reader-1",
            peer_id="member-9",
            chat_id="-100123",
            thread_origin=ThreadOrigin.GROUP_REPLY,
            consent_posture=ConsentPosture.GROUP_CONTEXT_ONLY,
            status=ExternalConversationStatus.ACTIVE,
            reply_target_message_id="777",
            follow_up_due_at=datetime(2026, 5, 23, 11, 0, tzinfo=UTC),
            follow_up_window_type=FollowUpWindowType.GROUP_FOLLOW_UP,
        )
    )
    messaging_capability = FakeMessagingCapability(
        [
            CapabilityResult(
                success=True,
                data={
                    "message_id": "779",
                    "date": "2026-05-23T12:35:00+00:00",
                    "outcome_code": "success",
                },
            )
        ]
    )
    service = LiveExecutionService(
        manager,
        messaging_capability=messaging_capability,
        conversation_manager=conversation_manager,
        conversation_timing_service=timing_service,
        worker_id="worker-group-follow-up",
    )
    action = service.enqueue_action(
        "cmp-1",
        "reader-1",
        action_type=LiveActionType.SEND_GROUP_REPLY,
        conversation_id="conv-group-2",
        payload={
            "chat_id": "-100123",
            "text": "Circling back with one more thought.",
            "approval_context": _operator_approval_context(conversation_id="conv-group-2"),
        },
    )

    processed = service.dispatch_next_ready(now=datetime(2026, 5, 23, 12, 35, tzinfo=UTC))
    reloaded_action = manager.get("cmp-1", action.action_id)
    reloaded_conversation = conversation_manager.get("cmp-1", "conv-group-2")

    assert processed is not None
    assert reloaded_action is not None
    assert reloaded_action.status is LiveActionStatus.SUCCEEDED
    assert reloaded_conversation is not None
    assert reloaded_conversation.follow_up_attempt_count == 1
    assert reloaded_conversation.follow_up_due_at == datetime(2026, 5, 24, 12, 35, tzinfo=UTC)
    assert reloaded_conversation.next_action_type == "scheduled_group_follow_up_window"


def test_live_execution_service_dispatches_mark_read(tmp_path) -> None:
    manager = LiveExecutionManager(tmp_path / "campaigns")
    messaging_capability = FakeMessagingCapability(
        [
            CapabilityResult(
                success=True,
                data={"outcome_code": "success", "acknowledged": True},
            )
        ]
    )
    service = LiveExecutionService(
        manager,
        messaging_capability=messaging_capability,
        worker_id="worker-mark-read",
    )
    action = service.enqueue_action(
        "cmp-1",
        "reader-1",
        action_type=LiveActionType.MARK_READ,
        payload={"chat_id": "user-42", "message_id": "501"},
    )

    processed = service.dispatch_next_ready(now=datetime(2026, 5, 23, 12, 40, tzinfo=UTC))
    reloaded_action = manager.get("cmp-1", action.action_id)
    attempts = manager.list_attempts("cmp-1", action_id=action.action_id)

    assert processed is not None
    assert processed.status is LiveActionStatus.SUCCEEDED
    assert reloaded_action is not None
    assert reloaded_action.status is LiveActionStatus.SUCCEEDED
    assert len(attempts) == 1
    assert attempts[0].outcome_code == "success"
    assert messaging_capability.mark_read_calls == [("reader-1", "user-42", "501")]


def test_live_execution_service_dispatches_leave_dialog(tmp_path) -> None:
    manager = LiveExecutionManager(tmp_path / "campaigns")
    messaging_capability = FakeMessagingCapability(
        [
            CapabilityResult(
                success=True,
                data={"outcome_code": "success", "left": True},
            )
        ]
    )
    service = LiveExecutionService(
        manager,
        messaging_capability=messaging_capability,
        worker_id="worker-leave-dialog",
    )
    action = service.enqueue_action(
        "cmp-1",
        "reader-1",
        action_type=LiveActionType.LEAVE_DIALOG,
        payload={"peer_id": "user-42"},
    )

    processed = service.dispatch_next_ready(now=datetime(2026, 5, 23, 12, 41, tzinfo=UTC))
    reloaded_action = manager.get("cmp-1", action.action_id)

    assert processed is not None
    assert processed.status is LiveActionStatus.SUCCEEDED
    assert reloaded_action is not None
    assert reloaded_action.status is LiveActionStatus.SUCCEEDED
    assert messaging_capability.leave_dialog_calls == [("reader-1", "user-42")]


def test_live_execution_service_does_not_retry_ambiguous_transient_group_sends(tmp_path) -> None:
    manager = LiveExecutionManager(tmp_path / "campaigns")
    messaging_capability = FakeMessagingCapability(
        [
            CapabilityResult(
                success=False,
                data={"outcome_code": "transient_error"},
                error="Temporary upstream issue.",
            )
        ]
    )
    service = LiveExecutionService(
        manager,
        messaging_capability=messaging_capability,
        worker_id="worker-transient-retry",
    )
    action = service.enqueue_action(
        "cmp-1",
        "reader-1",
        action_type=LiveActionType.SEND_GROUP_MESSAGE,
        payload={
            "chat_id": "-100123",
            "text": "Hello group",
            "approval_context": _operator_approval_context(),
        },
    )
    now = datetime(2026, 5, 23, 12, 0, tzinfo=UTC)

    processed = service.dispatch_next_ready(now=now)
    reloaded_action = manager.get("cmp-1", action.action_id)

    assert processed is not None
    assert processed.status is LiveActionStatus.FAILED
    assert reloaded_action is not None
    assert reloaded_action.next_attempt_at is None
    assert reloaded_action.last_result_summary.startswith(
        "Stopped automatic retry after an ambiguous Telegram send failure"
    )
    assert reloaded_action.last_error == "Temporary upstream issue."


def test_live_execution_service_retries_rate_limited_group_message(tmp_path) -> None:
    manager = LiveExecutionManager(tmp_path / "campaigns")
    messaging_capability = FakeMessagingCapability(
        [
            CapabilityResult(
                success=False,
                data={"outcome_code": "rate_limited", "wait_seconds": 45},
                error="Telegram asked this account to wait 45 seconds.",
            )
        ]
    )
    service = LiveExecutionService(
        manager,
        messaging_capability=messaging_capability,
        worker_id="worker-2",
    )
    action = service.enqueue_action(
        "cmp-1",
        "reader-1",
        action_type=LiveActionType.SEND_GROUP_MESSAGE,
        payload={
            "chat_id": "-100123",
            "text": "Hello group",
            "approval_context": _operator_approval_context(),
        },
    )
    now = datetime(2026, 5, 23, 12, 0, tzinfo=UTC)

    processed = service.dispatch_next_ready(now=now)
    reloaded_action = manager.get("cmp-1", action.action_id)
    attempts = manager.list_attempts("cmp-1", action_id=action.action_id)

    assert processed is not None
    assert processed.status is LiveActionStatus.RETRY_WAIT
    assert reloaded_action is not None
    assert reloaded_action.retry_count == 1
    assert reloaded_action.next_attempt_at == now + timedelta(seconds=45)
    assert len(attempts) == 1
    assert attempts[0].outcome_code == "rate_limited"


def test_live_execution_service_blocks_deferred_channel_group_message(tmp_path) -> None:
    manager = LiveExecutionManager(tmp_path / "campaigns")
    messaging_capability = FakeMessagingCapability(
        [
            CapabilityResult(
                success=False,
                data={"outcome_code": "channel_send_deferred"},
                error="Broadcast channel sends are deferred in this version.",
            )
        ]
    )
    service = LiveExecutionService(
        manager,
        messaging_capability=messaging_capability,
        worker_id="worker-channel-deferred",
    )
    action = service.enqueue_action(
        "cmp-1",
        "reader-1",
        action_type=LiveActionType.SEND_GROUP_MESSAGE,
        payload={
            "chat_id": "@example_channel",
            "text": "Hello channel",
            "approval_context": _operator_approval_context(),
        },
    )

    processed = service.dispatch_next_ready(now=datetime(2026, 5, 23, 12, 2, tzinfo=UTC))
    reloaded_action = manager.get("cmp-1", action.action_id)

    assert processed is not None
    assert processed.status is LiveActionStatus.BLOCKED
    assert reloaded_action is not None
    assert reloaded_action.status is LiveActionStatus.BLOCKED
    assert reloaded_action.last_error == "Broadcast channel sends are deferred in this version."


def test_live_execution_service_blocks_dm_reply_without_inbound_first_posture(tmp_path) -> None:
    manager = LiveExecutionManager(tmp_path / "campaigns")
    conversation_manager = ExternalConversationManager(tmp_path / "campaigns")
    conversation_manager.save(
        ExternalConversationRecord(
            conversation_id="conv-2",
            campaign_id="cmp-1",
            account_id="reader-1",
            peer_id="user-42",
            chat_id="user-42",
            thread_origin=ThreadOrigin.DIRECT_INBOUND_DM,
            consent_posture=ConsentPosture.GROUP_CONTEXT_ONLY,
            status=ExternalConversationStatus.ACTIVE,
            external_user_messaged_first=False,
        )
    )
    messaging_capability = FakeMessagingCapability(
        [
            CapabilityResult(
                success=True,
                data={"message_id": "should-not-send", "outcome_code": "success"},
            )
        ]
    )
    service = LiveExecutionService(
        manager,
        messaging_capability=messaging_capability,
        conversation_manager=conversation_manager,
        worker_id="worker-3",
    )
    action = service.enqueue_action(
        "cmp-1",
        "reader-1",
        action_type=LiveActionType.SEND_DM_REPLY,
        conversation_id="conv-2",
        payload={
            "chat_id": "user-42",
            "text": "Checking in",
            "approval_context": _operator_approval_context(conversation_id="conv-2"),
        },
    )

    processed = service.dispatch_next_ready(now=datetime(2026, 5, 23, 12, 15, tzinfo=UTC))
    reloaded_action = manager.get("cmp-1", action.action_id)
    attempts = manager.list_attempts("cmp-1", action_id=action.action_id)

    assert processed is not None
    assert processed.status is LiveActionStatus.BLOCKED
    assert reloaded_action is not None
    assert reloaded_action.terminal_failure_reason
    assert len(attempts) == 1
    assert attempts[0].outcome_code == "dm_inbound_required"
    assert attempts[0].result_data["policy_decision"] == "blocked"
    assert attempts[0].result_data["reason_codes"] == ["dm_inbound_required"]
    assert messaging_capability.send_calls == []
    assert messaging_capability.reply_calls == []


def test_live_execution_service_blocks_autonomous_reply_with_manual_only_posture_context(tmp_path) -> None:
    manager = LiveExecutionManager(tmp_path / "campaigns")
    conversation_manager = ExternalConversationManager(tmp_path / "campaigns")
    conversation_manager.save(
        ExternalConversationRecord(
            conversation_id="conv-auto-policy",
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
    messaging_capability = FakeMessagingCapability(
        [
            CapabilityResult(
                success=True,
                data={"message_id": "should-not-send", "outcome_code": "success"},
            )
        ]
    )
    service = LiveExecutionService(
        manager,
        messaging_capability=messaging_capability,
        conversation_manager=conversation_manager,
        worker_id="worker-auto-policy",
    )
    action = service.enqueue_action(
        "cmp-1",
        "reader-1",
        action_type=LiveActionType.SEND_DM_REPLY,
        conversation_id="conv-auto-policy",
        payload={
            "chat_id": "user-42",
            "text": "Quick follow-up.",
            "approval_context": {
                "approved": True,
                "approval_mode": "autonomous",
                "approval_source": "engagement_brain_authorizer",
                "authorization_decision": "allowed",
                "authorized_action_type": "send_dm_reply",
                "campaign_id": "cmp-1",
                "conversation_id": "conv-auto-policy",
                "context_fingerprint": "ctx-1",
                "authorized_at": "2026-05-23T12:00:00+00:00",
                "autonomous_send_mode": "manual_only",
                "community_risk_level": "low",
                "conversation_risk_level": "low",
                "tone_contract_fingerprint": "tone-1",
            },
        },
    )

    processed = service.dispatch_next_ready(now=datetime(2026, 5, 23, 12, 15, tzinfo=UTC))
    attempts = manager.list_attempts("cmp-1", action_id=action.action_id)

    assert processed is not None
    assert processed.status is LiveActionStatus.BLOCKED
    assert len(attempts) == 1
    assert attempts[0].outcome_code == "autonomous_send_posture_blocked"
    assert attempts[0].result_data["reason_codes"] == ["autonomous_send_posture_blocked"]
    assert messaging_capability.send_calls == []
    assert messaging_capability.reply_calls == []


def test_live_execution_service_blocks_paused_conversation_before_dispatch(tmp_path) -> None:
    manager = LiveExecutionManager(tmp_path / "campaigns")
    conversation_manager = ExternalConversationManager(tmp_path / "campaigns")
    conversation_manager.save(
        ExternalConversationRecord(
            conversation_id="conv-paused",
            campaign_id="cmp-1",
            account_id="reader-1",
            peer_id="user-42",
            chat_id="user-42",
            thread_origin=ThreadOrigin.DIRECT_INBOUND_DM,
            consent_posture=ConsentPosture.INBOUND_ONLY,
            status=ExternalConversationStatus.PAUSED,
            external_user_messaged_first=True,
        )
    )
    messaging_capability = FakeMessagingCapability(
        [
            CapabilityResult(
                success=True,
                data={"message_id": "should-not-send", "outcome_code": "success"},
            )
        ]
    )
    service = LiveExecutionService(
        manager,
        messaging_capability=messaging_capability,
        conversation_manager=conversation_manager,
        worker_id="worker-paused",
    )
    action = service.enqueue_action(
        "cmp-1",
        "reader-1",
        action_type=LiveActionType.SEND_DM_REPLY,
        conversation_id="conv-paused",
        payload={
            "chat_id": "user-42",
            "text": "Checking in",
            "approval_context": _operator_approval_context(conversation_id="conv-paused"),
        },
    )

    processed = service.dispatch_next_ready(now=datetime(2026, 5, 23, 12, 20, tzinfo=UTC))
    reloaded_action = manager.get("cmp-1", action.action_id)
    attempts = manager.list_attempts("cmp-1", action_id=action.action_id)

    assert processed is not None
    assert processed.status is LiveActionStatus.BLOCKED
    assert reloaded_action is not None
    assert reloaded_action.terminal_failure_reason == "Blocked an action because the conversation is paused."
    assert len(attempts) == 1
    assert attempts[0].outcome_code == "conversation_paused"
    assert attempts[0].result_data["reason_codes"] == ["conversation_paused"]
    assert messaging_capability.send_calls == []
    assert messaging_capability.reply_calls == []


def test_live_execution_service_marks_handoff_delivered_on_successful_conversion_reply(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    manager = LiveExecutionManager(campaigns_root)
    conversation_manager = ExternalConversationManager(campaigns_root)
    campaign_manager = CampaignManager(campaigns_root)
    campaign_manager.ensure_campaign("operator-1", campaign_id="cmp-1", workspace_path=str(campaigns_root / "cmp-1"))
    conversation_manager.save(
        ExternalConversationRecord(
            conversation_id="conv-handoff-success",
            campaign_id="cmp-1",
            account_id="reader-1",
            peer_id="user-42",
            chat_id="user-42",
            thread_origin=ThreadOrigin.DIRECT_INBOUND_DM,
            consent_posture=ConsentPosture.INBOUND_ONLY,
            status=ExternalConversationStatus.ACTIVE,
            external_user_messaged_first=True,
            handoff_status="ready",
            qualification_status="conversion_ready",
        )
    )
    messaging_capability = FakeMessagingCapability(
        [
            CapabilityResult(
                success=True,
                data={
                    "message_id": "handoff-501",
                    "date": "2026-05-23T12:30:00+00:00",
                    "outcome_code": "success",
                },
            )
        ]
    )
    qualification_service = QualificationService(
        campaign_manager,
        QualificationManager(campaigns_root),
        conversation_manager,
    )
    service = LiveExecutionService(
        manager,
        messaging_capability=messaging_capability,
        conversation_manager=conversation_manager,
        campaign_manager=campaign_manager,
        qualification_service=qualification_service,
        worker_id="worker-handoff-success",
    )
    action = service.enqueue_action(
        "cmp-1",
        "reader-1",
        action_type=LiveActionType.SEND_DM_REPLY,
        conversation_id="conv-handoff-success",
        payload={
            "chat_id": "user-42",
            "text": "Here is the next step: https://example.com/apply",
            "approval_context": {
                **_operator_approval_context(conversation_id="conv-handoff-success"),
                "handoff_intent": True,
                "handoff_target_summary": "External website: https://example.com/apply.",
            },
        },
    )

    processed = service.dispatch_next_ready(now=datetime(2026, 5, 23, 12, 30, tzinfo=UTC))
    updated_conversation = conversation_manager.get("cmp-1", "conv-handoff-success")
    attempts = manager.list_attempts("cmp-1", action_id=action.action_id)

    assert processed is not None
    assert processed.status is LiveActionStatus.SUCCEEDED
    assert len(attempts) == 1
    assert updated_conversation is not None
    assert updated_conversation.handoff_status == "delivered"
    assert updated_conversation.last_handoff_action_id == action.action_id
    assert "Delivered a conversion handoff" in updated_conversation.handoff_summary


def test_live_execution_service_marks_handoff_blocked_on_policy_block(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    manager = LiveExecutionManager(campaigns_root)
    conversation_manager = ExternalConversationManager(campaigns_root)
    campaign_manager = CampaignManager(campaigns_root)
    campaign_manager.ensure_campaign("operator-1", campaign_id="cmp-1", workspace_path=str(campaigns_root / "cmp-1"))
    conversation_manager.save(
        ExternalConversationRecord(
            conversation_id="conv-handoff-blocked",
            campaign_id="cmp-1",
            account_id="reader-1",
            peer_id="user-42",
            chat_id="user-42",
            thread_origin=ThreadOrigin.DIRECT_INBOUND_DM,
            consent_posture=ConsentPosture.INBOUND_ONLY,
            status=ExternalConversationStatus.PAUSED,
            external_user_messaged_first=True,
            handoff_status="ready",
            qualification_status="conversion_ready",
        )
    )
    qualification_service = QualificationService(
        campaign_manager,
        QualificationManager(campaigns_root),
        conversation_manager,
    )
    service = LiveExecutionService(
        manager,
        conversation_manager=conversation_manager,
        campaign_manager=campaign_manager,
        qualification_service=qualification_service,
        worker_id="worker-handoff-blocked",
    )
    action = service.enqueue_action(
        "cmp-1",
        "reader-1",
        action_type=LiveActionType.SEND_DM_REPLY,
        conversation_id="conv-handoff-blocked",
        payload={
            "chat_id": "user-42",
            "text": "Here is the next step: https://example.com/apply",
            "approval_context": {
                **_operator_approval_context(conversation_id="conv-handoff-blocked"),
                "handoff_intent": True,
                "handoff_target_summary": "External website: https://example.com/apply.",
            },
        },
    )

    processed = service.dispatch_next_ready(now=datetime(2026, 5, 23, 12, 31, tzinfo=UTC))
    updated_conversation = conversation_manager.get("cmp-1", "conv-handoff-blocked")
    attempts = manager.list_attempts("cmp-1", action_id=action.action_id)

    assert processed is not None
    assert processed.status is LiveActionStatus.BLOCKED
    assert len(attempts) == 1
    assert attempts[-1].outcome_code == "conversation_paused"
    assert updated_conversation is not None
    assert updated_conversation.handoff_status == "blocked"
    assert "Blocked a conversion handoff" in updated_conversation.handoff_summary


def test_live_execution_service_records_account_rate_limit_cooldown(tmp_path) -> None:
    manager = LiveExecutionManager(tmp_path / "campaigns")
    messaging_capability = FakeMessagingCapability(
        [
            CapabilityResult(
                success=False,
                data={"outcome_code": "rate_limited", "wait_seconds": 600},
                error="Telegram asked this account to wait 600 seconds.",
            )
        ]
    )
    policy_state_manager = LiveExecutionPolicyStateManager(tmp_path)
    service = LiveExecutionService(
        manager,
        messaging_capability=messaging_capability,
        policy_state_manager=policy_state_manager,
        worker_id="worker-rate-limit-state",
    )
    first = service.enqueue_action(
        "cmp-1",
        "reader-1",
        action_type=LiveActionType.SEND_GROUP_MESSAGE,
        payload={"chat_id": "-100123", "text": "Hello group", "approval_context": _operator_approval_context()},
    )
    second = service.enqueue_action(
        "cmp-1",
        "reader-1",
        action_type=LiveActionType.SEND_GROUP_MESSAGE,
        payload={"chat_id": "-100124", "text": "Hello again", "approval_context": _operator_approval_context()},
    )

    first_processed = service.dispatch_next_ready(now=datetime(2026, 5, 23, 12, 0, tzinfo=UTC))
    second_processed = service.dispatch_next_ready(now=datetime(2026, 5, 23, 12, 5, tzinfo=UTC))
    first_attempts = manager.list_attempts("cmp-1", action_id=first.action_id)
    second_attempts = manager.list_attempts("cmp-1", action_id=second.action_id)

    assert first_processed is not None
    assert first_processed.status is LiveActionStatus.RETRY_WAIT
    assert len(first_attempts) == 1
    assert first_attempts[0].outcome_code == "rate_limited"

    assert second_processed is not None
    assert second_processed.status is LiveActionStatus.RETRY_WAIT
    assert len(second_attempts) == 1
    assert second_attempts[0].outcome_code == "account_rate_limited"
    assert second_attempts[0].result_data["policy_decision"] == "cooldown"
    assert len(messaging_capability.send_calls) == 1


def test_live_execution_service_continues_other_accounts_after_mid_wave_rate_limit(tmp_path) -> None:
    manager = LiveExecutionManager(tmp_path / "campaigns")
    messaging_capability = FakeMessagingCapability(
        [
            CapabilityResult(
                success=False,
                data={"outcome_code": "rate_limited", "wait_seconds": 600},
                error="Telegram asked this account to wait 600 seconds.",
            ),
            CapabilityResult(
                success=True,
                data={"message_id": "9001", "outcome_code": "success"},
            ),
        ]
    )
    policy_state_manager = LiveExecutionPolicyStateManager(tmp_path)
    service = LiveExecutionService(
        manager,
        messaging_capability=messaging_capability,
        policy_state_manager=policy_state_manager,
        worker_id="worker-mid-wave-rate-limit",
    )
    first = service.enqueue_action(
        "cmp-1",
        "reader-1",
        action_type=LiveActionType.SEND_GROUP_MESSAGE,
        payload={"chat_id": "-100111", "text": "First wave", "approval_context": _operator_approval_context()},
    )
    second = service.enqueue_action(
        "cmp-1",
        "reader-1",
        action_type=LiveActionType.SEND_GROUP_MESSAGE,
        payload={"chat_id": "-100112", "text": "Second wave", "approval_context": _operator_approval_context()},
    )
    third = service.enqueue_action(
        "cmp-1",
        "reader-2",
        action_type=LiveActionType.SEND_GROUP_MESSAGE,
        payload={"chat_id": "-100113", "text": "Third wave", "approval_context": _operator_approval_context()},
    )

    first_processed = service.dispatch_next_ready(now=datetime(2026, 5, 23, 12, 0, tzinfo=UTC))
    second_processed = service.dispatch_next_ready(now=datetime(2026, 5, 23, 12, 1, tzinfo=UTC))
    third_processed = service.dispatch_next_ready(now=datetime(2026, 5, 23, 12, 2, tzinfo=UTC))
    first_attempts = manager.list_attempts("cmp-1", action_id=first.action_id)
    second_attempts = manager.list_attempts("cmp-1", action_id=second.action_id)
    third_attempts = manager.list_attempts("cmp-1", action_id=third.action_id)

    assert first_processed is not None
    assert first_processed.status is LiveActionStatus.RETRY_WAIT
    assert first_attempts[-1].outcome_code == "rate_limited"

    assert second_processed is not None
    assert second_processed.status is LiveActionStatus.RETRY_WAIT
    assert second_attempts[-1].outcome_code == "account_rate_limited"

    assert third_processed is not None
    assert third_processed.status is LiveActionStatus.SUCCEEDED
    assert third_attempts[-1].outcome_code == "success"
    assert [call[0] for call in messaging_capability.send_calls] == ["reader-1", "reader-2"]


def test_live_execution_service_continues_other_accounts_after_flagged_account_pause(tmp_path) -> None:
    manager = LiveExecutionManager(tmp_path / "campaigns")
    messaging_capability = FakeMessagingCapability(
        [
            CapabilityResult(
                success=False,
                data={"outcome_code": "account_flagged"},
                error="Telegram flagged this account for the requested action.",
            ),
            CapabilityResult(
                success=True,
                data={"message_id": "9010", "outcome_code": "success"},
            ),
        ]
    )
    policy_state_manager = LiveExecutionPolicyStateManager(tmp_path)
    service = LiveExecutionService(
        manager,
        messaging_capability=messaging_capability,
        policy_state_manager=policy_state_manager,
        worker_id="worker-mid-wave-flagged",
    )
    first = service.enqueue_action(
        "cmp-1",
        "reader-1",
        action_type=LiveActionType.SEND_GROUP_MESSAGE,
        payload={"chat_id": "-100121", "text": "Flagged wave", "approval_context": _operator_approval_context()},
    )
    second = service.enqueue_action(
        "cmp-1",
        "reader-1",
        action_type=LiveActionType.SEND_GROUP_MESSAGE,
        payload={"chat_id": "-100122", "text": "Should pause", "approval_context": _operator_approval_context()},
    )
    third = service.enqueue_action(
        "cmp-1",
        "reader-2",
        action_type=LiveActionType.SEND_GROUP_MESSAGE,
        payload={"chat_id": "-100123", "text": "Healthy account continues", "approval_context": _operator_approval_context()},
    )

    first_processed = service.dispatch_next_ready(now=datetime(2026, 5, 23, 12, 0, tzinfo=UTC))
    second_processed = service.dispatch_next_ready(now=datetime(2026, 5, 23, 12, 1, tzinfo=UTC))
    third_processed = service.dispatch_next_ready(now=datetime(2026, 5, 23, 12, 2, tzinfo=UTC))
    first_attempts = manager.list_attempts("cmp-1", action_id=first.action_id)
    second_attempts = manager.list_attempts("cmp-1", action_id=second.action_id)
    third_attempts = manager.list_attempts("cmp-1", action_id=third.action_id)

    assert first_processed is not None
    assert first_processed.status is LiveActionStatus.BLOCKED
    assert first_attempts[-1].outcome_code == "account_flagged"

    assert second_processed is not None
    assert second_processed.status is LiveActionStatus.BLOCKED
    assert second_attempts[-1].outcome_code == "account_paused"

    assert third_processed is not None
    assert third_processed.status is LiveActionStatus.SUCCEEDED
    assert third_attempts[-1].outcome_code == "success"
    assert [call[0] for call in messaging_capability.send_calls] == ["reader-1", "reader-2"]


def test_live_execution_service_reclaims_expired_claim_after_restart_without_double_send(tmp_path) -> None:
    manager = LiveExecutionManager(tmp_path / "campaigns")
    messaging_capability = FakeMessagingCapability(
        [
            CapabilityResult(
                success=True,
                data={"message_id": "claim-1", "outcome_code": "success"},
            )
        ]
    )
    service = LiveExecutionService(
        manager,
        messaging_capability=messaging_capability,
        worker_id="worker-claim-original",
        claim_ttl_seconds=60,
    )
    action = service.enqueue_action(
        "cmp-1",
        "reader-1",
        action_type=LiveActionType.SEND_GROUP_MESSAGE,
        payload={"chat_id": "-100130", "text": "Queued before restart", "approval_context": _operator_approval_context()},
    )

    claimed = manager.claim_next_ready(
        owner_id="worker-crashed",
        claim_ttl_seconds=60,
        now=datetime(2026, 5, 23, 12, 0, tzinfo=UTC),
    )
    reloaded_service = LiveExecutionService(
        LiveExecutionManager(tmp_path / "campaigns"),
        messaging_capability=messaging_capability,
        worker_id="worker-after-restart",
        claim_ttl_seconds=60,
    )

    before_expiry = reloaded_service.dispatch_next_ready(now=datetime(2026, 5, 23, 12, 0, 30, tzinfo=UTC))
    after_expiry = reloaded_service.dispatch_next_ready(now=datetime(2026, 5, 23, 12, 1, 1, tzinfo=UTC))
    second_restart = LiveExecutionService(
        LiveExecutionManager(tmp_path / "campaigns"),
        messaging_capability=messaging_capability,
        worker_id="worker-final-check",
        claim_ttl_seconds=60,
    )
    nothing_left = second_restart.dispatch_next_ready(now=datetime(2026, 5, 23, 12, 2, tzinfo=UTC))
    attempts = manager.list_attempts("cmp-1", action_id=action.action_id)

    assert claimed is not None
    assert before_expiry is None
    assert after_expiry is not None
    assert after_expiry.status is LiveActionStatus.SUCCEEDED
    assert nothing_left is None
    assert len(attempts) == 1
    assert messaging_capability.send_calls == [
        ("reader-1", "-100130", "Queued before restart", _operator_approval_context()),
    ]


def test_live_execution_service_blocks_reply_when_approval_context_targets_wrong_conversation(tmp_path) -> None:
    manager = LiveExecutionManager(tmp_path / "campaigns")
    conversation_manager = ExternalConversationManager(tmp_path / "campaigns")
    conversation_manager.save(
        ExternalConversationRecord(
            conversation_id="conv-context-1",
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
    messaging_capability = FakeMessagingCapability(
        [CapabilityResult(success=True, data={"message_id": "should-not-send", "outcome_code": "success"})]
    )
    service = LiveExecutionService(
        manager,
        messaging_capability=messaging_capability,
        conversation_manager=conversation_manager,
        worker_id="worker-wrong-conversation",
    )
    action = service.enqueue_action(
        "cmp-1",
        "reader-1",
        action_type=LiveActionType.SEND_DM_REPLY,
        conversation_id="conv-context-1",
        payload={
            "chat_id": "user-42",
            "text": "Reply with stale context.",
            "approval_context": {
                **_operator_approval_context(conversation_id="conv-stale"),
            },
        },
    )

    processed = service.dispatch_next_ready(now=datetime(2026, 5, 23, 12, 20, tzinfo=UTC))
    attempts = manager.list_attempts("cmp-1", action_id=action.action_id)

    assert processed is not None
    assert processed.status is LiveActionStatus.BLOCKED
    assert attempts[-1].outcome_code == "approval_context_invalid"
    assert messaging_capability.send_calls == []
    assert messaging_capability.reply_calls == []


def test_live_execution_service_blocks_group_reply_when_reply_target_changes_after_restart(tmp_path) -> None:
    manager = LiveExecutionManager(tmp_path / "campaigns")
    conversation_manager = ExternalConversationManager(tmp_path / "campaigns")
    conversation_manager.save(
        ExternalConversationRecord(
            conversation_id="conv-reply-target",
            campaign_id="cmp-1",
            account_id="reader-1",
            peer_id="member-7",
            chat_id="-100140",
            thread_origin=ThreadOrigin.GROUP_REPLY,
            consent_posture=ConsentPosture.GROUP_CONTEXT_ONLY,
            status=ExternalConversationStatus.ACTIVE,
            reply_target_message_id="900",
        )
    )
    service = LiveExecutionService(
        manager,
        messaging_capability=FakeMessagingCapability(
            [CapabilityResult(success=True, data={"message_id": "should-not-send", "outcome_code": "success"})]
        ),
        conversation_manager=conversation_manager,
        worker_id="worker-reply-target",
    )
    action = service.enqueue_action(
        "cmp-1",
        "reader-1",
        action_type=LiveActionType.SEND_GROUP_REPLY,
        conversation_id="conv-reply-target",
        payload={
            "chat_id": "-100140",
            "reply_to_message_id": "777",
            "text": "Replying with stale target.",
            "approval_context": _operator_approval_context(conversation_id="conv-reply-target"),
        },
    )

    processed = LiveExecutionService(
        LiveExecutionManager(tmp_path / "campaigns"),
        messaging_capability=FakeMessagingCapability(
            [CapabilityResult(success=True, data={"message_id": "should-not-send", "outcome_code": "success"})]
        ),
        conversation_manager=conversation_manager,
        worker_id="worker-reply-target-restarted",
    ).dispatch_next_ready(now=datetime(2026, 5, 23, 12, 25, tzinfo=UTC))
    attempts = manager.list_attempts("cmp-1", action_id=action.action_id)

    assert processed is not None
    assert processed.status is LiveActionStatus.BLOCKED
    assert attempts[-1].outcome_code == "reply_target_mismatch"


def test_live_execution_service_reschedules_overdue_follow_up_outside_quiet_hours_after_late_send(tmp_path) -> None:
    manager = LiveExecutionManager(tmp_path / "campaigns")
    conversation_manager = ExternalConversationManager(tmp_path / "campaigns")
    timing_service = ExternalConversationTimingService(
        conversation_manager,
        policy=FollowUpTimingPolicy(sample_int=SequenceSampler(24 * 3600, 10)),
    )
    conversation_manager.save(
        ExternalConversationRecord(
            conversation_id="conv-quiet-overdue",
            campaign_id="cmp-1",
            account_id="reader-1",
            peer_id="member-9",
            chat_id="-100150",
            thread_origin=ThreadOrigin.GROUP_REPLY,
            consent_posture=ConsentPosture.GROUP_CONTEXT_ONLY,
            status=ExternalConversationStatus.ACTIVE,
            reply_target_message_id="777",
            follow_up_due_at=datetime(2026, 5, 23, 18, 0, tzinfo=UTC),
            follow_up_window_type=FollowUpWindowType.GROUP_FOLLOW_UP,
        )
    )
    messaging_capability = FakeMessagingCapability(
        [
            CapabilityResult(
                success=True,
                data={
                    "message_id": "9030",
                    "date": "2026-05-23T23:50:00+00:00",
                    "outcome_code": "success",
                },
            )
        ]
    )
    service = LiveExecutionService(
        manager,
        messaging_capability=messaging_capability,
        conversation_manager=conversation_manager,
        conversation_timing_service=timing_service,
        worker_id="worker-quiet-overdue",
    )
    action = service.enqueue_action(
        "cmp-1",
        "reader-1",
        action_type=LiveActionType.SEND_GROUP_REPLY,
        conversation_id="conv-quiet-overdue",
        payload={
            "chat_id": "-100150",
            "text": "Circling back after the missed window.",
            "approval_context": _operator_approval_context(conversation_id="conv-quiet-overdue"),
        },
    )

    processed = service.dispatch_next_ready(now=datetime(2026, 5, 23, 23, 50, tzinfo=UTC))
    updated_conversation = conversation_manager.get("cmp-1", "conv-quiet-overdue")

    assert processed is not None
    assert processed.status is LiveActionStatus.SUCCEEDED
    assert updated_conversation is not None
    assert updated_conversation.follow_up_due_at == datetime(2026, 5, 25, 7, 10, tzinfo=UTC)
    assert updated_conversation.next_action_type == "scheduled_group_follow_up_window"
    assert action.action_id


def test_live_execution_service_pause_after_partial_claim_blocks_late_send_after_claim_expiry(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    manager = LiveExecutionManager(campaigns_root)
    campaign_manager = CampaignManager(campaigns_root)
    campaign_manager.ensure_campaign("operator-1", campaign_id="cmp-1", workspace_path=str(campaigns_root / "cmp-1"))
    messaging_capability = FakeMessagingCapability(
        [CapabilityResult(success=True, data={"message_id": "9040", "outcome_code": "success"})]
    )
    service = LiveExecutionService(
        manager,
        messaging_capability=messaging_capability,
        campaign_manager=campaign_manager,
        worker_id="worker-partial-claim",
        claim_ttl_seconds=60,
    )
    action = service.enqueue_action(
        "cmp-1",
        "reader-1",
        action_type=LiveActionType.SEND_GROUP_MESSAGE,
        payload={"chat_id": "-100160", "text": "Should never leak", "approval_context": _operator_approval_context()},
    )

    claimed = manager.claim_next_ready(
        owner_id="worker-crashed",
        claim_ttl_seconds=60,
        now=datetime(2026, 5, 23, 12, 0, tzinfo=UTC),
    )
    assert claimed is not None
    assert service.pause_campaign("cmp-1")

    processed = LiveExecutionService(
        LiveExecutionManager(campaigns_root),
        messaging_capability=messaging_capability,
        campaign_manager=campaign_manager,
        worker_id="worker-after-pause",
        claim_ttl_seconds=60,
    ).dispatch_next_ready(now=datetime(2026, 5, 23, 12, 1, 1, tzinfo=UTC))
    attempts = manager.list_attempts("cmp-1", action_id=action.action_id)

    assert processed is not None
    assert processed.status is LiveActionStatus.BLOCKED
    assert attempts[-1].outcome_code == "campaign_paused"
    assert messaging_capability.send_calls == []


def test_live_execution_service_pauses_community_after_repeated_write_forbidden(tmp_path) -> None:
    manager = LiveExecutionManager(tmp_path / "campaigns")
    messaging_capability = FakeMessagingCapability(
        [
            CapabilityResult(
                success=False,
                data={"outcome_code": "write_forbidden"},
                error="This account is not allowed to post in that chat.",
            ),
            CapabilityResult(
                success=False,
                data={"outcome_code": "write_forbidden"},
                error="Telegram requires additional permissions for that action in this chat.",
            ),
        ]
    )
    policy_state_manager = LiveExecutionPolicyStateManager(tmp_path)
    service = LiveExecutionService(
        manager,
        messaging_capability=messaging_capability,
        policy_state_manager=policy_state_manager,
        worker_id="worker-community-friction",
    )
    first = service.enqueue_action(
        "cmp-1",
        "reader-1",
        action_type=LiveActionType.SEND_GROUP_MESSAGE,
        payload={"chat_id": "-100123", "text": "Hello group", "approval_context": _operator_approval_context()},
    )
    second = service.enqueue_action(
        "cmp-1",
        "reader-2",
        action_type=LiveActionType.SEND_GROUP_MESSAGE,
        payload={"chat_id": "-100123", "text": "Trying again", "approval_context": _operator_approval_context()},
    )
    third = service.enqueue_action(
        "cmp-1",
        "reader-3",
        action_type=LiveActionType.SEND_GROUP_MESSAGE,
        payload={"chat_id": "-100123", "text": "Should now block", "approval_context": _operator_approval_context()},
    )

    first_processed = service.dispatch_next_ready(now=datetime(2026, 5, 23, 12, 0, tzinfo=UTC))
    second_processed = service.dispatch_next_ready(now=datetime(2026, 5, 23, 12, 2, tzinfo=UTC))
    third_processed = service.dispatch_next_ready(now=datetime(2026, 5, 23, 12, 3, tzinfo=UTC))
    reloaded_policy_state_manager = LiveExecutionPolicyStateManager(tmp_path)
    community_state = reloaded_policy_state_manager.get_community_state("cmp-1", "-100123")
    first_attempts = manager.list_attempts("cmp-1", action_id=first.action_id)
    second_attempts = manager.list_attempts("cmp-1", action_id=second.action_id)
    third_attempts = manager.list_attempts("cmp-1", action_id=third.action_id)

    assert first_processed is not None
    assert first_processed.status is LiveActionStatus.BLOCKED
    assert first_attempts[-1].outcome_code == "write_forbidden"

    assert second_processed is not None
    assert second_processed.status is LiveActionStatus.BLOCKED
    assert second_attempts[-1].outcome_code == "write_forbidden"

    assert third_processed is not None
    assert third_processed.status is LiveActionStatus.BLOCKED
    assert third_attempts[-1].outcome_code == "community_risk_pause"
    assert third_attempts[-1].result_data["reason_codes"] == ["community_risk_pause"]

    assert community_state is not None
    assert community_state.is_paused is True
    assert community_state.recent_write_forbidden_count >= 2
    assert len(messaging_capability.send_calls) == 2


def test_live_execution_service_can_pause_account_and_campaign(tmp_path) -> None:
    manager = LiveExecutionManager(tmp_path / "campaigns")
    campaigns_root = tmp_path / "campaigns"
    campaign_manager = CampaignManager(campaigns_root)
    campaign_manager.ensure_campaign("operator-1", campaign_id="cmp-1", workspace_path=str(campaigns_root / "cmp-1"))
    account_registry = AccountRegistry(tmp_path / "accounts.json")
    account_registry.save_account(AccountRecord(account_id="reader-1", phone="+15551234567", health="active"))
    policy_state_manager = LiveExecutionPolicyStateManager(tmp_path)
    messaging_capability = FakeMessagingCapability(
        [
            CapabilityResult(success=True, data={"message_id": "701", "outcome_code": "success"})
        ]
    )
    service = LiveExecutionService(
        manager,
        messaging_capability=messaging_capability,
        campaign_manager=campaign_manager,
        account_registry=account_registry,
        policy_state_manager=policy_state_manager,
        worker_id="worker-operator-pause",
    )

    assert service.pause_account("reader-1", reason="operator_pause")
    account_action = service.enqueue_action(
        "cmp-1",
        "reader-1",
        action_type=LiveActionType.SEND_GROUP_MESSAGE,
        payload={"chat_id": "-100123", "text": "Hello", "approval_context": _operator_approval_context()},
    )
    blocked_account = service.dispatch_next_ready(now=datetime(2026, 5, 23, 12, 0, tzinfo=UTC))
    account_attempts = manager.list_attempts("cmp-1", action_id=account_action.action_id)

    assert blocked_account is not None
    assert blocked_account.status is LiveActionStatus.BLOCKED
    assert account_attempts[-1].outcome_code == "account_paused"

    assert service.resume_account("reader-1")
    assert service.pause_campaign("cmp-1")
    campaign_action = service.enqueue_action(
        "cmp-1",
        "reader-1",
        action_type=LiveActionType.SEND_GROUP_MESSAGE,
        payload={"chat_id": "-100124", "text": "Hello again", "approval_context": _operator_approval_context()},
    )
    blocked_campaign = service.dispatch_next_ready(now=datetime(2026, 5, 23, 12, 5, tzinfo=UTC))
    campaign_attempts = manager.list_attempts("cmp-1", action_id=campaign_action.action_id)

    assert blocked_campaign is not None
    assert blocked_campaign.status is LiveActionStatus.BLOCKED
    assert campaign_attempts[-1].outcome_code == "campaign_paused"


def test_live_execution_service_pauses_flagged_account_and_promotes_memory(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    manager = LiveExecutionManager(campaigns_root)
    campaign_manager = CampaignManager(campaigns_root)
    campaign = campaign_manager.ensure_campaign(
        "operator-1",
        campaign_id="cmp-1",
        workspace_path=str(campaigns_root / "cmp-1"),
    )
    messaging_capability = FakeMessagingCapability(
        [
            CapabilityResult(
                success=False,
                data={"outcome_code": "account_flagged"},
                error="Telegram flagged this account for the requested action.",
            )
        ]
    )
    policy_state_manager = LiveExecutionPolicyStateManager(tmp_path)
    signal_manager = CampaignSignalManager(campaigns_root)
    work_item_manager = WorkItemManager(campaigns_root)
    service = LiveExecutionService(
        manager,
        messaging_capability=messaging_capability,
        campaign_manager=campaign_manager,
        policy_state_manager=policy_state_manager,
        signal_bridge=CampaignSignalBridge(
            signal_manager,
            observation_work_refresher=ObservationWorkRefresher(signal_manager, work_item_manager),
        ),
        worker_id="worker-flagged-account",
    )
    action = service.enqueue_action(
        "cmp-1",
        "reader-1",
        action_type=LiveActionType.SEND_GROUP_MESSAGE,
        payload={"chat_id": "-100123", "text": "Hello group", "approval_context": _operator_approval_context()},
    )

    processed = service.dispatch_next_ready(now=datetime(2026, 5, 23, 12, 10, tzinfo=UTC))
    attempts = manager.list_attempts("cmp-1", action_id=action.action_id)
    reloaded_policy_state_manager = LiveExecutionPolicyStateManager(tmp_path)
    account_state = reloaded_policy_state_manager.get_account_state("reader-1")
    execution_log = (campaigns_root / campaign.campaign_id / "execution-log.md").read_text(encoding="utf-8")
    next_actions = (campaigns_root / campaign.campaign_id / "next-actions.md").read_text(encoding="utf-8")
    signals = signal_manager.list_for_campaign("cmp-1")
    observation_work = work_item_manager.find_latest("cmp-1", work_type="observation")

    assert processed is not None
    assert processed.status is LiveActionStatus.BLOCKED
    assert attempts[-1].outcome_code == "account_flagged"
    assert account_state is not None
    assert account_state.is_paused is True
    assert "Telegram flagged this account" in account_state.pause_reason
    assert "Managed account `reader-1` was marked flagged" in execution_log
    assert "rested or replaced" in next_actions
    assert len(signals) == 1
    assert signals[0].signal_type == "account_flagged_or_banned"
    assert observation_work is not None
    assert observation_work.context_refs == [f"signal:{signals[0].signal_id}"]


def test_live_execution_service_promotes_community_risk_pause_to_campaign_memory(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    manager = LiveExecutionManager(campaigns_root)
    campaign_manager = CampaignManager(campaigns_root)
    campaign = campaign_manager.ensure_campaign(
        "operator-1",
        campaign_id="cmp-1",
        workspace_path=str(campaigns_root / "cmp-1"),
    )
    messaging_capability = FakeMessagingCapability(
        [
            CapabilityResult(
                success=False,
                data={"outcome_code": "write_forbidden"},
                error="This account is not allowed to post in that chat.",
            ),
            CapabilityResult(
                success=False,
                data={"outcome_code": "write_forbidden"},
                error="Telegram requires additional permissions for that action in this chat.",
            ),
        ]
    )
    policy_state_manager = LiveExecutionPolicyStateManager(tmp_path)
    signal_manager = CampaignSignalManager(campaigns_root)
    work_item_manager = WorkItemManager(campaigns_root)
    service = LiveExecutionService(
        manager,
        messaging_capability=messaging_capability,
        campaign_manager=campaign_manager,
        policy_state_manager=policy_state_manager,
        signal_bridge=CampaignSignalBridge(
            signal_manager,
            observation_work_refresher=ObservationWorkRefresher(signal_manager, work_item_manager),
        ),
        worker_id="worker-community-memory",
    )
    first = service.enqueue_action(
        "cmp-1",
        "reader-1",
        action_type=LiveActionType.SEND_GROUP_MESSAGE,
        payload={"chat_id": "-100123", "text": "Hello group", "approval_context": _operator_approval_context()},
    )
    second = service.enqueue_action(
        "cmp-1",
        "reader-2",
        action_type=LiveActionType.SEND_GROUP_MESSAGE,
        payload={"chat_id": "-100123", "text": "Trying again", "approval_context": _operator_approval_context()},
    )

    first_processed = service.dispatch_next_ready(now=datetime(2026, 5, 23, 12, 0, tzinfo=UTC))
    second_processed = service.dispatch_next_ready(now=datetime(2026, 5, 23, 12, 2, tzinfo=UTC))
    execution_log = (campaigns_root / campaign.campaign_id / "execution-log.md").read_text(encoding="utf-8")
    next_actions = (campaigns_root / campaign.campaign_id / "next-actions.md").read_text(encoding="utf-8")
    signals = signal_manager.list_for_campaign("cmp-1")
    observation_work = work_item_manager.find_latest("cmp-1", work_type="observation")

    assert first_processed is not None
    assert first_processed.status is LiveActionStatus.BLOCKED
    assert second_processed is not None
    assert second_processed.status is LiveActionStatus.BLOCKED
    assert "risk-paused after repeated write-forbidden outcomes" in execution_log
    assert "Pause or avoid community" in next_actions
    assert next_actions.count("Pause or avoid community") == 1
    assert {signal.signal_type for signal in signals} == {
        "community_paused_for_risk",
        "community_write_friction",
    }
    write_friction = next(signal for signal in signals if signal.signal_type == "community_write_friction")
    assert write_friction.occurrence_count == 2
    assert observation_work is not None
