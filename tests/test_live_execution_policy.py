from __future__ import annotations

from datetime import datetime

from telegram_app.external_conversations import (
    ConsentPosture,
    ExternalConversationManager,
    ExternalConversationRecord,
    ExternalConversationStatus,
    ThreadOrigin,
)
from telegram_app.capabilities.mtproto.registry import AccountRecord, AccountRegistry
from telegram_app.live_execution import (
    LiveActionPolicyDecisionType,
    LiveActionPolicyEvaluator,
    LiveActionRecord,
    LiveActionType,
)


def _approval_context(*, action_type: LiveActionType, conversation_id: str) -> dict[str, object]:
    return {
        "approved": True,
        "approval_mode": "autonomous",
        "approval_source": "test_live_execution_policy",
        "authorization_decision": "allowed",
        "authorized_action_type": action_type.value,
        "campaign_id": "cmp-1",
        "conversation_id": conversation_id,
        "context_fingerprint": "ctx-1",
        "authorized_at": "2026-05-23T12:00:00+00:00",
        "autonomous_send_mode": "autonomous_allowed",
        "community_risk_level": "normal",
        "conversation_risk_level": "normal",
        "tone_contract_fingerprint": "tone-1",
    }


def test_policy_allows_valid_dm_reply(tmp_path) -> None:
    conversation_manager = ExternalConversationManager(tmp_path / "campaigns")
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
    evaluator = LiveActionPolicyEvaluator(conversation_manager=conversation_manager)

    decision = evaluator.evaluate(
        LiveActionRecord(
            action_id="act-1",
            campaign_id="cmp-1",
            account_id="reader-1",
            action_type=LiveActionType.SEND_DM_REPLY,
            conversation_id="conv-1",
            payload={
                "chat_id": "user-42",
                "text": "Thanks for reaching out.",
                "approval_context": _approval_context(
                    action_type=LiveActionType.SEND_DM_REPLY,
                    conversation_id="conv-1",
                ),
            },
        )
    )

    assert decision.decision is LiveActionPolicyDecisionType.ALLOWED
    assert decision.reason_codes == []


def test_policy_blocks_dm_reply_without_inbound_first_proof(tmp_path) -> None:
    conversation_manager = ExternalConversationManager(tmp_path / "campaigns")
    conversation_manager.save(
        ExternalConversationRecord(
            conversation_id="conv-2",
            campaign_id="cmp-1",
            account_id="reader-1",
            peer_id="user-42",
            chat_id="user-42",
            thread_origin=ThreadOrigin.DIRECT_INBOUND_DM,
            consent_posture=ConsentPosture.INBOUND_ONLY,
            status=ExternalConversationStatus.ACTIVE,
            external_user_messaged_first=False,
        )
    )
    evaluator = LiveActionPolicyEvaluator(conversation_manager=conversation_manager)

    decision = evaluator.evaluate(
        LiveActionRecord(
            action_id="act-2",
            campaign_id="cmp-1",
            account_id="reader-1",
            action_type=LiveActionType.SEND_DM_REPLY,
            conversation_id="conv-2",
            payload={
                "chat_id": "user-42",
                "text": "Following up.",
                "approval_context": _approval_context(
                    action_type=LiveActionType.SEND_DM_REPLY,
                    conversation_id="conv-2",
                ),
            },
        )
    )

    assert decision.decision is LiveActionPolicyDecisionType.BLOCKED
    assert decision.reason_codes == ["dm_inbound_required"]
    assert decision.risk_level == "critical"


def test_policy_blocks_group_reply_without_reply_lineage(tmp_path) -> None:
    conversation_manager = ExternalConversationManager(tmp_path / "campaigns")
    conversation_manager.save(
        ExternalConversationRecord(
            conversation_id="conv-group",
            campaign_id="cmp-1",
            account_id="reader-1",
            peer_id="member-9",
            chat_id="-100123",
            thread_origin=ThreadOrigin.DIRECT_INBOUND_DM,
            consent_posture=ConsentPosture.GROUP_CONTEXT_ONLY,
            status=ExternalConversationStatus.ACTIVE,
        )
    )
    evaluator = LiveActionPolicyEvaluator(conversation_manager=conversation_manager)

    decision = evaluator.evaluate(
        LiveActionRecord(
            action_id="act-3",
            campaign_id="cmp-1",
            account_id="reader-1",
            action_type=LiveActionType.SEND_GROUP_REPLY,
            conversation_id="conv-group",
            payload={
                "chat_id": "-100123",
                "text": "Appreciate the reply.",
                "approval_context": _approval_context(
                    action_type=LiveActionType.SEND_GROUP_REPLY,
                    conversation_id="conv-group",
                ),
            },
        )
    )

    assert decision.decision is LiveActionPolicyDecisionType.BLOCKED
    assert decision.reason_codes == ["group_reply_lineage_required"]


def test_policy_cools_down_actions_when_account_warmup_budget_is_exhausted(tmp_path) -> None:
    registry = AccountRegistry(tmp_path / "accounts.json")
    registry.save_account(
        AccountRecord(
            account_id="reader-1",
            phone="+15551234567",
            health="active",
            onboarded_at="2026-05-23T09:00:00+00:00",
            metadata={
                "warmup_activity": {
                    "reads": {
                        "window_started_at": "2026-05-23T10:00:00+00:00",
                        "count": 250,
                    }
                }
            },
        )
    )
    evaluator = LiveActionPolicyEvaluator(account_registry=registry)
    now = datetime.fromisoformat("2026-05-23T12:00:00+00:00")

    decision = evaluator.evaluate(
        LiveActionRecord(
            action_id="act-read-1",
            campaign_id="cmp-1",
            account_id="reader-1",
            action_type=LiveActionType.MARK_READ,
            payload={"chat_id": "user-42"},
        ),
        now=now,
    )

    assert decision.decision is LiveActionPolicyDecisionType.COOLDOWN
    assert "warmup_budget_active" in decision.reason_codes
    assert decision.cooldown_until is not None
    assert decision.cooldown_until > now
