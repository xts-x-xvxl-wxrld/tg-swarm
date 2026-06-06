from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from telegram_app.campaigns import CampaignManager
from telegram_app.engagement import (
    EngagementEventKind,
    EngagementEventRecord,
    EngagementRoutingStatus,
    ManagedAccountEngagementStore,
)
from telegram_app.engagement_brain import EngagementBrainContextBuilder
from telegram_app.engagement_triage import CheapInboundTriageService, TriagePromotionDecision
from telegram_app.external_conversations import (
    ConsentPosture,
    ConversationReviewTrigger,
    ConversationReviewTriggerType,
    ExternalConversationManager,
    ExternalConversationRecord,
    ExternalConversationStatus,
    ThreadOrigin,
)
from telegram_app.llm import resolve_model


def test_cheap_triage_uses_summary_model_role_for_llm_path(tmp_path, monkeypatch) -> None:
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
            conversation_id="conv-1",
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
            recent_message_refs=["event:evt-1"],
        )
    )
    engagement_store = ManagedAccountEngagementStore(tmp_path)
    engagement_store.append_inbound_event(
        EngagementEventRecord(
            event_id="evt-1",
            dedupe_key="dedupe-1",
            account_id="reader-1",
            event_kind=EngagementEventKind.INBOUND_DM,
            chat_id="user-42",
            peer_id="user-42",
            sender_id="user-42",
            message_id="401",
            text="Can you send pricing details today?",
            occurred_at=datetime(2026, 5, 24, 12, 0, tzinfo=UTC),
            campaign_id="cmp-1",
            routing_status=EngagementRoutingStatus.ROUTED,
        )
    )
    service = CheapInboundTriageService(
        EngagementBrainContextBuilder(campaign_manager, conversation_manager, engagement_store),
        conversation_manager,
    )
    service._client = MagicMock()
    service._client.messages.create.return_value = SimpleNamespace(
        content=[
            SimpleNamespace(
                text=(
                    "ENGAGEMENT_TRIAGE_JSON\n"
                    '{"interest_level":"high","urgency_level":"high","objection_present":false,'
                    '"low_signal_chatter":false,"review_priority":"high",'
                    '"promotion_decision":"promote_to_deep_review",'
                    '"triage_summary":"Promoted for deeper review."}'
                )
            )
        ]
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    result = service.triage_review(
        "cmp-1",
        "conv-1",
        trigger=ConversationReviewTrigger(
            campaign_id="cmp-1",
            conversation_id="conv-1",
            trigger_type=ConversationReviewTriggerType.INBOUND,
            trigger_source="review_inbound",
            trigger_key="inbound:evt-1",
            eligible_at=datetime(2026, 5, 24, 12, 0, tzinfo=UTC),
        ),
        now=datetime(2026, 5, 24, 12, 1, tzinfo=UTC),
    )

    assert result is not None
    assert result.triage_state.promotion_decision is TriagePromotionDecision.PROMOTE_TO_DEEP_REVIEW
    assert service._client.messages.create.call_args.kwargs["model"] == resolve_model("summary")
