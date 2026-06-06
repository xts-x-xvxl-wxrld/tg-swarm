from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from telegram_app.app_service import TelegramAppService
from telegram_app.approvals import ApprovalManager, JsonApprovalStore
from telegram_app.autonomous_send import (
    AutonomousSendManager,
    AutonomousSendReviewRecord,
    AutonomousSendReviewStatus,
    AutonomousSendService,
)
from telegram_app.campaigns import CampaignManager
from telegram_app.compiled_intents import CompiledIntentApplicator, CompiledIntentStatus, CompiledIntentStore
from telegram_app.continuous_ops import ContinuousOpsManager
from telegram_app.engagement import ManagedAccountEngagementStore
from telegram_app.engagement_brain import EngagementBrainContextBuilder
from telegram_app.external_conversations import (
    ConsentPosture,
    ExternalConversationManager,
    ExternalConversationRecord,
    ExternalConversationStatus,
    ThreadOrigin,
)
from telegram_app.live_execution import (
    LiveActionType,
    LiveExecutionManager,
    LiveExecutionPolicyStateManager,
    LiveExecutionService,
)
from telegram_app.live_ops import LiveOpsControlManager, LiveOpsService, OperatorGuardrail
from telegram_app.models import WorkflowSnapshot, WorkflowStage
from telegram_app.orchestrator import PurposeBuiltOrchestrator
from telegram_app.prepared_execution import PreparedExecutionManager, PreparedExecutionService
from telegram_app.sessions import JsonSessionStore, SessionManager
from telegram_app.transport import TelegramUpdate
from telegram_app.work_items import WorkItemManager
from telegram_app.scheduling import ScheduleManager
from telegram_app.campaign_signals import CampaignSignalManager
from telegram_app.campaign_signals import CampaignSignalBridge, CampaignSignalSeverity


def _build_runtime(tmp_path: Path) -> dict[str, object]:
    campaigns_root = tmp_path / "campaigns"
    state_root = tmp_path / "state"
    data_root = tmp_path / "data"

    session_manager = SessionManager(JsonSessionStore(state_root / "sessions.json"))
    approval_manager = ApprovalManager(JsonApprovalStore(state_root / "approvals.json"))
    campaign_manager = CampaignManager(campaigns_root)
    work_item_manager = WorkItemManager(campaigns_root)
    schedule_manager = ScheduleManager(campaigns_root)
    signal_manager = CampaignSignalManager(campaigns_root)
    conversation_manager = ExternalConversationManager(campaigns_root)
    continuous_ops_manager = ContinuousOpsManager(
        campaign_manager,
        work_item_manager,
        schedule_manager,
        signal_manager,
        conversation_manager=conversation_manager,
    )
    live_execution_manager = LiveExecutionManager(campaigns_root)
    prepared_execution_manager = PreparedExecutionManager(campaigns_root)
    prepared_execution_service = PreparedExecutionService(
        prepared_execution_manager,
        live_execution_manager,
        session_manager=session_manager,
        work_item_manager=work_item_manager,
    )
    policy_state_manager = LiveExecutionPolicyStateManager(data_root)
    live_execution_service = LiveExecutionService(
        live_execution_manager,
        conversation_manager=conversation_manager,
        campaign_manager=campaign_manager,
        policy_state_manager=policy_state_manager,
        worker_id="worker-live-ops-tests",
    )
    autonomous_send_manager = AutonomousSendManager(campaigns_root)
    autonomous_send_service = AutonomousSendService(
        autonomous_send_manager,
        conversation_manager=conversation_manager,
        live_execution_service=live_execution_service,
    )
    control_manager = LiveOpsControlManager(campaigns_root)
    live_ops_service = LiveOpsService(
        campaign_manager=campaign_manager,
        continuous_ops_manager=continuous_ops_manager,
        control_manager=control_manager,
        autonomous_send_manager=autonomous_send_manager,
        autonomous_send_service=autonomous_send_service,
        conversation_manager=conversation_manager,
        live_execution_service=live_execution_service,
        live_execution_policy_state_manager=policy_state_manager,
        prepared_execution_manager=prepared_execution_manager,
    )
    compiled_intent_store = CompiledIntentStore(campaigns_root)
    compiled_intent_applicator = CompiledIntentApplicator(
        campaign_manager=campaign_manager,
        live_ops_service=live_ops_service,
        schedule_manager=schedule_manager,
        work_item_manager=work_item_manager,
    )

    with patch("anthropic.Anthropic", return_value=MagicMock()):
        orchestrator = PurposeBuiltOrchestrator(
            session_manager=session_manager,
            approval_manager=approval_manager,
            work_item_manager=work_item_manager,
            schedule_manager=schedule_manager,
            campaign_manager=campaign_manager,
            signal_manager=signal_manager,
            continuous_ops_manager=continuous_ops_manager,
            prepared_execution_service=prepared_execution_service,
            live_ops_service=live_ops_service,
            compiled_intent_store=compiled_intent_store,
            compiled_intent_applicator=compiled_intent_applicator,
        )

    service = TelegramAppService(
        session_manager=session_manager,
        approval_manager=approval_manager,
        orchestrator=orchestrator,
        campaign_manager=campaign_manager,
        continuous_ops_manager=continuous_ops_manager,
    )
    return {
        "service": service,
        "session_manager": session_manager,
        "campaign_manager": campaign_manager,
        "compiled_intent_store": compiled_intent_store,
        "conversation_manager": conversation_manager,
        "autonomous_send_manager": autonomous_send_manager,
        "control_manager": control_manager,
        "live_execution_manager": live_execution_manager,
        "policy_state_manager": policy_state_manager,
        "campaigns_root": campaigns_root,
        "tmp_path": tmp_path,
    }


def _attach_campaign(runtime: dict[str, object], *, operator_id: str, campaign_id: str = "cmp-live-ops") -> None:
    session_manager: SessionManager = runtime["session_manager"]  # type: ignore[assignment]
    campaign_manager: CampaignManager = runtime["campaign_manager"]  # type: ignore[assignment]
    session = session_manager.start_session(operator_id)
    campaign = campaign_manager.ensure_campaign(
        operator_id,
        campaign_id=campaign_id,
        workspace_path=str((runtime["campaigns_root"] / campaign_id).resolve()),  # type: ignore[index]
    )
    session_manager.attach_campaign(
        session,
        campaign_id=campaign.campaign_id,
        campaign_workspace_path=campaign.workspace_path,
        canonical_memory_files=campaign.canonical_files,
        agent_memory_files=campaign.agent_memory_files,
    )
    session_manager.replace_workflow_snapshot(
        session,
        WorkflowSnapshot(
            stage=WorkflowStage.COMPLETE,
            summary="Campaign is ready for live operations.",
        ),
    )


def test_live_ops_chat_controls_pause_resume_and_posture_changes(tmp_path) -> None:
    runtime = _build_runtime(tmp_path)
    _attach_campaign(runtime, operator_id="operator-live-ops")
    service: TelegramAppService = runtime["service"]  # type: ignore[assignment]
    campaign_manager: CampaignManager = runtime["campaign_manager"]  # type: ignore[assignment]
    conversation_manager: ExternalConversationManager = runtime["conversation_manager"]  # type: ignore[assignment]
    autonomous_send_manager: AutonomousSendManager = runtime["autonomous_send_manager"]  # type: ignore[assignment]

    conversation_manager.save(
        ExternalConversationRecord(
            conversation_id="conv-only-1",
            campaign_id="cmp-live-ops",
            account_id="acct-1",
            peer_id="user-1",
            chat_id="user-1",
            thread_origin=ThreadOrigin.DIRECT_INBOUND_DM,
            consent_posture=ConsentPosture.INBOUND_ONLY,
            status=ExternalConversationStatus.PAUSED,
            external_user_messaged_first=True,
        )
    )

    pause_response = service.handle_update(
        TelegramUpdate(chat_id="chat-1", user_id="operator-live-ops", text="pause this campaign")
    )
    dm_response = service.handle_update(
        TelegramUpdate(chat_id="chat-1", user_id="operator-live-ops", text="stop autonomous DM replies")
    )
    group_response = service.handle_update(
        TelegramUpdate(chat_id="chat-1", user_id="operator-live-ops", text="let group replies run automatically")
    )
    outreach_response = service.handle_update(
        TelegramUpdate(chat_id="chat-1", user_id="operator-live-ops", text="let group outreach run automatically")
    )
    resume_response = service.handle_update(
        TelegramUpdate(chat_id="chat-1", user_id="operator-live-ops", text="resume this conversation")
    )

    assert "Paused campaign `cmp-live-ops`" in pause_response.messages[0].text
    assert campaign_manager.get("cmp-live-ops").status.value == "paused"

    posture = autonomous_send_manager.get_posture("cmp-live-ops")
    assert posture.dm_reply_mode.value == "manual_only"
    assert "DM replies are now `manual-only`" in dm_response.messages[0].text
    assert posture.group_reply_mode.value == "autonomous_allowed"
    assert "Group replies are now `automatic`" in group_response.messages[0].text
    assert posture.group_outreach_mode.value == "autonomous_allowed"
    assert "Group outreach sends are now `automatic`" in outreach_response.messages[0].text

    resumed_conversation = conversation_manager.get("cmp-live-ops", "conv-only-1")
    assert resumed_conversation is not None
    assert resumed_conversation.status is ExternalConversationStatus.ACTIVE
    assert "Resumed conversation `conv-only-1`." in resume_response.messages[0].text


def test_live_ops_approves_single_pending_review_from_chat(tmp_path) -> None:
    runtime = _build_runtime(tmp_path)
    _attach_campaign(runtime, operator_id="operator-review")
    service: TelegramAppService = runtime["service"]  # type: ignore[assignment]
    conversation_manager: ExternalConversationManager = runtime["conversation_manager"]  # type: ignore[assignment]
    autonomous_send_manager: AutonomousSendManager = runtime["autonomous_send_manager"]  # type: ignore[assignment]
    live_execution_manager: LiveExecutionManager = runtime["live_execution_manager"]  # type: ignore[assignment]

    conversation_manager.save(
        ExternalConversationRecord(
            conversation_id="conv-review-1",
            campaign_id="cmp-live-ops",
            account_id="acct-9",
            peer_id="user-99",
            chat_id="user-99",
            thread_origin=ThreadOrigin.DIRECT_INBOUND_DM,
            consent_posture=ConsentPosture.INBOUND_ONLY,
            status=ExternalConversationStatus.ACTIVE,
            external_user_messaged_first=True,
            last_event_id="evt-1",
            last_inbound_message_id="msg-1",
        )
    )
    autonomous_send_manager.save_review(
        AutonomousSendReviewRecord(
            review_id="review-123",
            campaign_id="cmp-live-ops",
            conversation_id="conv-review-1",
            account_id="acct-9",
            action_type=LiveActionType.SEND_DM_REPLY.value,
            status=AutonomousSendReviewStatus.PENDING,
            draft_text="Happy to share more. What are you trying to solve right now?",
            goal="qualify_interest",
            trigger_key="evt-1",
            context_fingerprint="",
            summary="DM reply needs operator approval.",
        )
    )
    conversation = conversation_manager.get("cmp-live-ops", "conv-review-1")
    assert conversation is not None
    conversation.pending_autonomous_review_id = "review-123"
    conversation_manager.save(conversation)

    response = service.handle_update(
        TelegramUpdate(chat_id="chat-1", user_id="operator-review", text="approve that review")
    )

    review = autonomous_send_manager.get_review("cmp-live-ops", "review-123")
    queued_actions = live_execution_manager.list_for_campaign("cmp-live-ops")
    updated_conversation = conversation_manager.get("cmp-live-ops", "conv-review-1")

    assert "Approved `review-123` and queued" in response.messages[0].text
    assert review is not None
    assert review.status is AutonomousSendReviewStatus.MATERIALIZED
    assert len(queued_actions) == 1
    assert queued_actions[0].payload["approval_context"]["approval_mode"] == "operator"
    assert queued_actions[0].payload["approval_context"]["review_id"] == "review-123"
    assert updated_conversation is not None
    assert updated_conversation.pending_autonomous_review_id == ""


def test_live_ops_clarifies_when_review_scope_is_ambiguous(tmp_path) -> None:
    runtime = _build_runtime(tmp_path)
    _attach_campaign(runtime, operator_id="operator-ambiguous")
    service: TelegramAppService = runtime["service"]  # type: ignore[assignment]
    autonomous_send_manager: AutonomousSendManager = runtime["autonomous_send_manager"]  # type: ignore[assignment]

    for review_id in ("review-111", "review-222"):
        autonomous_send_manager.save_review(
            AutonomousSendReviewRecord(
                review_id=review_id,
                campaign_id="cmp-live-ops",
                conversation_id=f"conv-{review_id}",
                account_id="acct-1",
                action_type=LiveActionType.SEND_DM_REPLY.value,
                status=AutonomousSendReviewStatus.PENDING,
                draft_text="Need approval.",
                goal="qualify_interest",
            )
        )

    response = service.handle_update(
        TelegramUpdate(chat_id="chat-1", user_id="operator-ambiguous", text="approve that review")
    )

    assert "Which review should I use?" in response.messages[0].text
    assert autonomous_send_manager.get_review("cmp-live-ops", "review-111").status is AutonomousSendReviewStatus.PENDING
    assert autonomous_send_manager.get_review("cmp-live-ops", "review-222").status is AutonomousSendReviewStatus.PENDING


def test_live_ops_status_surfaces_missing_and_default_controls(tmp_path) -> None:
    runtime = _build_runtime(tmp_path)
    _attach_campaign(runtime, operator_id="operator-readiness")
    service: TelegramAppService = runtime["service"]  # type: ignore[assignment]

    response = service.handle_update(
        TelegramUpdate(chat_id="chat-1", user_id="operator-readiness", text="show me what needs attention")
    )
    text = response.messages[0].text.lower()

    assert "control readiness:" in text
    assert "voice profile is still using the built-in live reply default" in text
    assert "approved claims are not defined yet" in text
    assert "forbidden claims are still relying on the built-in defaults" in text
    assert "autonomous dm reply posture is still on the default" in text
    assert "community-specific tone guidance is still missing" in text


def test_live_ops_chat_updates_voice_and_safeguard_controls(tmp_path) -> None:
    runtime = _build_runtime(tmp_path)
    _attach_campaign(runtime, operator_id="operator-tone")
    service: TelegramAppService = runtime["service"]  # type: ignore[assignment]
    control_manager: LiveOpsControlManager = runtime["control_manager"]  # type: ignore[assignment]

    voice_response = service.handle_update(
        TelegramUpdate(
            chat_id="chat-1",
            user_id="operator-tone",
            text="make the tone warmer, less salesy, more direct, use less punctuation, no prose, no em dashes, no emojis, not corny, and remember this is an online service",
        )
    )
    safeguard_response = service.handle_update(
        TelegramUpdate(
            chat_id="chat-1",
            user_id="operator-tone",
            text="do not mention pricing unless asked",
        )
    )
    profile = control_manager.get_profile("cmp-live-ops")

    assert "Updated the live reply voice" in voice_response.messages[0].text
    assert "Saved that safeguard" in safeguard_response.messages[0].text
    assert "warmer" in profile.voice_profile.tone_descriptors
    assert "direct" in profile.voice_profile.tone_descriptors
    assert "salesy language" in profile.voice_profile.style_avoid
    assert "use minimal punctuation" in profile.voice_profile.style_do
    assert "polished prose" in profile.voice_profile.style_avoid
    assert "em dashes" in profile.voice_profile.style_avoid
    assert "emoji greetings" in profile.voice_profile.style_avoid
    assert "corny openers" in profile.voice_profile.style_avoid
    assert profile.voice_profile.emoji_policy == "none"
    assert "frame value around the online service naturally" in profile.voice_profile.style_do
    assert any("pricing unless asked" in claim.instruction.lower() for claim in profile.forbidden_claims)


def test_live_ops_control_message_persists_multiple_compiled_intents(tmp_path) -> None:
    runtime = _build_runtime(tmp_path)
    _attach_campaign(runtime, operator_id="operator-compiled-controls")
    service: TelegramAppService = runtime["service"]  # type: ignore[assignment]
    control_manager: LiveOpsControlManager = runtime["control_manager"]  # type: ignore[assignment]
    compiled_intent_store: CompiledIntentStore = runtime["compiled_intent_store"]  # type: ignore[assignment]

    response = service.handle_update(
        TelegramUpdate(
            chat_id="chat-1",
            user_id="operator-compiled-controls",
            text="make the tone warmer, less salesy, more direct, use less punctuation, no prose, no em dashes, no emojis, not corny, this is an online service, and do not mention pricing unless asked",
        )
    )

    profile = control_manager.get_profile("cmp-live-ops")
    stored_intents = compiled_intent_store.list_for_campaign("cmp-live-ops")
    stored_kinds = {intent.kind for intent in stored_intents}
    applied_kinds = {
        intent.kind
        for intent in stored_intents
        if intent.status is CompiledIntentStatus.APPLIED
    }
    voice_intent = next(intent for intent in stored_intents if intent.kind == "campaign_control.update_voice")
    safeguard_intent = next(intent for intent in stored_intents if intent.kind == "campaign_control.update_safeguard")

    assert "Updated the live reply voice" in response.messages[0].text
    assert "Saved that safeguard" in response.messages[0].text
    assert "warmer" in profile.voice_profile.tone_descriptors
    assert "direct" in profile.voice_profile.tone_descriptors
    assert "salesy language" in profile.voice_profile.style_avoid
    assert "use minimal punctuation" in profile.voice_profile.style_do
    assert "polished prose" in profile.voice_profile.style_avoid
    assert "em dashes" in profile.voice_profile.style_avoid
    assert "emoji greetings" in profile.voice_profile.style_avoid
    assert "corny openers" in profile.voice_profile.style_avoid
    assert profile.voice_profile.emoji_policy == "none"
    assert "frame value around the online service naturally" in profile.voice_profile.style_do
    assert any("pricing unless asked" in claim.instruction.lower() for claim in profile.forbidden_claims)
    assert "campaign_control.update_voice" in stored_kinds
    assert "campaign_control.update_safeguard" in stored_kinds
    assert "campaign_control.update_voice" in applied_kinds
    assert "campaign_control.update_safeguard" in applied_kinds
    assert "warmer" in voice_intent.payload["tone_descriptors"]
    assert "salesy language" in voice_intent.payload["style_avoid"]
    assert "use minimal punctuation" in voice_intent.payload["style_do"]
    assert "polished prose" in voice_intent.payload["style_avoid"]
    assert "em dashes" in voice_intent.payload["style_avoid"]
    assert "emoji greetings" in voice_intent.payload["style_avoid"]
    assert "corny openers" in voice_intent.payload["style_avoid"]
    assert voice_intent.payload["emoji_policy"] == "none"
    assert safeguard_intent.payload["instruction"] == "do not mention pricing unless asked"


def test_live_ops_status_surfaces_commercial_traction(tmp_path) -> None:
    runtime = _build_runtime(tmp_path)
    _attach_campaign(runtime, operator_id="operator-traction")
    service: TelegramAppService = runtime["service"]  # type: ignore[assignment]
    conversation_manager: ExternalConversationManager = runtime["conversation_manager"]  # type: ignore[assignment]
    session_manager: SessionManager = runtime["session_manager"]  # type: ignore[assignment]
    signal_manager = CampaignSignalManager(runtime["campaigns_root"])  # type: ignore[arg-type]
    bridge = CampaignSignalBridge(signal_manager)

    conversation_manager.save(
        ExternalConversationRecord(
            conversation_id="conv-hot-1",
            campaign_id="cmp-live-ops",
            account_id="acct-hot",
            peer_id="peer-hot",
            chat_id="peer-hot",
            community_id="community-hot",
            thread_origin=ThreadOrigin.DIRECT_INBOUND_DM,
            consent_posture=ConsentPosture.INBOUND_ONLY,
            status=ExternalConversationStatus.ACTIVE,
            qualification_status="conversion_ready",
            handoff_status="ready",
            qualification_summary="Conversation looks conversion-ready.",
            handoff_summary="Ready to route this lead via Telegram DM.",
            external_user_messaged_first=True,
        )
    )
    bridge.record(
        campaign_id="cmp-live-ops",
        source_kind="qualification",
        source_ref="conv-hot-1",
        signal_type="conversion_ready_thread",
        severity=CampaignSignalSeverity.HIGH,
        summary="Thread is ready to route.",
        account_id="acct-hot",
        community_id="community-hot",
        conversation_id="conv-hot-1",
    )
    bridge.record(
        campaign_id="cmp-live-ops",
        source_kind="qualification",
        source_ref="conv-hot-1",
        signal_type="pricing_interest",
        severity=CampaignSignalSeverity.MEDIUM,
        summary="Lead asked about pricing.",
        account_id="acct-hot",
        community_id="community-hot",
        conversation_id="conv-hot-1",
    )
    assert session_manager.get_active_session("operator-traction") is not None

    response = service.handle_update(
        TelegramUpdate(chat_id="chat-1", user_id="operator-traction", text="show live status")
    )
    text = response.messages[0].text.lower()

    assert "traction:" in text
    assert "conversion-ready" in text
    assert "momentum hotspots:" in text
    assert "acct-hot" in text
    assert "conv-hot-1" in text


def test_live_ops_control_profile_reaches_engagement_brain_context(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    campaign_manager = CampaignManager(campaigns_root)
    campaign_manager.ensure_campaign(
        "operator-control-profile",
        campaign_id="cmp-ctx",
        workspace_path=str((campaigns_root / "cmp-ctx").resolve()),
    )
    control_manager = LiveOpsControlManager(campaigns_root)
    profile = control_manager.get_profile("cmp-ctx")
    profile.voice_profile.tone_descriptors = ["warmer", "direct"]
    profile.voice_profile.style_avoid = ["salesy language"]
    profile.forbidden_claims = [
        OperatorGuardrail(
            label="pricing_unless_asked",
            instruction="Do not mention pricing unless asked.",
        )
    ]
    control_manager.save_profile(profile)

    conversation_manager = ExternalConversationManager(campaigns_root)
    conversation_manager.save(
        ExternalConversationRecord(
            conversation_id="conv-ctx-1",
            campaign_id="cmp-ctx",
            account_id="acct-ctx-1",
            peer_id="peer-ctx-1",
            chat_id="peer-ctx-1",
            thread_origin=ThreadOrigin.DIRECT_INBOUND_DM,
            consent_posture=ConsentPosture.INBOUND_ONLY,
            status=ExternalConversationStatus.ACTIVE,
            external_user_messaged_first=True,
        )
    )

    builder = EngagementBrainContextBuilder(
        campaign_manager,
        conversation_manager,
        ManagedAccountEngagementStore(tmp_path),
        live_ops_control_manager=control_manager,
    )
    context = builder.build("cmp-ctx", "conv-ctx-1")

    assert context is not None
    assert "warmer" in context.voice_profile.tone_descriptors
    assert "salesy language" in context.voice_profile.style_avoid
    assert any(claim.label == "pricing_unless_asked" for claim in context.effective_forbidden_claims())
