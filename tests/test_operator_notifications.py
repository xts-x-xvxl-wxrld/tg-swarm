from __future__ import annotations

from telegram_app.app_service import TelegramAppService
from telegram_app.approvals import ApprovalManager, JsonApprovalStore
from telegram_app.campaigns import CampaignManager
from telegram_app.campaign_signals import CampaignSignalManager
from telegram_app.compiled_intents import (
    CompiledIntentApplicator,
    CompiledIntentStatus,
    CompiledIntentStore,
)
from telegram_app.continuous_ops import ContinuousOpsManager
from telegram_app.intake import StructuredIntakeCoordinator
from telegram_app.models import WorkflowArtifactKind, WorkflowSnapshot, WorkflowStage
from telegram_app.operator_notifications import (
    OperatorInterventionKind,
    OperatorInterventionManager,
    OperatorInterventionStatus,
)
from telegram_app.orchestrator import PurposeBuiltOrchestrator
from telegram_app.orchestrator.context_builder import build_runtime_context
from telegram_app.scheduling import ScheduleManager
from telegram_app.sessions import JsonSessionStore, SessionManager
from telegram_app.transport import TelegramResponse, TelegramUpdate
from telegram_app.work_items import WorkItemManager


class StubTurnHandler:
    def handle_turn(self, session, update, pending_approval=None, trace_context=None):  # noqa: ANN001
        return TelegramResponse.single(update.chat_id, "Base reply.")


def test_interventions_track_blocked_loop_and_resolve_after_schedule_creation(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    session_manager = SessionManager(JsonSessionStore(tmp_path / "sessions.json"))
    campaign_manager = CampaignManager(campaigns_root)
    work_item_manager = WorkItemManager(campaigns_root)
    schedule_manager = ScheduleManager(campaigns_root)
    signal_manager = CampaignSignalManager(campaigns_root)
    intervention_manager = OperatorInterventionManager(
        campaign_manager,
        schedule_manager,
        signal_manager,
    )
    continuous_ops_manager = ContinuousOpsManager(
        campaign_manager,
        work_item_manager,
        schedule_manager,
        signal_manager,
        intervention_manager=intervention_manager,
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

    interventions = intervention_manager.list_open_for_campaign(campaign.campaign_id)
    assert len(interventions) == 1
    assert interventions[0].kind is OperatorInterventionKind.CAMPAIGN_LOOP_BLOCKED
    assert "no recurring schedules or open work items" in interventions[0].body.lower()

    context = build_runtime_context(session, pending_approval=None)
    assert "operator_interventions_present: true" in context
    assert "campaign_loop_blocked" in context

    schedule_manager.create_interval_schedule(
        campaign.campaign_id,
        owner_role="strategy",
        work_type="strategy",
        goal="Refresh the strategy weekly.",
        interval_minutes=10080,
    )
    refreshed_state = continuous_ops_manager.refresh_for_session(session)
    assert refreshed_state is not None

    assert intervention_manager.list_open_for_campaign(campaign.campaign_id) == []
    stored = intervention_manager.list_for_campaign(campaign.campaign_id)
    assert len(stored) == 1
    assert stored[0].status is OperatorInterventionStatus.RESOLVED


def test_app_service_delivers_interventions_once_and_supports_show_and_ack(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    session_manager = SessionManager(JsonSessionStore(tmp_path / "sessions.json"))
    approval_manager = ApprovalManager(JsonApprovalStore(tmp_path / "approvals.json"))
    campaign_manager = CampaignManager(campaigns_root)
    work_item_manager = WorkItemManager(campaigns_root)
    schedule_manager = ScheduleManager(campaigns_root)
    signal_manager = CampaignSignalManager(campaigns_root)
    intervention_manager = OperatorInterventionManager(
        campaign_manager,
        schedule_manager,
        signal_manager,
    )
    continuous_ops_manager = ContinuousOpsManager(
        campaign_manager,
        work_item_manager,
        schedule_manager,
        signal_manager,
        intervention_manager=intervention_manager,
    )
    intake = StructuredIntakeCoordinator(session_manager)
    service = TelegramAppService(
        session_manager=session_manager,
        approval_manager=approval_manager,
        orchestrator=StubTurnHandler(),
        intake_coordinator=intake,
        campaign_manager=campaign_manager,
        intervention_manager=intervention_manager,
        continuous_ops_manager=continuous_ops_manager,
    )

    session = session_manager.start_session("operator-alerts")
    campaign = campaign_manager.ensure_campaign("operator-alerts", campaign_id="cmp-alerts")
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
    continuous_ops_manager.refresh_for_session(session)

    first_response = service.handle_update(
        TelegramUpdate(
            chat_id="chat-alerts",
            user_id="operator-alerts",
            text="What now?",
        )
    )
    assert [message.text for message in first_response.messages] == [
        "Base reply.",
        (
            "Operator intervention needed for campaign `cmp-alerts`:\n"
            "- Campaign loop is blocked: Continuous autonomy is enabled, but no recurring schedules or open work items are driving the campaign yet.\n"
            "  Recovery: Create a recurring schedule or open a new work item so the campaign has a bounded next move again.\n\n"
            "Reply `ack alerts` to quiet repeats until something changes, or `show alerts` to list current interventions."
        ),
    ]

    second_response = service.handle_update(
        TelegramUpdate(
            chat_id="chat-alerts",
            user_id="operator-alerts",
            text="Anything else?",
        )
    )
    assert [message.text for message in second_response.messages] == ["Base reply."]

    show_response = service.handle_update(
        TelegramUpdate(
            chat_id="chat-alerts",
            user_id="operator-alerts",
            text="show alerts",
        )
    )
    assert len(show_response.messages) == 1
    assert "Campaign loop is blocked" in show_response.messages[0].text

    ack_response = service.handle_update(
        TelegramUpdate(
            chat_id="chat-alerts",
            user_id="operator-alerts",
            text="ack alerts",
        )
    )
    assert [message.text for message in ack_response.messages] == [
        "Acknowledged 1 operator intervention(s). I will keep them quiet until something changes."
    ]

    after_ack_response = service.handle_update(
        TelegramUpdate(
            chat_id="chat-alerts",
            user_id="operator-alerts",
            text="Still there?",
        )
    )
    assert [message.text for message in after_ack_response.messages] == ["Base reply."]


def test_direct_schedule_control_resolves_loop_block_and_persists_compiled_intent(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    session_manager = SessionManager(JsonSessionStore(tmp_path / "sessions.json"))
    approval_manager = ApprovalManager(JsonApprovalStore(tmp_path / "approvals.json"))
    campaign_manager = CampaignManager(campaigns_root)
    work_item_manager = WorkItemManager(campaigns_root)
    schedule_manager = ScheduleManager(campaigns_root)
    signal_manager = CampaignSignalManager(campaigns_root)
    intervention_manager = OperatorInterventionManager(
        campaign_manager,
        schedule_manager,
        signal_manager,
    )
    continuous_ops_manager = ContinuousOpsManager(
        campaign_manager,
        work_item_manager,
        schedule_manager,
        signal_manager,
        intervention_manager=intervention_manager,
    )
    compiled_intent_store = CompiledIntentStore(campaigns_root)
    compiled_intent_applicator = CompiledIntentApplicator(schedule_manager=schedule_manager)
    intake = StructuredIntakeCoordinator(session_manager)
    orchestrator = PurposeBuiltOrchestrator(
        session_manager=session_manager,
        approval_manager=approval_manager,
        schedule_manager=schedule_manager,
        campaign_manager=campaign_manager,
        continuous_ops_manager=continuous_ops_manager,
        compiled_intent_store=compiled_intent_store,
        compiled_intent_applicator=compiled_intent_applicator,
    )
    service = TelegramAppService(
        session_manager=session_manager,
        approval_manager=approval_manager,
        orchestrator=orchestrator,
        intake_coordinator=intake,
        campaign_manager=campaign_manager,
        intervention_manager=intervention_manager,
        continuous_ops_manager=continuous_ops_manager,
    )

    session = session_manager.start_session("operator-control")
    campaign = campaign_manager.ensure_campaign("operator-control", campaign_id="cmp-control")
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
        data={"summary": "Plan ready for ongoing strategy refresh."},
    )
    session_manager.replace_workflow_snapshot(
        session,
        WorkflowSnapshot(
            stage=WorkflowStage.COMPLETE,
            summary="Initial planning is complete and ready for ongoing follow-up.",
        ),
    )
    campaign_manager.sync_session_memory(session)

    blocked_state = continuous_ops_manager.refresh_for_session(session)
    assert blocked_state is not None
    assert intervention_manager.list_open_for_campaign(campaign.campaign_id)

    response = service.handle_update(
        TelegramUpdate(
            chat_id="chat-control",
            user_id="operator-control",
            text="Set up a weekly strategy refresh for this campaign.",
        )
    )

    current_state = continuous_ops_manager.get_for_campaign(campaign.campaign_id)
    stored_intents = compiled_intent_store.list_for_campaign(campaign.campaign_id)
    stored_interventions = intervention_manager.list_for_campaign(campaign.campaign_id)

    assert "Saved a recurring `strategy` schedule" in response.messages[0].text
    assert len(stored_intents) == 1
    assert stored_intents[0].kind == "schedule.create"
    assert stored_intents[0].status is CompiledIntentStatus.APPLIED
    assert intervention_manager.list_open_for_campaign(campaign.campaign_id) == []
    assert len(stored_interventions) == 1
    assert stored_interventions[0].status is OperatorInterventionStatus.RESOLVED
    assert current_state is not None
    assert current_state.active_schedule_ids
    assert "no recurring schedules or open work items" not in current_state.blocked_reasons
