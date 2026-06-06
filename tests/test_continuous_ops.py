from __future__ import annotations

from datetime import UTC, datetime

from telegram_app.agent_runtime import AgentRuntimeBroker
from telegram_app.campaign_signals import (
    CampaignSignalBridge,
    CampaignSignalManager,
    CampaignSignalSeverity,
    ObservationMaterialChange,
    ObservationOperatorAttention,
    ObservationPriorityPressure,
    ObservationRecommendedNextStep,
    ObservationReviewBrief,
)
from telegram_app.campaigns import CampaignManager
from telegram_app.compiled_intents import (
    CompiledIntentSafetyClass,
    CompiledIntentStore,
    build_compiled_intent,
)
from telegram_app.continuous_ops import (
    ContinuousAutonomyMode,
    ContinuousOpsManager,
    ContinuousOpsStatus,
    load_continuous_ops_state_for_workspace,
)
from telegram_app.external_conversations import (
    ConversationBeliefState,
    ConsentPosture,
    ExternalConversationManager,
    ExternalConversationRecord,
    ExternalConversationStatus,
    ThreadOrigin,
)
from telegram_app.intake import StructuredIntakeCoordinator
from telegram_app.models import WorkflowArtifactKind, WorkflowSnapshot, WorkflowStage
from telegram_app.orchestrator.context_builder import build_runtime_context
from telegram_app.scheduling import ScheduleManager
from telegram_app.sessions import JsonSessionStore, SessionManager
from telegram_app.work_items import WorkItemManager


def test_continuous_ops_blocks_continuous_campaign_without_active_loop(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    session_manager = SessionManager(JsonSessionStore(tmp_path / "sessions.json"))
    campaign_manager = CampaignManager(campaigns_root)
    work_item_manager = WorkItemManager(campaigns_root)
    schedule_manager = ScheduleManager(campaigns_root)
    signal_manager = CampaignSignalManager(campaigns_root)
    continuous_ops_manager = ContinuousOpsManager(
        campaign_manager,
        work_item_manager,
        schedule_manager,
        signal_manager,
    )

    intake = StructuredIntakeCoordinator(session_manager)
    session = session_manager.start_session("operator-loop-gap")
    campaign = campaign_manager.ensure_campaign("operator-loop-gap", campaign_id="cmp-loop-gap")
    session_manager.attach_campaign(
        session,
        campaign.campaign_id,
        campaign.workspace_path,
        canonical_memory_files=campaign.canonical_files,
        agent_memory_files=campaign.agent_memory_files,
    )
    intake.ingest_operator_turn(
        session,
        "Goal: Reach AI founders. Keep running until paused.",
        source_message_id="turn-1",
    )
    session_manager.create_workflow_artifact(
        session=session,
        kind=WorkflowArtifactKind.ACCOUNT_ASSIGNMENT_PLAN,
        title="Account plan",
        data={"summary": "Plan ready for live follow-up."},
    )
    session_manager.replace_workflow_snapshot(
        session,
        WorkflowSnapshot(
            stage=WorkflowStage.COMPLETE,
            summary="Initial planning is complete and ready for ongoing follow-up.",
        ),
    )
    campaign_manager.sync_session_memory(session)

    state = continuous_ops_manager.refresh_for_session(session)
    assert state is not None
    assert state.autonomy_mode is ContinuousAutonomyMode.CONTINUOUS
    assert state.loop_status is ContinuousOpsStatus.BLOCKED
    assert "no recurring schedules or open work items" in state.status_summary.lower()

    reloaded_state = load_continuous_ops_state_for_workspace(campaign.workspace_path)
    assert reloaded_state is not None
    assert reloaded_state.loop_status is ContinuousOpsStatus.BLOCKED

    context = build_runtime_context(session, pending_approval=None)
    assert "continuous_ops_status: blocked" in context

    overview = (campaigns_root / campaign.campaign_id / "overview.md").read_text(encoding="utf-8")
    next_actions = (campaigns_root / campaign.campaign_id / "next-actions.md").read_text(encoding="utf-8")
    assert "- Loop status: blocked" in overview
    assert "Continuous ops status: blocked" in next_actions


def test_runtime_context_includes_agent_runtime_broker_summaries(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    session_manager = SessionManager(JsonSessionStore(tmp_path / "sessions.json"))
    campaign_manager = CampaignManager(campaigns_root)
    work_item_manager = WorkItemManager(campaigns_root)
    schedule_manager = ScheduleManager(campaigns_root)
    signal_manager = CampaignSignalManager(campaigns_root)
    continuous_ops_manager = ContinuousOpsManager(
        campaign_manager,
        work_item_manager,
        schedule_manager,
        signal_manager,
    )
    compiled_intent_store = CompiledIntentStore(campaigns_root)

    session = session_manager.start_session("operator-runtime-context")
    campaign = campaign_manager.ensure_campaign("operator-runtime-context", campaign_id="cmp-runtime-context")
    session_manager.attach_campaign(
        session,
        campaign.campaign_id,
        campaign.workspace_path,
        canonical_memory_files=campaign.canonical_files,
        agent_memory_files=campaign.agent_memory_files,
    )
    work_item_manager.ensure_work_item(
        campaign.campaign_id,
        owner_role="discovery",
        work_type="discovery",
        goal="Refresh the shortlist.",
    )
    schedule_manager.create_interval_schedule(
        campaign.campaign_id,
        owner_role="strategy",
        work_type="strategy",
        goal="Run a weekly strategy review.",
        interval_minutes=60,
        next_run_at=datetime(2026, 5, 30, 12, 0, tzinfo=UTC),
    )
    proposal = build_compiled_intent(
        campaign_id=campaign.campaign_id,
        kind="planning.follow_on_recommendation",
        summary="Recommend strategy after discovery review.",
        payload={
            "current_work_type": "discovery",
            "recommended_next_work_type": "strategy",
            "recommended_action": "refresh_if_stale",
            "reason": "Discovery remains one bounded planning surface.",
        },
        source_role="discovery",
        safety_class=CompiledIntentSafetyClass.ADVISORY,
    )
    compiled_intent_store.save(proposal)
    proposal.mark_accepted()
    compiled_intent_store.save(proposal)
    continuous_ops_manager.refresh_for_session(session)

    broker = AgentRuntimeBroker(
        work_item_manager=work_item_manager,
        schedule_manager=schedule_manager,
        compiled_intent_store=compiled_intent_store,
    )
    context = build_runtime_context(
        session,
        pending_approval=None,
        work_type="discovery",
        agent_runtime_broker=broker,
    )

    assert "campaign_readiness_summary" in context
    assert "runtime_pressure_summary" in context
    assert "traction_summary" in context
    assert "worker_health_summary" in context
    assert "recent_proposal_outcomes" in context
    assert '"accepted": 1' in context
    assert "active_work_item_count: 1" in context
    assert "active_schedule_count: 1" in context


def test_signal_bridge_refreshes_running_continuous_ops_state(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    campaign_manager = CampaignManager(campaigns_root)
    work_item_manager = WorkItemManager(campaigns_root)
    schedule_manager = ScheduleManager(campaigns_root)
    signal_manager = CampaignSignalManager(campaigns_root)
    continuous_ops_manager = ContinuousOpsManager(
        campaign_manager,
        work_item_manager,
        schedule_manager,
        signal_manager,
    )
    campaign = campaign_manager.ensure_campaign("operator-signal", campaign_id="cmp-signal")
    bridge = CampaignSignalBridge(
        signal_manager,
        continuous_ops_manager=continuous_ops_manager,
    )

    bridge.record(
        campaign_id=campaign.campaign_id,
        source_kind="live_execution",
        source_ref="action-1",
        signal_type="policy_block_repeated",
        severity=CampaignSignalSeverity.HIGH,
        summary="A live action hit repeated policy friction.",
        review_eligible=True,
    )

    state = load_continuous_ops_state_for_workspace(campaign.workspace_path)
    assert state is not None
    assert state.loop_status is ContinuousOpsStatus.RUNNING
    assert state.reviewable_signal_count == 1
    assert state.highest_signal_severity == "high"


def test_continuous_ops_blocks_when_observation_requires_operator_attention(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    session_manager = SessionManager(JsonSessionStore(tmp_path / "sessions.json"))
    campaign_manager = CampaignManager(campaigns_root)
    work_item_manager = WorkItemManager(campaigns_root)
    schedule_manager = ScheduleManager(campaigns_root)
    signal_manager = CampaignSignalManager(campaigns_root)
    continuous_ops_manager = ContinuousOpsManager(
        campaign_manager,
        work_item_manager,
        schedule_manager,
        signal_manager,
    )
    session = session_manager.start_session("operator-attention")
    campaign = campaign_manager.ensure_campaign("operator-attention", campaign_id="cmp-attention")
    session_manager.attach_campaign(
        session,
        campaign.campaign_id,
        campaign.workspace_path,
        canonical_memory_files=campaign.canonical_files,
        agent_memory_files=campaign.agent_memory_files,
    )
    session_manager.create_workflow_artifact(
        session=session,
        kind=WorkflowArtifactKind.CAMPAIGN_BRIEF,
        title="Campaign brief",
        data={"objective": "Reach AI founders"},
    )
    campaign_manager.sync_session_memory(session)

    bridge = CampaignSignalBridge(signal_manager)
    signal = bridge.record(
        campaign_id=campaign.campaign_id,
        source_kind="live_execution",
        source_ref="action-2",
        signal_type="account_flagged_or_banned",
        severity=CampaignSignalSeverity.CRITICAL,
        summary="A key account was flagged and operator judgment is now required.",
        review_eligible=True,
    )
    signal_manager.complete_review(
        campaign.campaign_id,
        work_item_id="work-observation-1",
        trigger_source="test",
        review_reason="Operator judgment is required before continuing.",
        signal_ids=[signal.signal_id],
        brief=ObservationReviewBrief(
            summary="A flagged account now requires operator review before campaign work continues.",
            material_change=ObservationMaterialChange.YES,
            priority_pressure=ObservationPriorityPressure.HIGH,
            suggested_work_item_changes=[],
            suggested_posture_updates=[],
            operator_attention_needed=ObservationOperatorAttention.REQUIRED,
            recommended_next_step=ObservationRecommendedNextStep.OPERATOR_REVIEW,
            memory_note_lines=[],
        ),
    )

    state = continuous_ops_manager.refresh_for_session(session)
    assert state is not None
    assert state.loop_status is ContinuousOpsStatus.BLOCKED
    assert state.operator_attention_required is True
    assert "operator review" in state.status_summary.lower()


def test_continuous_ops_summarizes_commercial_traction(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    session_manager = SessionManager(JsonSessionStore(tmp_path / "sessions.json"))
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
    session = session_manager.start_session("operator-traction")
    campaign = campaign_manager.ensure_campaign("operator-traction", campaign_id="cmp-traction")
    session_manager.attach_campaign(
        session,
        campaign.campaign_id,
        campaign.workspace_path,
        canonical_memory_files=campaign.canonical_files,
        agent_memory_files=campaign.agent_memory_files,
    )
    campaign_manager.sync_session_memory(session)
    now = datetime.now(UTC)
    conversation_manager.save(
        ExternalConversationRecord(
            conversation_id="conv-promising",
            campaign_id=campaign.campaign_id,
            account_id="acct-1",
            peer_id="peer-1",
            chat_id="peer-1",
            thread_origin=ThreadOrigin.DIRECT_INBOUND_DM,
            consent_posture=ConsentPosture.INBOUND_ONLY,
            status=ExternalConversationStatus.ACTIVE,
            qualification_status="potential_fit",
            belief_state=ConversationBeliefState(
                commercial_stage="potential_fit",
                known_fit_signals=["asked about pricing"],
                last_belief_update_at=now,
            ),
            external_user_messaged_first=True,
        )
    )
    conversation_manager.save(
        ExternalConversationRecord(
            conversation_id="conv-stale-ready",
            campaign_id=campaign.campaign_id,
            account_id="acct-2",
            peer_id="peer-2",
            chat_id="peer-2",
            community_id="community-1",
            thread_origin=ThreadOrigin.DIRECT_INBOUND_DM,
            consent_posture=ConsentPosture.INBOUND_ONLY,
            status=ExternalConversationStatus.ACTIVE,
            qualification_status="conversion_ready",
            handoff_status="ready",
            belief_state=ConversationBeliefState(
                commercial_stage="handoff_ready",
                known_fit_signals=["conversion-ready signal"],
                last_belief_update_at=datetime(2026, 5, 20, 12, 0, tzinfo=UTC),
            ),
            created_at=datetime(2026, 5, 20, 12, 0, tzinfo=UTC),
            external_user_messaged_first=True,
        )
    )
    conversation_manager.save(
        ExternalConversationRecord(
            conversation_id="conv-objection",
            campaign_id=campaign.campaign_id,
            account_id="acct-3",
            peer_id="peer-3",
            chat_id="peer-3",
            thread_origin=ThreadOrigin.DIRECT_INBOUND_DM,
            consent_posture=ConsentPosture.INBOUND_ONLY,
            status=ExternalConversationStatus.ACTIVE,
            qualification_status="objection_or_unclear",
            belief_state=ConversationBeliefState(known_objections=["pricing_concern"]),
            external_user_messaged_first=True,
        )
    )
    bridge = CampaignSignalBridge(signal_manager)
    bridge.record(
        campaign_id=campaign.campaign_id,
        source_kind="qualification",
        source_ref="conv-stale-ready",
        signal_type="conversion_ready_thread",
        severity=CampaignSignalSeverity.HIGH,
        summary="Thread is ready to route.",
        account_id="acct-2",
        community_id="community-1",
        conversation_id="conv-stale-ready",
    )
    bridge.record(
        campaign_id=campaign.campaign_id,
        source_kind="qualification_handoff",
        source_ref="conv-stale-ready",
        signal_type="handoff_delivered",
        severity=CampaignSignalSeverity.HIGH,
        summary="Delivered the handoff successfully.",
        account_id="acct-2",
        community_id="community-1",
        conversation_id="conv-stale-ready",
        happened_at=now,
    )

    state = continuous_ops_manager.refresh_for_session(session)

    assert state is not None
    assert state.promising_active_thread_count == 2
    assert state.objection_heavy_thread_count == 1
    assert state.conversion_ready_thread_count == 1
    assert state.unresolved_high_opportunity_thread_count == 1
    assert state.stale_promising_thread_count == 1
    assert "promising active" in state.commercial_summary.lower()
    assert state.high_yield_account_labels == ["acct-2 (3 traction)"]
    assert state.high_yield_community_labels == ["community-1 (3 traction)"]
