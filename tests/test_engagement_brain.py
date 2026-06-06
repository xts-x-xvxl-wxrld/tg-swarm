from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from telegram_app.autonomous_send import (
    AutonomousSendManager,
    AutonomousSendMode,
    AutonomousSendReviewRecord,
    AutonomousSendReviewStatus,
    AutonomousSendService,
)
from telegram_app.campaigns import CampaignManager
from telegram_app.compiled_intents import CompiledIntentApplicator, CompiledIntentStatus, CompiledIntentStore
from telegram_app.engagement_policy import CampaignEngagementPolicy, CampaignEngagementPolicyManager, CampaignEngagementPolicyService, CommunityBehaviorPolicy, QuietHoursPolicy, ReplyLatencyTier
from telegram_app.engagement import EngagementEventKind, EngagementEventRecord, EngagementRoutingStatus, ManagedAccountEngagementStore
from telegram_app.engagement_brain import (
    AnthropicCommercialReasoningReviewer,
    EngagementBrainActionType,
    EngagementBrainApprovedClaim,
    EngagementBrainCommunityRiskLevel,
    EngagementBrainContext,
    EngagementBrainContextBuilder,
    EngagementBrainConversationRiskLevel,
    EngagementBrainCoordinator,
    EngagementBrainDecision,
    EngagementBrainMessage,
    EngagementBrainMessageDirection,
    EngagementBrainMode,
    EngagementBrainProposal,
    EngagementBrainQualificationState,
    EngagementBrainResolutionStrategy,
    EngagementBrainReview,
    EngagementBrainRunDisposition,
    EngagementBrainRiskLevel,
    EngagementBrainService,
)
from telegram_app.engagement_brain.drafting_skills import (
    DeterministicDraftingSkillSelector,
    DraftingSkillLibrary,
    DraftingSkillSelection,
)
from telegram_app.external_conversations import (
    ConversationBeliefState,
    ConsentPosture,
    ConversationReviewTrigger,
    ConversationReviewTriggerType,
    ExternalConversationManager,
    ExternalConversationRecord,
    ExternalConversationStatus,
    ThreadOrigin,
)
from telegram_app.live_execution import LiveActionType, LiveExecutionManager, LiveExecutionService
from telegram_app.models import WorkflowArtifact, WorkflowArtifactKind, WorkflowStage


def _build_autonomous_send_service(campaigns_root, *, group_reply_allowed: bool = False, dm_reply_allowed: bool = False):  # noqa: ANN001
    manager = AutonomousSendManager(campaigns_root)
    manager.update_posture(
        "cmp-1",
        group_reply_mode=AutonomousSendMode.AUTONOMOUS_ALLOWED if group_reply_allowed else AutonomousSendMode.MANUAL_ONLY,
        dm_reply_mode=AutonomousSendMode.AUTONOMOUS_ALLOWED if dm_reply_allowed else AutonomousSendMode.MANUAL_ONLY,
        updated_by="tests",
    )
    return AutonomousSendService(manager)


def _build_group_conversation() -> ExternalConversationRecord:
    return ExternalConversationRecord(
        conversation_id="conv-group-1",
        campaign_id="cmp-1",
        account_id="reader-1",
        peer_id="member-9",
        chat_id="-100123",
        community_id="-100123",
        thread_origin=ThreadOrigin.GROUP_REPLY,
        consent_posture=ConsentPosture.GROUP_CONTEXT_ONLY,
        status=ExternalConversationStatus.ACTIVE,
        reply_target_message_id="777",
    )


def _build_dm_conversation() -> ExternalConversationRecord:
    return ExternalConversationRecord(
        conversation_id="conv-dm-1",
        campaign_id="cmp-1",
        account_id="reader-1",
        peer_id="user-42",
        chat_id="user-42",
        thread_origin=ThreadOrigin.DIRECT_INBOUND_DM,
        consent_posture=ConsentPosture.INBOUND_ONLY,
        status=ExternalConversationStatus.ACTIVE,
        external_user_messaged_first=True,
    )


def test_anthropic_reviewer_parses_shared_output_proposals() -> None:
    output_text = """ENGAGEMENT_BRAIN_REVIEW_JSON
```json
{
  "decision": "reply",
  "qualification_state": "potential_fit",
  "goal": "qualify_interest",
  "missing_facts": ["pricing_details"],
  "facts_used": ["Asked about pricing."],
  "risk_level": "medium",
  "conversation_risk_level": "needs_clarification",
  "resolution_strategy": "ask_narrowing_question",
  "escalation_reason": "",
  "review_summary": "The thread showed real interest but still needs approved pricing context.",
  "learning_note": "Pricing interest keeps showing up in early DM replies.",
  "belief_state": {
    "intent_posture": "evaluating_fit",
    "known_objections": ["pricing_concern"],
    "known_fit_signals": ["asked about pricing"],
    "unanswered_questions": ["What pricing details are approved for this conversation?"],
    "commercial_stage": "potential_fit",
    "last_meaningful_shift": "The thread showed real interest but still needs approved pricing context.",
    "suggested_next_move": "Ask one narrow question to fill the missing commercial context."
  }
}
```
COMPILED_PROPOSALS_JSON
```json
[
  {
    "kind": "engagement.next_move",
    "summary": "Record the promoted-thread next move recommendation.",
    "payload": {
      "conversation_id": "conv-dm-1",
      "decision": "reply",
      "action_type": "send_dm_reply",
      "goal": "qualify_interest"
    },
    "confidence": 0.95
  },
  {
    "kind": "conversation.update_belief_state",
    "summary": "Persist the updated compact belief state.",
    "payload": {
      "conversation_id": "conv-dm-1",
      "summary": "The thread showed real interest but still needs approved pricing context.",
      "belief_state": {
        "intent_posture": "evaluating_fit",
        "known_objections": ["pricing_concern"],
        "known_fit_signals": ["asked about pricing"],
        "unanswered_questions": ["What pricing details are approved for this conversation?"],
        "commercial_stage": "potential_fit",
        "last_meaningful_shift": "The thread showed real interest but still needs approved pricing context.",
        "suggested_next_move": "Ask one narrow question to fill the missing commercial context."
      }
    },
    "confidence": 0.95
  }
]
```"""
    fake_content_block = MagicMock()
    fake_content_block.text = output_text
    fake_response = MagicMock()
    fake_response.content = [fake_content_block]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = fake_response

    context = EngagementBrainContext(conversation=_build_dm_conversation())

    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
        with patch("telegram_app.engagement_brain.service.anthropic.Anthropic", return_value=mock_client):
            reviewer = AnthropicCommercialReasoningReviewer()
            review = reviewer.review(context)

    assert review is not None
    assert review.decision is EngagementBrainDecision.REPLY
    assert [proposal["kind"] for proposal in review.compiled_proposal_payloads] == [
        "engagement.next_move",
        "conversation.update_belief_state",
    ]


def test_context_derives_group_mode_from_group_reply_thread() -> None:
    context = EngagementBrainContext(conversation=_build_group_conversation())

    assert context.mode is EngagementBrainMode.GROUP


def test_service_ignores_low_signal_inbound_message() -> None:
    service = EngagementBrainService()
    context = EngagementBrainContext(
        conversation=_build_dm_conversation(),
        recent_messages=[
            EngagementBrainMessage(
                direction=EngagementBrainMessageDirection.INBOUND,
                text="ok",
                message_id="401",
            )
        ],
    )

    proposal = service.propose(context)

    assert proposal.decision is EngagementBrainDecision.IGNORE
    assert proposal.action_type is EngagementBrainActionType.NONE
    assert proposal.goal == "avoid_needy_follow_up"


def test_service_asks_clarifying_question_when_pricing_fact_is_missing() -> None:
    service = EngagementBrainService()
    context = EngagementBrainContext(
        conversation=_build_dm_conversation(),
        campaign_brief="We help service businesses tighten outbound execution.",
        strategy_notes=["The offer works best when the lead wants cleaner conversion flow."],
        recent_messages=[
            EngagementBrainMessage(
                direction=EngagementBrainMessageDirection.INBOUND,
                text="How much does this cost?",
                message_id="501",
            )
        ],
    )

    proposal = service.propose(context)

    assert proposal.decision is EngagementBrainDecision.ASK_CLARIFYING_QUESTION
    assert proposal.action_type is EngagementBrainActionType.SEND_DM_REPLY
    assert "What are you mainly trying to get done right now?" in proposal.draft_text
    assert proposal.missing_facts == ["pricing_details"]
    assert proposal.resolution_strategy is EngagementBrainResolutionStrategy.ASK_NARROWING_QUESTION


def test_service_escalates_high_stakes_request_without_sending() -> None:
    service = EngagementBrainService()
    context = EngagementBrainContext(
        conversation=_build_dm_conversation(),
        approved_offer_facts=["We support operators who want cleaner Telegram-driven lead flow."],
        recent_messages=[
            EngagementBrainMessage(
                direction=EngagementBrainMessageDirection.INBOUND,
                text="Can you guarantee refunds in the contract?",
                message_id="601",
            )
        ],
    )

    proposal = service.propose(context)

    assert proposal.decision is EngagementBrainDecision.ESCALATE
    assert proposal.action_type is EngagementBrainActionType.NONE
    assert proposal.escalation_reason == "high_stakes_request"


def test_service_returns_group_reply_with_telegram_native_hints() -> None:
    service = EngagementBrainService()
    context = EngagementBrainContext(
        conversation=_build_group_conversation(),
        approved_offer_facts=["We help brands turn Telegram attention into cleaner DM demand."],
        recent_messages=[
            EngagementBrainMessage(
                direction=EngagementBrainMessageDirection.INBOUND,
                text="Does this actually work for sales?",
                message_id="701",
            )
        ],
    )

    proposal = service.propose(context)

    assert proposal.decision is EngagementBrainDecision.REPLY
    assert proposal.action_type is EngagementBrainActionType.SEND_GROUP_REPLY
    assert proposal.qualification_state is EngagementBrainQualificationState.POTENTIAL_FIT
    assert "light_emoji_ok" in proposal.presentation_hints
    assert "optional_media_consideration" in proposal.presentation_hints


def test_proposal_validation_requires_draft_text_for_send_action() -> None:
    try:
        EngagementBrainProposal(
            decision=EngagementBrainDecision.REPLY,
            action_type=EngagementBrainActionType.SEND_DM_REPLY,
        )
    except ValueError as error:
        assert "non-empty draft text" in str(error)
    else:
        raise AssertionError("Expected send proposals without draft text to fail validation.")


class FakeBrainService:
    def __init__(self, proposal: EngagementBrainProposal) -> None:
        self._proposal = proposal

    def propose(self, context: EngagementBrainContext) -> EngagementBrainProposal:
        return self._proposal


class FakeCommercialReviewer:
    def __init__(self, review: EngagementBrainReview) -> None:
        self._review = review

    def review(self, context: EngagementBrainContext) -> EngagementBrainReview:
        return self._review


class FakeDraftGenerator:
    def __init__(self, text: str) -> None:
        self._text = text

    def generate(self, request) -> object:  # noqa: ANN001
        from telegram_app.engagement_brain.service import DraftGenerationResult

        return DraftGenerationResult(
            text=self._text,
            facts_used=["We help founders turn Telegram interest into cleaner follow-up demand."],
            approved_claim_ids_used=["claim_peer_fit"],
            presentation_hints=["telegram_formatting_ok"],
        )


class CapturingDraftGenerator:
    def __init__(self, text: str) -> None:
        self._text = text
        self.last_request = None

    def generate(self, request) -> object:  # noqa: ANN001
        from telegram_app.engagement_brain.service import DraftGenerationResult

        self.last_request = request
        return DraftGenerationResult(
            text=self._text,
            facts_used=[],
            approved_claim_ids_used=[],
            presentation_hints=["telegram_formatting_ok"],
        )


class FakeDraftingSkillSelector:
    def __init__(self, selection: DraftingSkillSelection | None) -> None:
        self._selection = selection

    def select(
        self,
        context,  # noqa: ANN001
        *,
        decision,  # noqa: ANN001
        qualification_state,  # noqa: ANN001
        goal,  # noqa: ANN001
        missing_facts,  # noqa: ANN001
        risk_level,  # noqa: ANN001
        conversation_risk_level,  # noqa: ANN001
    ) -> DraftingSkillSelection | None:
        return self._selection


class SequenceSampler:
    def __init__(self, *values: int) -> None:
        self._values = list(values)

    def __call__(self, minimum_value: int, maximum_value: int) -> int:
        if not self._values:
            raise AssertionError("No sampler value remained for this test call.")
        value = self._values.pop(0)
        assert minimum_value <= value <= maximum_value
        return value


def test_context_builder_loads_campaign_and_recent_message_context(tmp_path) -> None:
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
            summary="Sell a Telegram-native growth system to founders.",
            data={
                "objective": "Sell more through Telegram conversations.",
                "offer": "Telegram-native growth system",
                "target_audience": "founders",
                "geography": "Europe",
            },
        ),
        stage=WorkflowStage.DISCOVERY,
        summary="Campaign brief ready.",
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
    campaign_manager.persist_generated_artifact(
        campaign.campaign_id,
        WorkflowArtifact(
            artifact_id="shortlist-1",
            kind=WorkflowArtifactKind.COMMUNITY_SHORTLIST,
            summary="Shortlisted founder communities.",
            data={
                "communities": [
                    {
                        "community_id": "-100123",
                        "verification_state": "live_confirmed",
                        "evidence_summary": "Strong founder chatter around GTM and conversion.",
                    }
                ]
            },
        ),
        stage=WorkflowStage.DISCOVERY,
        summary="Shortlist ready.",
    )
    campaign_manager.persist_generated_artifact(
        campaign.campaign_id,
        WorkflowArtifact(
            artifact_id="strategy-1",
            kind=WorkflowArtifactKind.STRATEGY_PLAYBOOK,
            summary="Lead with proof and sharp founder messaging.",
            data={
                "campaign_strategy_summary": "Lead with proof and concise social credibility.",
                "voice_profile": {
                    "brand_name": "SignalFlow",
                    "tone_descriptors": ["peer", "clear", "concise"],
                    "style_do": ["sound human", "lead with relevance"],
                    "style_avoid": ["hard close language"],
                    "cta_style": "soft_question",
                    "emoji_policy": "light",
                    "evidence_style": "claim_only_what_is_approved",
                },
                "approved_claims": [
                    {
                        "claim_id": "claim_peer_fit",
                        "text": "We help founders turn Telegram interest into cleaner follow-up demand.",
                        "evidence_basis": "campaign_brief",
                    }
                ],
                "forbidden_claims": [
                    {
                        "label": "guaranteed_outcomes",
                        "instruction": "Do not promise guaranteed results.",
                    }
                ],
                "communities": [
                    {
                        "community_id": "-100123",
                        "messaging_angle": "Peer-to-peer founder insight",
                        "risk_notes": "Do not overpitch in public threads.",
                        "community_risk_level": "guarded",
                        "tone_guidance": "Sound like a founder-peer, not a closer.",
                        "response_posture": "value_first",
                        "allowed_cta": "Invite a short follow-up only when asked.",
                        "direct_response_rule": "Answer simple fit questions directly.",
                        "clarifying_question_rule": "Ask one narrow question when pricing or setup detail is missing.",
                        "escalation_rule": "Escalate if someone asks for guarantees or legal assurances.",
                        "approved_claim_ids": ["claim_peer_fit"],
                        "forbidden_claim_labels": ["guaranteed_outcomes"],
                        "risky_topics": ["guarantees", "refunds"],
                    }
                ],
            },
        ),
        stage=WorkflowStage.STRATEGY,
        summary="Strategy ready.",
    )

    conversation_manager = ExternalConversationManager(campaigns_root)
    conversation_manager.save(
        ExternalConversationRecord(
            conversation_id="conv-1",
            campaign_id="cmp-1",
            account_id="reader-1",
            peer_id="member-9",
            chat_id="-100123",
            community_id="-100123",
            thread_origin=ThreadOrigin.GROUP_REPLY,
            consent_posture=ConsentPosture.GROUP_CONTEXT_ONLY,
            status=ExternalConversationStatus.ACTIVE,
            last_event_id="evt-1",
            recent_message_refs=["event:evt-1"],
            summary="Founder asked whether this works for sales.",
            belief_state=ConversationBeliefState(
                intent_posture="evaluating_fit",
                known_fit_signals=["asked whether the offer works for sales"],
                commercial_stage="potential_fit",
                last_meaningful_shift="Conversation shows potential fit with the campaign audience.",
                suggested_next_move="Answer helpfully without pushing too hard in public.",
            ),
        )
    )
    engagement_store = ManagedAccountEngagementStore(tmp_path)
    engagement_store.append_inbound_event(
        EngagementEventRecord(
            event_id="evt-1",
            dedupe_key="dedupe-1",
            account_id="reader-1",
            event_kind=EngagementEventKind.GROUP_REPLY,
            chat_id="-100123",
            peer_id="member-9",
            sender_id="member-9",
            message_id="701",
            text="Does this actually work for sales?",
            occurred_at=datetime(2026, 5, 23, 12, 0, tzinfo=UTC),
            campaign_id="cmp-1",
            community_id="-100123",
            routing_status=EngagementRoutingStatus.ROUTED,
        )
    )

    builder = EngagementBrainContextBuilder(campaign_manager, conversation_manager, engagement_store)
    context = builder.build("cmp-1", "conv-1")

    assert context is not None
    assert "Sell more through Telegram conversations." in context.campaign_brief
    assert context.conversion_target_kind == "external_website"
    assert context.conversion_target_value == "https://example.com/apply"
    assert "Telegram-native growth system" in context.approved_offer_facts
    assert "Peer-to-peer founder insight" in context.strategy_notes
    assert "Strong founder chatter around GTM and conversion." in context.community_notes
    assert context.voice_profile.brand_name == "SignalFlow"
    assert context.community_risk_level.value == "guarded"
    assert context.community_guidance is not None
    assert context.community_guidance.tone_guidance == "Sound like a founder-peer, not a closer."
    assert context.allowed_claims()[0].claim_id == "claim_peer_fit"
    assert context.effective_forbidden_claims()[0].label == "guaranteed_outcomes"
    assert context.tone_contract_fingerprint
    assert "Conversation shows potential fit with the campaign audience." in context.conversation_summary
    assert "stage:potential_fit" in context.conversation_posture
    assert context.recent_messages[-1].text == "Does this actually work for sales?"


def test_service_separates_commercial_review_from_bounded_drafting() -> None:
    review = EngagementBrainReview(
        decision=EngagementBrainDecision.ASK_CLARIFYING_QUESTION,
        qualification_state=EngagementBrainQualificationState.POTENTIAL_FIT,
        goal="narrow_buying_context",
        missing_facts=["pricing_details"],
        facts_used=["We help founders turn Telegram interest into cleaner follow-up demand."],
        risk_level=EngagementBrainRiskLevel.MEDIUM,
        community_risk_level=EngagementBrainCommunityRiskLevel.GUARDED,
        conversation_risk_level=EngagementBrainConversationRiskLevel.NEEDS_CLARIFICATION,
        resolution_strategy=EngagementBrainResolutionStrategy.ASK_NARROWING_QUESTION,
        belief_state=ConversationBeliefState(
            intent_posture="evaluating_fit",
            known_fit_signals=["asked about pricing"],
            unanswered_questions=["What pricing details are approved for this conversation?"],
            commercial_stage="potential_fit",
            last_meaningful_shift="The thread showed real interest but still needs approved pricing context.",
            suggested_next_move="Ask one narrow question to fill the missing commercial context.",
        ),
    )
    service = EngagementBrainService(
        reviewer=FakeCommercialReviewer(review),
        draft_generator=FakeDraftGenerator("Happy to help. What are you mainly trying to get done right now?"),
    )
    context = EngagementBrainContext(
        conversation=_build_dm_conversation(),
        approved_claims=[
            EngagementBrainApprovedClaim(
                claim_id="claim_peer_fit",
                text="We help founders turn Telegram interest into cleaner follow-up demand.",
            )
        ],
        recent_messages=[
            EngagementBrainMessage(
                direction=EngagementBrainMessageDirection.INBOUND,
                text="How much does this cost?",
                message_id="review-split-1",
            )
        ],
    )

    proposal = service.propose(context)

    assert proposal.decision is EngagementBrainDecision.ASK_CLARIFYING_QUESTION
    assert proposal.action_type is EngagementBrainActionType.SEND_DM_REPLY
    assert proposal.goal == "narrow_buying_context"
    assert proposal.missing_facts == ["pricing_details"]
    assert proposal.resolution_strategy is EngagementBrainResolutionStrategy.ASK_NARROWING_QUESTION
    assert proposal.draft_text == "Happy to help. What are you mainly trying to get done right now?"


def test_context_builder_reconstructs_outbound_text_timing_and_assets(tmp_path) -> None:
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
            last_outbound_message_id="501",
            recent_message_refs=["outbound:501", "event:evt-1"],
        )
    )
    engagement_store = ManagedAccountEngagementStore(tmp_path)
    engagement_store.record_outbound_message(
        "reader-1",
        "user-42",
        "501",
        sent_at=datetime(2026, 5, 23, 12, 0, tzinfo=UTC),
        campaign_id="cmp-1",
        conversation_id="conv-1",
        text="Happy to send more detail if that helps.",
        asset_refs=["asset-brief-1"],
    )
    engagement_store.append_inbound_event(
        EngagementEventRecord(
            event_id="evt-1",
            dedupe_key="dedupe-1",
            account_id="reader-1",
            event_kind=EngagementEventKind.INBOUND_DM,
            chat_id="user-42",
            peer_id="user-42",
            sender_id="user-42",
            message_id="601",
            text="Yes, send it over.",
            occurred_at=datetime(2026, 5, 23, 12, 5, tzinfo=UTC),
            campaign_id="cmp-1",
            routing_status=EngagementRoutingStatus.ROUTED,
        )
    )

    builder = EngagementBrainContextBuilder(campaign_manager, conversation_manager, engagement_store)
    context = builder.build("cmp-1", "conv-1")

    assert context is not None
    assert len(context.recent_messages) == 2
    assert context.recent_messages[0].direction is EngagementBrainMessageDirection.OUTBOUND
    assert context.recent_messages[0].text == "Happy to send more detail if that helps."
    assert context.recent_messages[0].sent_at == datetime(2026, 5, 23, 12, 0, tzinfo=UTC)
    assert context.recent_messages[0].asset_refs == ["asset-brief-1"]
    assert context.recent_messages[1].direction is EngagementBrainMessageDirection.INBOUND
    assert context.recent_messages[1].text == "Yes, send it over."


def test_service_asks_clarifying_question_in_high_risk_group_thread() -> None:
    service = EngagementBrainService()
    context = EngagementBrainContext(
        conversation=_build_group_conversation(),
        community_risk_level=EngagementBrainCommunityRiskLevel.HIGH,
        approved_claims=[
            EngagementBrainApprovedClaim(
                claim_id="claim_founder_fit",
                text="We help founders tighten follow-up from Telegram demand.",
            )
        ],
        recent_messages=[
            EngagementBrainMessage(
                direction=EngagementBrainMessageDirection.INBOUND,
                text="Interested, can you send the link?",
                message_id="risk-1",
            )
        ],
    )

    proposal = service.propose(context)

    assert proposal.decision is EngagementBrainDecision.ASK_CLARIFYING_QUESTION
    assert proposal.action_type is EngagementBrainActionType.SEND_GROUP_REPLY
    assert proposal.community_risk_level is EngagementBrainCommunityRiskLevel.HIGH
    assert proposal.conversation_risk_level is EngagementBrainConversationRiskLevel.SENSITIVE


def test_service_uses_conversion_target_hint_for_conversion_ready_dm_reply() -> None:
    service = EngagementBrainService()
    context = EngagementBrainContext(
        conversation=_build_dm_conversation(),
        conversion_target_summary="External website: https://example.com/apply.",
        conversion_target_kind="external_website",
        conversion_target_value="https://example.com/apply",
        approved_offer_facts=["We help operators book more qualified sales calls from Telegram demand."],
        recent_messages=[
            EngagementBrainMessage(
                direction=EngagementBrainMessageDirection.INBOUND,
                text="I'm interested. Where do I sign up?",
                message_id="811",
            )
        ],
    )

    proposal = service.propose(context)

    assert proposal.decision is EngagementBrainDecision.REPLY
    assert proposal.qualification_state is EngagementBrainQualificationState.CONVERSION_READY
    assert "https://example.com/apply" in proposal.draft_text


def test_service_passes_selected_drafting_skill_to_generator_and_records_hint() -> None:
    library = DraftingSkillLibrary()
    selection = DraftingSkillSelection(
        primary_skill=library.load_packet("sales-telegram-objection-reply"),
        selection_reason="Clear pushback makes the objection-reply packet the best fit.",
        confidence=0.91,
    )
    generator = CapturingDraftGenerator("Fair question. What part feels unclear or risky to you?")
    service = EngagementBrainService(
        reviewer=FakeCommercialReviewer(
            EngagementBrainReview(
                decision=EngagementBrainDecision.REPLY,
                qualification_state=EngagementBrainQualificationState.OBJECTION_OR_UNCLEAR,
                goal="handle_objection",
                risk_level=EngagementBrainRiskLevel.MEDIUM,
                community_risk_level=EngagementBrainCommunityRiskLevel.LOW,
                conversation_risk_level=EngagementBrainConversationRiskLevel.SENSITIVE,
                resolution_strategy=EngagementBrainResolutionStrategy.ANSWER_SAFE_PORTION,
            )
        ),
        draft_generator=generator,
        drafting_skill_selector=FakeDraftingSkillSelector(selection),
    )
    context = EngagementBrainContext(
        conversation=_build_dm_conversation(),
        recent_messages=[
            EngagementBrainMessage(
                direction=EngagementBrainMessageDirection.INBOUND,
                text="Not sure this is legit tbh",
                message_id="skill-select-1",
            )
        ],
    )

    proposal = service.propose(context)

    assert generator.last_request is not None
    assert generator.last_request.drafting_skill_selection is not None
    assert generator.last_request.drafting_skill_selection.primary_skill is not None
    assert (
        generator.last_request.drafting_skill_selection.primary_skill.skill_name
        == "sales-telegram-objection-reply"
    )
    assert "drafting_skill:sales-telegram-objection-reply" in proposal.presentation_hints


def test_deterministic_drafting_skill_selector_prefers_objection_skill() -> None:
    selector = DeterministicDraftingSkillSelector()
    context = EngagementBrainContext(
        conversation=_build_dm_conversation(),
        recent_messages=[
            EngagementBrainMessage(
                direction=EngagementBrainMessageDirection.INBOUND,
                text="Too expensive and not sure I trust it",
                message_id="selector-objection-1",
            )
        ],
    )

    selection = selector.select(
        context,
        decision=EngagementBrainDecision.REPLY,
        qualification_state=EngagementBrainQualificationState.OBJECTION_OR_UNCLEAR,
        goal="handle_objection",
        missing_facts=[],
        risk_level=EngagementBrainRiskLevel.MEDIUM,
        conversation_risk_level=EngagementBrainConversationRiskLevel.SENSITIVE,
    )

    assert selection is not None
    assert selection.primary_skill is not None
    assert selection.primary_skill.skill_name == "sales-telegram-objection-reply"


def test_coordinator_persists_review_owned_belief_state_without_qualification_service(tmp_path) -> None:
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
            conversation_id="conv-belief-owned",
            campaign_id="cmp-1",
            account_id="reader-1",
            peer_id="user-42",
            chat_id="user-42",
            thread_origin=ThreadOrigin.DIRECT_INBOUND_DM,
            consent_posture=ConsentPosture.INBOUND_ONLY,
            status=ExternalConversationStatus.ACTIVE,
            external_user_messaged_first=True,
            last_event_id="evt-belief-1",
            recent_message_refs=["event:evt-belief-1"],
        )
    )
    engagement_store = ManagedAccountEngagementStore(tmp_path)
    engagement_store.append_inbound_event(
        EngagementEventRecord(
            event_id="evt-belief-1",
            dedupe_key="dedupe-belief-1",
            account_id="reader-1",
            event_kind=EngagementEventKind.INBOUND_DM,
            chat_id="user-42",
            peer_id="user-42",
            sender_id="user-42",
            message_id="belief-1",
            text="Could you share pricing details?",
            occurred_at=datetime(2026, 5, 23, 13, 0, tzinfo=UTC),
            campaign_id="cmp-1",
            routing_status=EngagementRoutingStatus.ROUTED,
        )
    )
    review = EngagementBrainReview(
        decision=EngagementBrainDecision.IGNORE,
        qualification_state=EngagementBrainQualificationState.POTENTIAL_FIT,
        goal="leave_space_for_now",
        community_risk_level=EngagementBrainCommunityRiskLevel.LOW,
        belief_state=ConversationBeliefState(
            intent_posture="evaluating_fit",
            known_fit_signals=["asked about pricing"],
            commercial_stage="potential_fit",
            last_meaningful_shift="The thread showed enough commercial curiosity to track as fit.",
            suggested_next_move="Wait for the next meaningful reply before sending.",
        ),
    )
    service = EngagementBrainService(
        reviewer=FakeCommercialReviewer(review),
        draft_generator=FakeDraftGenerator("Unused draft."),
    )
    coordinator = EngagementBrainCoordinator(
        EngagementBrainContextBuilder(campaign_manager, conversation_manager, engagement_store),
        conversation_manager,
        LiveExecutionService(
            LiveExecutionManager(campaigns_root),
            conversation_manager=conversation_manager,
            campaign_manager=campaign_manager,
            worker_id="worker-live-belief",
        ),
        _build_autonomous_send_service(campaigns_root, dm_reply_allowed=True),
        brain_service=service,
    )

    outcome = coordinator.review_conversation("cmp-1", "conv-belief-owned")
    updated = conversation_manager.get("cmp-1", "conv-belief-owned")

    assert outcome is not None
    assert outcome.disposition is EngagementBrainRunDisposition.NO_ACTION
    assert updated is not None
    assert updated.belief_state.intent_posture == "evaluating_fit"
    assert updated.belief_state.known_fit_signals == ["asked about pricing"]
    assert updated.belief_state.last_meaningful_shift == "The thread showed enough commercial curiosity to track as fit."


def test_coordinator_persists_compiled_review_outputs_before_queueing(tmp_path) -> None:
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
            conversation_id="conv-compiled-review-1",
            campaign_id="cmp-1",
            account_id="reader-1",
            peer_id="user-42",
            chat_id="user-42",
            thread_origin=ThreadOrigin.DIRECT_INBOUND_DM,
            consent_posture=ConsentPosture.INBOUND_ONLY,
            status=ExternalConversationStatus.ACTIVE,
            external_user_messaged_first=True,
            last_event_id="evt-compiled-review-1",
            recent_message_refs=["event:evt-compiled-review-1"],
        )
    )
    engagement_store = ManagedAccountEngagementStore(tmp_path)
    engagement_store.append_inbound_event(
        EngagementEventRecord(
            event_id="evt-compiled-review-1",
            dedupe_key="dedupe-compiled-review-1",
            account_id="reader-1",
            event_kind=EngagementEventKind.INBOUND_DM,
            chat_id="user-42",
            peer_id="user-42",
            sender_id="user-42",
            message_id="belief-compiled-1",
            text="Could you share pricing details?",
            occurred_at=datetime(2026, 5, 23, 13, 0, tzinfo=UTC),
            campaign_id="cmp-1",
            routing_status=EngagementRoutingStatus.ROUTED,
        )
    )
    review = EngagementBrainReview(
        decision=EngagementBrainDecision.REPLY,
        qualification_state=EngagementBrainQualificationState.POTENTIAL_FIT,
        goal="qualify_interest",
        learning_note="Pricing interest keeps showing up in early DM replies.",
        community_risk_level=EngagementBrainCommunityRiskLevel.LOW,
        belief_state=ConversationBeliefState(
            intent_posture="evaluating_fit",
            known_fit_signals=["asked about pricing"],
            commercial_stage="potential_fit",
            last_meaningful_shift="The thread showed enough commercial curiosity to track as fit.",
            suggested_next_move="Ask one narrow qualifying question before pushing a CTA.",
        ),
    )
    compiled_intent_store = CompiledIntentStore(campaigns_root)
    compiled_intent_applicator = CompiledIntentApplicator(
        campaign_manager=campaign_manager,
        conversation_manager=conversation_manager,
    )
    coordinator = EngagementBrainCoordinator(
        EngagementBrainContextBuilder(campaign_manager, conversation_manager, engagement_store),
        conversation_manager,
        LiveExecutionService(
            LiveExecutionManager(campaigns_root),
            conversation_manager=conversation_manager,
            worker_id="worker-live-compiled-review",
        ),
        _build_autonomous_send_service(campaigns_root, dm_reply_allowed=True),
        brain_service=EngagementBrainService(
            reviewer=FakeCommercialReviewer(review),
            draft_generator=FakeDraftGenerator("Happy to share more. What are you mainly trying to solve right now?"),
        ),
        compiled_intent_store=compiled_intent_store,
        compiled_intent_applicator=compiled_intent_applicator,
    )

    outcome = coordinator.review_conversation("cmp-1", "conv-compiled-review-1")
    stored_intents = compiled_intent_store.list_for_campaign("cmp-1")
    kinds = {intent.kind for intent in stored_intents}
    updated = conversation_manager.get("cmp-1", "conv-compiled-review-1")

    assert outcome is not None
    assert outcome.disposition is EngagementBrainRunDisposition.ENQUEUED
    assert kinds >= {"engagement.next_move", "conversation.update_belief_state", "memory.note"}
    assert all(intent.status is CompiledIntentStatus.APPLIED for intent in stored_intents)
    assert updated is not None
    assert updated.belief_state.intent_posture == "evaluating_fit"
    assert "Pricing interest keeps showing up" in (
        campaigns_root / "cmp-1" / "next-actions.md"
    ).read_text(encoding="utf-8")


def test_coordinator_enqueues_actionable_brain_proposal(tmp_path) -> None:
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
            conversation_id="conv-dm-queued",
            campaign_id="cmp-1",
            account_id="reader-1",
            peer_id="user-42",
            chat_id="user-42",
            thread_origin=ThreadOrigin.DIRECT_INBOUND_DM,
            consent_posture=ConsentPosture.INBOUND_ONLY,
            status=ExternalConversationStatus.ACTIVE,
            external_user_messaged_first=True,
            last_event_id="evt-dm-1",
            recent_message_refs=["event:evt-dm-1"],
        )
    )
    engagement_store = ManagedAccountEngagementStore(tmp_path)
    engagement_store.append_inbound_event(
        EngagementEventRecord(
            event_id="evt-dm-1",
            dedupe_key="dedupe-dm-1",
            account_id="reader-1",
            event_kind=EngagementEventKind.INBOUND_DM,
            chat_id="user-42",
            peer_id="user-42",
            sender_id="user-42",
            message_id="801",
            text="Interested, tell me more.",
            occurred_at=datetime(2026, 5, 23, 12, 5, tzinfo=UTC),
            campaign_id="cmp-1",
            routing_status=EngagementRoutingStatus.ROUTED,
        )
    )
    context_builder = EngagementBrainContextBuilder(campaign_manager, conversation_manager, engagement_store)
    execution_manager = LiveExecutionManager(campaigns_root)
    live_execution_service = LiveExecutionService(
        execution_manager,
        conversation_manager=conversation_manager,
        worker_id="worker-brain-queue",
    )
    proposal = EngagementBrainProposal(
        decision=EngagementBrainDecision.REPLY,
        action_type=EngagementBrainActionType.SEND_DM_REPLY,
        draft_text="There could be a fit. What are you mainly trying to solve right now?",
        goal="qualify_interest",
    )
    coordinator = EngagementBrainCoordinator(
        context_builder,
        conversation_manager,
        live_execution_service,
        _build_autonomous_send_service(campaigns_root, dm_reply_allowed=True),
        brain_service=FakeBrainService(proposal),
    )

    result = coordinator.review_conversation("cmp-1", "conv-dm-queued")
    queued_actions = execution_manager.list_for_campaign("cmp-1")
    updated_conversation = conversation_manager.get("cmp-1", "conv-dm-queued")

    assert result is not None
    assert result.disposition is EngagementBrainRunDisposition.ENQUEUED
    assert len(queued_actions) == 1
    assert queued_actions[0].action_type is LiveActionType.SEND_DM_REPLY
    assert queued_actions[0].payload["text"] == proposal.draft_text
    assert queued_actions[0].payload["approval_context"]["approval_mode"] == "autonomous"
    assert updated_conversation is not None
    assert updated_conversation.next_action_type == "queued_send_dm_reply"


def test_coordinator_enqueues_delayed_reply_with_campaign_policy_timing(tmp_path) -> None:
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
            artifact_id="strategy-delay-1",
            kind=WorkflowArtifactKind.STRATEGY_PLAYBOOK,
            summary="Hobby rooms should feel slower and less optimized.",
            data={
                "communities": [
                    {
                        "community_id": "-100123",
                        "chat_id": "-100123",
                        "community_type": "hobby",
                    }
                ]
            },
        ),
        stage=WorkflowStage.STRATEGY,
        summary="Strategy with community timing hints.",
    )
    conversation_manager = ExternalConversationManager(campaigns_root)
    conversation_manager.save(
        ExternalConversationRecord(
            conversation_id="conv-delay-1",
            campaign_id="cmp-1",
            account_id="reader-1",
            peer_id="member-9",
            chat_id="-100123",
            community_id="-100123",
            thread_origin=ThreadOrigin.GROUP_REPLY,
            consent_posture=ConsentPosture.GROUP_CONTEXT_ONLY,
            status=ExternalConversationStatus.ACTIVE,
            reply_target_message_id="777",
            last_event_id="evt-delay-1",
            recent_message_refs=["event:evt-delay-1"],
        )
    )
    engagement_store = ManagedAccountEngagementStore(tmp_path)
    engagement_store.append_inbound_event(
        EngagementEventRecord(
            event_id="evt-delay-1",
            dedupe_key="dedupe-delay-1",
            account_id="reader-1",
            event_kind=EngagementEventKind.GROUP_REPLY,
            chat_id="-100123",
            peer_id="member-9",
            sender_id="member-9",
            message_id="701",
            text="what does this actually do?",
            occurred_at=datetime(2026, 5, 23, 22, 30, tzinfo=UTC),
            campaign_id="cmp-1",
            community_id="-100123",
            routing_status=EngagementRoutingStatus.ROUTED,
        )
    )
    policy_manager = CampaignEngagementPolicyManager(campaigns_root)
    policy_manager.save_policy(
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
                "hobby": CommunityBehaviorPolicy(
                    reply_latency_tier=ReplyLatencyTier.LONG_DELAY,
                    negative_signal_tolerance="low",
                )
            },
        ),
    )
    context_builder = EngagementBrainContextBuilder(campaign_manager, conversation_manager, engagement_store)
    execution_manager = LiveExecutionManager(campaigns_root)
    policy_service = CampaignEngagementPolicyService(policy_manager, sample_int=SequenceSampler(900, 300))
    live_execution_service = LiveExecutionService(
        execution_manager,
        conversation_manager=conversation_manager,
        engagement_policy_service=policy_service,
        worker_id="worker-brain-delayed",
    )
    proposal = EngagementBrainProposal(
        decision=EngagementBrainDecision.REPLY,
        action_type=EngagementBrainActionType.SEND_GROUP_REPLY,
        draft_text="Mostly helps clean up how Telegram interest turns into real follow-up.",
        goal="advance_thread",
    )
    coordinator = EngagementBrainCoordinator(
        context_builder,
        conversation_manager,
        live_execution_service,
        _build_autonomous_send_service(campaigns_root, group_reply_allowed=True),
        brain_service=FakeBrainService(proposal),
        engagement_policy_service=policy_service,
    )

    result = coordinator.review_conversation(
        "cmp-1",
        "conv-delay-1",
        now=datetime(2026, 5, 23, 22, 30, tzinfo=UTC),
    )
    queued_actions = execution_manager.list_for_campaign("cmp-1")

    assert result is not None
    assert result.disposition is EngagementBrainRunDisposition.ENQUEUED
    assert len(queued_actions) == 1
    assert queued_actions[0].next_attempt_at == datetime(2026, 5, 24, 6, 5, tzinfo=UTC)
    assert queued_actions[0].payload["engagement_policy_context"]["latency_tier"] == "long_delay"


def test_coordinator_records_non_send_outcome_without_queueing(tmp_path) -> None:
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
            conversation_id="conv-ignore-1",
            campaign_id="cmp-1",
            account_id="reader-1",
            peer_id="user-42",
            chat_id="user-42",
            thread_origin=ThreadOrigin.DIRECT_INBOUND_DM,
            consent_posture=ConsentPosture.INBOUND_ONLY,
            status=ExternalConversationStatus.ACTIVE,
            external_user_messaged_first=True,
            last_event_id="evt-ignore-1",
            recent_message_refs=["event:evt-ignore-1"],
        )
    )
    engagement_store = ManagedAccountEngagementStore(tmp_path)
    engagement_store.append_inbound_event(
        EngagementEventRecord(
            event_id="evt-ignore-1",
            dedupe_key="dedupe-ignore-1",
            account_id="reader-1",
            event_kind=EngagementEventKind.INBOUND_DM,
            chat_id="user-42",
            peer_id="user-42",
            sender_id="user-42",
            message_id="901",
            text="ok",
            occurred_at=datetime(2026, 5, 23, 12, 15, tzinfo=UTC),
            campaign_id="cmp-1",
            routing_status=EngagementRoutingStatus.ROUTED,
        )
    )
    context_builder = EngagementBrainContextBuilder(campaign_manager, conversation_manager, engagement_store)
    execution_manager = LiveExecutionManager(campaigns_root)
    live_execution_service = LiveExecutionService(
        execution_manager,
        conversation_manager=conversation_manager,
        worker_id="worker-brain-ignore",
    )
    proposal = EngagementBrainProposal(
        decision=EngagementBrainDecision.IGNORE,
        goal="avoid_needy_follow_up",
    )
    coordinator = EngagementBrainCoordinator(
        context_builder,
        conversation_manager,
        live_execution_service,
        _build_autonomous_send_service(campaigns_root),
        brain_service=FakeBrainService(proposal),
    )

    result = coordinator.review_conversation("cmp-1", "conv-ignore-1")
    queued_actions = execution_manager.list_for_campaign("cmp-1")
    updated_conversation = conversation_manager.get("cmp-1", "conv-ignore-1")

    assert result is not None
    assert result.disposition is EngagementBrainRunDisposition.NO_ACTION
    assert queued_actions == []
    assert updated_conversation is not None
    assert updated_conversation.next_action_type == "brain_ignore"


def test_coordinator_enqueues_supported_reply_and_clears_stale_review_state(tmp_path) -> None:
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
            conversation_id="conv-dm-review-needed",
            campaign_id="cmp-1",
            account_id="reader-1",
            peer_id="user-42",
            chat_id="user-42",
            thread_origin=ThreadOrigin.DIRECT_INBOUND_DM,
            consent_posture=ConsentPosture.INBOUND_ONLY,
            status=ExternalConversationStatus.ACTIVE,
            external_user_messaged_first=True,
            last_event_id="evt-review-1",
            recent_message_refs=["event:evt-review-1"],
        )
    )
    engagement_store = ManagedAccountEngagementStore(tmp_path)
    engagement_store.append_inbound_event(
        EngagementEventRecord(
            event_id="evt-review-1",
            dedupe_key="dedupe-review-1",
            account_id="reader-1",
            event_kind=EngagementEventKind.INBOUND_DM,
            chat_id="user-42",
            peer_id="user-42",
            sender_id="user-42",
            message_id="910",
            text="Can you tell me more?",
            occurred_at=datetime(2026, 5, 23, 12, 16, tzinfo=UTC),
            campaign_id="cmp-1",
            routing_status=EngagementRoutingStatus.ROUTED,
        )
    )
    context_builder = EngagementBrainContextBuilder(campaign_manager, conversation_manager, engagement_store)
    execution_manager = LiveExecutionManager(campaigns_root)
    live_execution_service = LiveExecutionService(
        execution_manager,
        conversation_manager=conversation_manager,
        worker_id="worker-brain-review-needed",
    )
    autonomous_send_manager = AutonomousSendManager(campaigns_root)
    autonomous_send_manager.save_review(
        AutonomousSendReviewRecord(
            review_id="review-stale-1",
            campaign_id="cmp-1",
            conversation_id="conv-dm-review-needed",
            account_id="reader-1",
            action_type=LiveActionType.SEND_DM_REPLY.value,
            draft_text="Old pending draft",
            goal="qualify_interest",
            status=AutonomousSendReviewStatus.PENDING,
        )
    )
    stale_conversation = conversation_manager.get("cmp-1", "conv-dm-review-needed")
    assert stale_conversation is not None
    stale_conversation.pending_autonomous_review_id = "review-stale-1"
    conversation_manager.save(stale_conversation)
    proposal = EngagementBrainProposal(
        decision=EngagementBrainDecision.REPLY,
        action_type=EngagementBrainActionType.SEND_DM_REPLY,
        draft_text="There could be a fit. What are you mainly trying to solve right now?",
        goal="qualify_interest",
    )
    coordinator = EngagementBrainCoordinator(
        context_builder,
        conversation_manager,
        live_execution_service,
        AutonomousSendService(autonomous_send_manager),
        brain_service=FakeBrainService(proposal),
    )

    result = coordinator.review_conversation("cmp-1", "conv-dm-review-needed")
    updated_conversation = conversation_manager.get("cmp-1", "conv-dm-review-needed")
    stale_review = autonomous_send_manager.get_review("cmp-1", "review-stale-1")

    assert result is not None
    assert result.disposition is EngagementBrainRunDisposition.ENQUEUED
    assert result.authorization_reason_codes == ["autonomous_send_allowed"]
    assert len(execution_manager.list_for_campaign("cmp-1")) == 1
    assert updated_conversation is not None
    assert updated_conversation.pending_autonomous_review_id == ""
    assert updated_conversation.next_action_type == "queued_send_dm_reply"
    assert stale_review is not None
    assert stale_review.status is AutonomousSendReviewStatus.SUPERSEDED


def test_coordinator_records_pending_review_when_autonomous_send_is_manual_only(tmp_path) -> None:
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
            conversation_id="conv-dm-manual-only",
            campaign_id="cmp-1",
            account_id="reader-1",
            peer_id="user-42",
            chat_id="user-42",
            thread_origin=ThreadOrigin.DIRECT_INBOUND_DM,
            consent_posture=ConsentPosture.INBOUND_ONLY,
            status=ExternalConversationStatus.ACTIVE,
            external_user_messaged_first=True,
            last_event_id="evt-manual-1",
        )
    )
    context_builder = EngagementBrainContextBuilder(
        campaign_manager,
        conversation_manager,
        ManagedAccountEngagementStore(tmp_path),
    )
    live_execution_service = LiveExecutionService(
        LiveExecutionManager(campaigns_root),
        conversation_manager=conversation_manager,
        worker_id="worker-brain-manual-only",
    )
    coordinator = EngagementBrainCoordinator(
        context_builder,
        conversation_manager,
        live_execution_service,
        _build_autonomous_send_service(campaigns_root, dm_reply_allowed=False),
        brain_service=FakeBrainService(
            EngagementBrainProposal(
                decision=EngagementBrainDecision.REPLY,
                action_type=EngagementBrainActionType.SEND_DM_REPLY,
                draft_text="Happy to share more. What are you mainly trying to solve right now?",
                goal="qualify_interest",
            )
        ),
    )

    result = coordinator.review_conversation("cmp-1", "conv-dm-manual-only")
    updated_conversation = conversation_manager.get("cmp-1", "conv-dm-manual-only")

    assert result is not None
    assert result.disposition is EngagementBrainRunDisposition.BLOCKED_BY_AUTHORIZATION
    assert result.review_record_id
    assert updated_conversation is not None
    assert updated_conversation.pending_autonomous_review_id == result.review_record_id
    assert updated_conversation.next_action_type == "review_autonomous_send"


def test_coordinator_respects_policy_before_queueing(tmp_path) -> None:
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
            conversation_id="conv-paused-1",
            campaign_id="cmp-1",
            account_id="reader-1",
            peer_id="user-42",
            chat_id="user-42",
            thread_origin=ThreadOrigin.DIRECT_INBOUND_DM,
            consent_posture=ConsentPosture.INBOUND_ONLY,
            status=ExternalConversationStatus.PAUSED,
            external_user_messaged_first=True,
            last_event_id="evt-paused-1",
            recent_message_refs=["event:evt-paused-1"],
        )
    )
    engagement_store = ManagedAccountEngagementStore(tmp_path)
    engagement_store.append_inbound_event(
        EngagementEventRecord(
            event_id="evt-paused-1",
            dedupe_key="dedupe-paused-1",
            account_id="reader-1",
            event_kind=EngagementEventKind.INBOUND_DM,
            chat_id="user-42",
            peer_id="user-42",
            sender_id="user-42",
            message_id="902",
            text="Interested, tell me more.",
            occurred_at=datetime(2026, 5, 23, 12, 20, tzinfo=UTC),
            campaign_id="cmp-1",
            routing_status=EngagementRoutingStatus.ROUTED,
        )
    )
    context_builder = EngagementBrainContextBuilder(campaign_manager, conversation_manager, engagement_store)
    execution_manager = LiveExecutionManager(campaigns_root)
    live_execution_service = LiveExecutionService(
        execution_manager,
        conversation_manager=conversation_manager,
        worker_id="worker-brain-policy",
    )
    proposal = EngagementBrainProposal(
        decision=EngagementBrainDecision.REPLY,
        action_type=EngagementBrainActionType.SEND_DM_REPLY,
        draft_text="There could be a fit. What are you mainly trying to solve right now?",
        goal="qualify_interest",
    )
    coordinator = EngagementBrainCoordinator(
        context_builder,
        conversation_manager,
        live_execution_service,
        _build_autonomous_send_service(campaigns_root, dm_reply_allowed=True),
        brain_service=FakeBrainService(proposal),
    )

    result = coordinator.review_conversation("cmp-1", "conv-paused-1")
    updated_conversation = conversation_manager.get("cmp-1", "conv-paused-1")

    assert result is not None
    assert result.disposition is EngagementBrainRunDisposition.BLOCKED_BY_POLICY
    assert result.policy_reason_codes == ["conversation_paused"]
    assert execution_manager.list_for_campaign("cmp-1") == []
    assert updated_conversation is not None
    assert updated_conversation.next_action_type == "policy_hold"


def test_coordinator_uses_trigger_identity_in_queue_idempotency(tmp_path) -> None:
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
            conversation_id="conv-dm-follow-up-idempotency",
            campaign_id="cmp-1",
            account_id="reader-1",
            peer_id="user-42",
            chat_id="user-42",
            thread_origin=ThreadOrigin.DIRECT_INBOUND_DM,
            consent_posture=ConsentPosture.INBOUND_ONLY,
            status=ExternalConversationStatus.ACTIVE,
            external_user_messaged_first=True,
            last_event_id="evt-dm-1",
        )
    )
    engagement_store = ManagedAccountEngagementStore(tmp_path)
    context_builder = EngagementBrainContextBuilder(campaign_manager, conversation_manager, engagement_store)
    execution_manager = LiveExecutionManager(campaigns_root)
    live_execution_service = LiveExecutionService(
        execution_manager,
        conversation_manager=conversation_manager,
        worker_id="worker-brain-trigger-idempotency",
    )
    proposal = EngagementBrainProposal(
        decision=EngagementBrainDecision.REPLY,
        action_type=EngagementBrainActionType.SEND_DM_REPLY,
        draft_text="Checking back in with one quick follow-up.",
        goal="follow_up_interest",
    )
    coordinator = EngagementBrainCoordinator(
        context_builder,
        conversation_manager,
        live_execution_service,
        _build_autonomous_send_service(campaigns_root, dm_reply_allowed=True),
        brain_service=FakeBrainService(proposal),
    )

    first_result = coordinator.review_conversation(
        "cmp-1",
        "conv-dm-follow-up-idempotency",
        trigger=ConversationReviewTrigger(
            campaign_id="cmp-1",
            conversation_id="conv-dm-follow-up-idempotency",
            trigger_type=ConversationReviewTriggerType.FOLLOW_UP_DUE,
            trigger_source="scheduled_dm_follow_up_window",
            trigger_key="follow_up:dm_follow_up:2026-05-24T12:00:00+00:00:0",
            eligible_at=datetime(2026, 5, 24, 12, 0, tzinfo=UTC),
        ),
    )
    second_result = coordinator.review_conversation(
        "cmp-1",
        "conv-dm-follow-up-idempotency",
        trigger=ConversationReviewTrigger(
            campaign_id="cmp-1",
            conversation_id="conv-dm-follow-up-idempotency",
            trigger_type=ConversationReviewTriggerType.FOLLOW_UP_DUE,
            trigger_source="scheduled_dm_follow_up_window",
            trigger_key="follow_up:dm_follow_up:2026-05-25T12:00:00+00:00:1",
            eligible_at=datetime(2026, 5, 25, 12, 0, tzinfo=UTC),
        ),
    )
    queued_actions = execution_manager.list_for_campaign("cmp-1")

    assert first_result is not None
    assert second_result is not None
    assert first_result.disposition is EngagementBrainRunDisposition.ENQUEUED
    assert second_result.disposition is EngagementBrainRunDisposition.ENQUEUED
    assert len(queued_actions) == 2
    assert queued_actions[0].idempotency_key != queued_actions[1].idempotency_key
