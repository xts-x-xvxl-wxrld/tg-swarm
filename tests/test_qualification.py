from __future__ import annotations

from telegram_app.campaigns import CampaignManager
from telegram_app.campaign_signals import CampaignSignalBridge, CampaignSignalCategory, CampaignSignalManager
from telegram_app.engagement_brain import (
    EngagementBrainActionType,
    EngagementBrainContext,
    EngagementBrainDecision,
    EngagementBrainMessage,
    EngagementBrainMessageDirection,
    EngagementBrainProposal,
    EngagementBrainQualificationState,
)
from telegram_app.external_conversations import (
    ConversationBeliefState,
    ConsentPosture,
    ExternalConversationManager,
    ExternalConversationRecord,
    ExternalConversationStatus,
    ThreadOrigin,
)
from telegram_app.models import WorkflowArtifact, WorkflowArtifactKind, WorkflowStage
from telegram_app.qualification import HandoffStatus, QualificationManager, QualificationService


def _build_conversation() -> ExternalConversationRecord:
    return ExternalConversationRecord(
        conversation_id="conv-qualification-1",
        campaign_id="cmp-1",
        account_id="reader-1",
        peer_id="user-42",
        chat_id="user-42",
        thread_origin=ThreadOrigin.DIRECT_INBOUND_DM,
        consent_posture=ConsentPosture.INBOUND_ONLY,
        status=ExternalConversationStatus.ACTIVE,
        external_user_messaged_first=True,
    )


def test_qualification_service_builds_campaign_frame_from_campaign_artifacts(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    campaign_manager = CampaignManager(campaigns_root)
    campaign = campaign_manager.ensure_campaign(
        "operator-1",
        campaign_id="cmp-1",
        workspace_path=str(campaigns_root / "cmp-1"),
    )
    campaign_manager.persist_generated_artifact(
        campaign.campaign_id,
        WorkflowArtifact(
            artifact_id="brief-1",
            kind=WorkflowArtifactKind.CAMPAIGN_BRIEF,
            summary="Brief ready.",
            data={
                "objective": "Book sales calls from Telegram demand.",
                "offer": "Telegram revenue system",
                "target_audience": "founders",
            },
        ),
        stage=WorkflowStage.DISCOVERY,
        summary="Campaign brief ready.",
    )
    campaign_manager.persist_generated_artifact(
        campaign.campaign_id,
        WorkflowArtifact(
            artifact_id="intent-1",
            kind=WorkflowArtifactKind.CAMPAIGN_INTENT,
            summary="Intent ready.",
            data={"qualification_posture": "Only route leads who clearly want help now."},
        ),
        stage=WorkflowStage.DISCOVERY,
        summary="Campaign intent ready.",
    )
    campaign_manager.persist_generated_artifact(
        campaign.campaign_id,
        WorkflowArtifact(
            artifact_id="conversion-1",
            kind=WorkflowArtifactKind.CONVERSION_TARGET,
            summary="External website: https://example.com/apply.",
            data={
                "destination_kind": "external_website",
                "normalized_value": "https://example.com/apply",
                "raw_value": "https://example.com/apply",
                "allowed_action_types": ["share_external_link"],
            },
        ),
        stage=WorkflowStage.DISCOVERY,
        summary="Conversion target ready.",
    )

    service = QualificationService(
        campaign_manager,
        QualificationManager(campaigns_root),
        ExternalConversationManager(campaigns_root),
    )

    frame = service.ensure_frame("cmp-1")
    persisted = QualificationManager(campaigns_root).get_frame("cmp-1")

    assert "founders" in frame.summary
    assert "https://example.com/apply" in frame.summary
    assert frame.handoff_action_types == ["share_external_link"]
    assert persisted is not None
    assert persisted.conversion_target_kind == "external_website"


def test_qualification_service_records_ready_handoff_for_conversion_ready_proposal(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    campaign_manager = CampaignManager(campaigns_root)
    campaign_manager.ensure_campaign(
        "operator-1",
        campaign_id="cmp-1",
        workspace_path=str(campaigns_root / "cmp-1"),
    )
    campaign_manager.persist_generated_artifact(
        "cmp-1",
        WorkflowArtifact(
            artifact_id="brief-1",
            kind=WorkflowArtifactKind.CAMPAIGN_BRIEF,
            summary="Brief ready.",
            data={
                "objective": "Book sales calls from Telegram demand.",
                "offer": "Telegram revenue system",
                "target_audience": "founders",
            },
        ),
        stage=WorkflowStage.DISCOVERY,
        summary="Campaign brief ready.",
    )
    campaign_manager.persist_generated_artifact(
        "cmp-1",
        WorkflowArtifact(
            artifact_id="conversion-1",
            kind=WorkflowArtifactKind.CONVERSION_TARGET,
            summary="Telegram DM: @closer_handle.",
            data={
                "destination_kind": "telegram_dm",
                "normalized_value": "@closer_handle",
                "raw_value": "@closer_handle",
                "allowed_action_types": ["send_dm"],
            },
        ),
        stage=WorkflowStage.DISCOVERY,
        summary="Conversion target ready.",
    )
    conversation_manager = ExternalConversationManager(campaigns_root)
    conversation_manager.save(_build_conversation())
    service = QualificationService(
        campaign_manager,
        QualificationManager(campaigns_root),
        conversation_manager,
    )
    context = EngagementBrainContext(
        conversation=_build_conversation(),
        conversion_target_summary="Telegram DM: @closer_handle.",
        conversion_target_kind="telegram_dm",
        conversion_target_value="@closer_handle",
        approved_offer_facts=["Telegram revenue system"],
        recent_messages=[
            EngagementBrainMessage(
                direction=EngagementBrainMessageDirection.INBOUND,
                text="I'm interested. Can you connect me?",
                message_id="911",
            )
        ],
    )
    proposal = EngagementBrainProposal(
        decision=EngagementBrainDecision.REPLY,
        action_type=EngagementBrainActionType.SEND_DM_REPLY,
        draft_text="I can connect you directly next: @closer_handle.",
        goal="advance_to_conversion",
        qualification_state=EngagementBrainQualificationState.CONVERSION_READY,
    )

    result = service.record_proposal(context, proposal)
    updated_conversation = conversation_manager.get("cmp-1", "conv-qualification-1")

    assert result.handoff_status is HandoffStatus.READY
    assert result.approval_context["handoff_intent"] is True
    assert updated_conversation is not None
    assert updated_conversation.belief_state.intent_posture == "ready_to_route"
    assert updated_conversation.belief_state.commercial_stage == "handoff_ready"
    assert updated_conversation.belief_state.suggested_next_move == "Route the lead via Telegram DM: @closer_handle."
    assert updated_conversation.qualification_status == "conversion_ready"
    assert updated_conversation.handoff_status == "ready"


def test_qualification_service_records_positive_commercial_signals(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    campaign_manager = CampaignManager(campaigns_root)
    campaign_manager.ensure_campaign(
        "operator-1",
        campaign_id="cmp-1",
        workspace_path=str(campaigns_root / "cmp-1"),
    )
    campaign_manager.persist_generated_artifact(
        "cmp-1",
        WorkflowArtifact(
            artifact_id="conversion-1",
            kind=WorkflowArtifactKind.CONVERSION_TARGET,
            summary="Telegram DM: @closer_handle.",
            data={
                "destination_kind": "telegram_dm",
                "normalized_value": "@closer_handle",
                "raw_value": "@closer_handle",
                "allowed_action_types": ["send_dm"],
            },
        ),
        stage=WorkflowStage.DISCOVERY,
        summary="Conversion target ready.",
    )
    conversation_manager = ExternalConversationManager(campaigns_root)
    conversation_manager.save(_build_conversation())
    signal_manager = CampaignSignalManager(campaigns_root)
    service = QualificationService(
        campaign_manager,
        QualificationManager(campaigns_root),
        conversation_manager,
        signal_bridge=CampaignSignalBridge(signal_manager),
    )
    context = EngagementBrainContext(
        conversation=_build_conversation(),
        conversion_target_summary="Telegram DM: @closer_handle.",
        conversion_target_kind="telegram_dm",
        conversion_target_value="@closer_handle",
        recent_messages=[
            EngagementBrainMessage(
                direction=EngagementBrainMessageDirection.INBOUND,
                text="I'm interested. Can you connect me and share pricing?",
                message_id="913",
            )
        ],
    )
    proposal = EngagementBrainProposal(
        decision=EngagementBrainDecision.REPLY,
        action_type=EngagementBrainActionType.SEND_DM_REPLY,
        draft_text="Yes, I can connect you directly.",
        goal="advance_to_conversion",
        qualification_state=EngagementBrainQualificationState.CONVERSION_READY,
    )

    service.record_proposal(context, proposal)
    signal_types = {
        signal.signal_type: signal.category
        for signal in signal_manager.list_for_campaign("cmp-1")
    }

    assert signal_types["clarified_need"] is CampaignSignalCategory.OPPORTUNITY
    assert signal_types["pricing_interest"] is CampaignSignalCategory.OPPORTUNITY
    assert signal_types["conversion_ready_thread"] is CampaignSignalCategory.OPPORTUNITY


def test_qualification_service_preserves_review_owned_belief_state_details(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    campaign_manager = CampaignManager(campaigns_root)
    campaign_manager.ensure_campaign(
        "operator-1",
        campaign_id="cmp-1",
        workspace_path=str(campaigns_root / "cmp-1"),
    )
    campaign_manager.persist_generated_artifact(
        "cmp-1",
        WorkflowArtifact(
            artifact_id="brief-1",
            kind=WorkflowArtifactKind.CAMPAIGN_BRIEF,
            summary="Brief ready.",
            data={
                "objective": "Book sales calls from Telegram demand.",
                "offer": "Telegram revenue system",
                "target_audience": "founders",
            },
        ),
        stage=WorkflowStage.DISCOVERY,
        summary="Campaign brief ready.",
    )
    conversation_manager = ExternalConversationManager(campaigns_root)
    conversation_manager.save(_build_conversation())
    service = QualificationService(
        campaign_manager,
        QualificationManager(campaigns_root),
        conversation_manager,
    )
    context = EngagementBrainContext(
        conversation=_build_conversation(),
        approved_offer_facts=["Telegram revenue system"],
        recent_messages=[
            EngagementBrainMessage(
                direction=EngagementBrainMessageDirection.INBOUND,
                text="This looks interesting, but I'm not sure about the setup.",
                message_id="912",
            )
        ],
    )
    proposal = EngagementBrainProposal(
        decision=EngagementBrainDecision.ASK_CLARIFYING_QUESTION,
        action_type=EngagementBrainActionType.SEND_DM_REPLY,
        draft_text="Happy to help. What setup are you running today?",
        goal="narrow_buying_context",
        qualification_state=EngagementBrainQualificationState.POTENTIAL_FIT,
    )
    review_belief_state = ConversationBeliefState(
        intent_posture="evaluating_fit",
        known_objections=["clarity_concern"],
        known_fit_signals=["asked about setup"],
        unanswered_questions=["What setup are they using today?"],
        commercial_stage="potential_fit",
        last_meaningful_shift="The thread showed fit curiosity but still needs setup clarity.",
        suggested_next_move="Ask one narrow question about the current setup.",
    )

    service.record_proposal(context, proposal, belief_state=review_belief_state)
    updated_conversation = conversation_manager.get("cmp-1", "conv-qualification-1")

    assert updated_conversation is not None
    assert updated_conversation.belief_state.known_objections == ["clarity_concern"]
    assert updated_conversation.belief_state.known_fit_signals == ["asked about setup"]
    assert updated_conversation.belief_state.last_meaningful_shift == "The thread showed fit curiosity but still needs setup clarity."
