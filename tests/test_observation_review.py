from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

from telegram_app.approvals import ApprovalManager, JsonApprovalStore
from telegram_app.campaign_signals import (
    CampaignSignalBridge,
    CampaignSignalManager,
    CampaignSignalSeverity,
    ObservationMaterialChange,
    ObservationOperatorAttention,
    ObservationPriorityPressure,
    ObservationRecommendedNextStep,
    ObservationReviewBrief,
    ObservationWorkRefresher,
)
from telegram_app.campaigns import CampaignManager
from telegram_app.capabilities import StubCommunityCapability
from telegram_app.models import WorkItemPriority, WorkItemStatus, WorkflowArtifactKind, WorkflowSnapshot, WorkflowStage
from telegram_app.orchestrator.orchestrator import PurposeBuiltOrchestrator
from telegram_app.sessions import JsonSessionStore, SessionManager
from telegram_app.transport import TelegramUpdate
from telegram_app.work_items import WorkItemManager


def test_observation_cursor_skips_same_reviewed_pressure_until_new_signal_arrives(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    signal_manager = CampaignSignalManager(campaigns_root)
    bridge = CampaignSignalBridge(signal_manager)

    signal = bridge.record(
        campaign_id="cmp-observation-cursor",
        source_kind="live_execution",
        source_ref="action-1",
        signal_type="policy_block_repeated",
        severity=CampaignSignalSeverity.HIGH,
        summary="A repeated policy block now affects campaign outreach.",
        account_id="account-1",
        review_eligible=True,
    )

    first_batch = signal_manager.select_review_batch("cmp-observation-cursor", limit=8)
    assert [item.signal_id for item in first_batch] == [signal.signal_id]

    review_result = signal_manager.complete_review(
        "cmp-observation-cursor",
        work_item_id="work-observation-1",
        trigger_source="test",
        review_reason="Repeated policy blocks warranted review.",
        signal_ids=[signal.signal_id],
        brief=ObservationReviewBrief(
            summary="The block matters, but the current plan can hold for now.",
            material_change=ObservationMaterialChange.NO,
            priority_pressure=ObservationPriorityPressure.MEDIUM,
            suggested_work_item_changes=[],
            suggested_posture_updates=[],
            operator_attention_needed=ObservationOperatorAttention.NONE,
            recommended_next_step=ObservationRecommendedNextStep.KEEP_CURRENT_PLAN,
            memory_note_lines=["Policy friction is being watched."],
        ),
    )

    assert review_result.signal_digest_count == 1
    assert signal_manager.select_review_batch("cmp-observation-cursor", limit=8) == []

    refreshed = bridge.record(
        campaign_id="cmp-observation-cursor",
        source_kind="live_execution",
        source_ref="action-2",
        signal_type="policy_block_repeated",
        severity=CampaignSignalSeverity.HIGH,
        summary="A new policy block reopened the same campaign risk.",
        account_id="account-1",
        review_eligible=True,
    )

    second_batch = signal_manager.select_review_batch("cmp-observation-cursor", limit=8)
    assert [item.signal_id for item in second_batch] == [refreshed.signal_id]


def test_pending_observation_review_persists_result_and_refreshes_strategy_work(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    session_manager = SessionManager(JsonSessionStore(tmp_path / "sessions.json"))
    campaign_manager = CampaignManager(campaigns_root)
    work_item_manager = WorkItemManager(campaigns_root)
    signal_manager = CampaignSignalManager(campaigns_root)
    session = session_manager.start_session("operator-observation-review")
    campaign = campaign_manager.ensure_campaign("operator-observation-review", campaign_id="cmp-observation-review")
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
        data={"objective": "Reach AI founders", "target_audience": "AI founders", "geography": "Europe"},
    )
    session_manager.create_workflow_artifact(
        session=session,
        kind=WorkflowArtifactKind.COMMUNITY_SHORTLIST,
        title="Community shortlist",
        data={"communities": [{"name": "EU AI Founders", "handle": "@eu_ai_founders"}]},
    )
    campaign_manager.sync_session_memory(session)

    bridge = CampaignSignalBridge(
        signal_manager,
        observation_work_refresher=ObservationWorkRefresher(signal_manager, work_item_manager),
    )
    signal = bridge.record(
        campaign_id=campaign.campaign_id,
        source_kind="live_execution",
        source_ref="action-flagged",
        signal_type="account_flagged_or_banned",
        severity=CampaignSignalSeverity.CRITICAL,
        summary="Managed account `reader-1` was flagged and campaign throughput changed.",
        account_id="reader-1",
        review_eligible=True,
    )

    observation_output = """Account availability changed enough to refresh strategy before more live effort is spent.

OBSERVATION_REVIEW_JSON
```json
{
  "summary": "One core account is now flagged, so strategy should rebalance around lower-risk communities and pacing.",
  "material_change": "yes",
  "priority_pressure": "high",
  "suggested_work_item_changes": [
    {
      "work_type": "strategy",
      "action": "refresh",
      "reason": "Channel prioritization should change after the flagged-account loss."
    }
  ],
  "suggested_posture_updates": [
    {
      "kind": "account_rest_review",
      "summary": "Rest or replace the flagged account before relying on it again."
    }
  ],
  "operator_attention_needed": "none",
  "recommended_next_step": "refresh_strategy",
  "memory_note_lines": [
    "A flagged account reduced safe campaign capacity and reopened strategy review."
  ]
}
```"""

    fake_content_block = MagicMock()
    fake_content_block.text = observation_output
    fake_api_response = MagicMock()
    fake_api_response.content = [fake_content_block]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = fake_api_response

    with patch("anthropic.Anthropic", return_value=mock_client):
        orchestrator = PurposeBuiltOrchestrator(
            session_manager=session_manager,
            work_item_manager=work_item_manager,
            campaign_manager=campaign_manager,
            signal_manager=signal_manager,
        )
        completed_work_item = orchestrator.run_pending_observation_work(campaign.campaign_id)

    assert completed_work_item is not None
    assert completed_work_item.status is WorkItemStatus.COMPLETED
    assert "Follow-on: refreshed `strategy` work." in completed_work_item.result_summary

    latest_review = signal_manager.get_latest_review_result(campaign.campaign_id)
    assert latest_review is not None
    assert latest_review.recommended_next_step is ObservationRecommendedNextStep.REFRESH_STRATEGY
    assert latest_review.signal_ids == [signal.signal_id]

    reloaded_signal = signal_manager.get(campaign.campaign_id, signal.signal_id)
    assert reloaded_signal is not None
    assert reloaded_signal.state.value == "reviewed"
    assert reloaded_signal.last_review_result_ref == latest_review.review_id

    strategy_work_item = work_item_manager.find_latest(campaign.campaign_id, work_type="strategy")
    assert strategy_work_item is not None
    assert strategy_work_item.status is WorkItemStatus.IN_PROGRESS
    assert strategy_work_item.trigger_source == "observation_review"
    assert strategy_work_item.context_refs[0] == f"review:{latest_review.review_id}"

    notes_path = campaigns_root / campaign.campaign_id / "artifacts" / "operational-notes.json"
    notes_payload = json.loads(notes_path.read_text(encoding="utf-8"))
    assert notes_payload["notes"][0]["line"] == "A flagged account reduced safe campaign capacity and reopened strategy review."


def test_operator_turn_prefers_review_pending_strategy_over_observation_work(tmp_path) -> None:
    session_store = JsonSessionStore(tmp_path / "sessions.json")
    session_manager = SessionManager(session_store)
    approval_manager = ApprovalManager(JsonApprovalStore(tmp_path / "approvals.json"))
    campaign_manager = CampaignManager(tmp_path / "campaigns")
    work_item_manager = WorkItemManager(tmp_path / "campaigns")
    signal_manager = CampaignSignalManager(tmp_path / "campaigns")
    session = session_manager.start_session("operator-observation-route")
    campaign = campaign_manager.ensure_campaign("operator-observation-route", campaign_id="cmp-observation-route")
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
        data={"objective": "Reach AI founders", "target_audience": "AI founders", "geography": "Europe"},
    )
    session_manager.create_workflow_artifact(
        session=session,
        kind=WorkflowArtifactKind.COMMUNITY_SHORTLIST,
        title="Community shortlist",
        data={"communities": [{"name": "EU AI Founders", "handle": "@eu_ai_founders"}]},
    )
    session_manager.replace_workflow_snapshot(
        session,
        WorkflowSnapshot(stage=WorkflowStage.STRATEGY, summary="Strategy playbook ready for operator review."),
    )
    work_item_manager.ensure_work_item(
        campaign.campaign_id,
        owner_role="observation",
        work_type="observation",
        goal="Review unresolved campaign signals.",
        status=WorkItemStatus.PENDING,
    )
    work_item_manager.ensure_work_item(
        campaign.campaign_id,
        owner_role="strategy",
        work_type="strategy",
        goal="Review the strategy playbook.",
        status=WorkItemStatus.REVIEW_PENDING,
    )

    mock_client = MagicMock()

    with patch("anthropic.Anthropic", return_value=mock_client):
        orchestrator = PurposeBuiltOrchestrator(
            session_manager=session_manager,
            approval_manager=approval_manager,
            community_capability=StubCommunityCapability(),
            work_item_manager=work_item_manager,
            campaign_manager=campaign_manager,
            signal_manager=signal_manager,
        )
        response = orchestrator.handle_turn(
            session=session,
            update=TelegramUpdate(
                chat_id="chat-observation-route",
                user_id="operator-observation-route",
                text="what should I review first?",
            ),
        )

    assert "strategy draft ready" in response.messages[0].text.lower()
    assert mock_client.messages.create.call_count == 0


def test_operator_turn_routes_high_priority_observation_before_planning_refresh(tmp_path) -> None:
    session_store = JsonSessionStore(tmp_path / "sessions.json")
    session_manager = SessionManager(session_store)
    campaign_manager = CampaignManager(tmp_path / "campaigns")
    work_item_manager = WorkItemManager(tmp_path / "campaigns")
    signal_manager = CampaignSignalManager(tmp_path / "campaigns")
    session = session_manager.start_session("operator-observation-priority")
    campaign = campaign_manager.ensure_campaign("operator-observation-priority", campaign_id="cmp-observation-priority")
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
        data={"objective": "Reach AI founders", "target_audience": "AI founders", "geography": "Europe"},
    )
    session_manager.create_workflow_artifact(
        session=session,
        kind=WorkflowArtifactKind.COMMUNITY_SHORTLIST,
        title="Community shortlist",
        data={"communities": [{"name": "EU AI Founders", "handle": "@eu_ai_founders"}]},
    )
    session_manager.replace_workflow_snapshot(
        session,
        WorkflowSnapshot(stage=WorkflowStage.STRATEGY, summary="Strategy refresh is underway."),
    )
    work_item_manager.ensure_work_item(
        campaign.campaign_id,
        owner_role="strategy",
        work_type="strategy",
        goal="Refresh the strategy playbook.",
        priority=WorkItemPriority.MEDIUM,
        status=WorkItemStatus.IN_PROGRESS,
    )

    bridge = CampaignSignalBridge(
        signal_manager,
        observation_work_refresher=ObservationWorkRefresher(signal_manager, work_item_manager),
    )
    signal = bridge.record(
        campaign_id=campaign.campaign_id,
        source_kind="live_execution",
        source_ref="action-critical",
        signal_type="account_flagged_or_banned",
        severity=CampaignSignalSeverity.CRITICAL,
        summary="A core managed account was flagged and campaign posture may need review.",
        account_id="reader-1",
        review_eligible=True,
    )

    observation_output = """A flagged account materially changed safe campaign capacity, so I reviewed the live pressure first.

OBSERVATION_REVIEW_JSON
```json
{
  "summary": "A flagged core account changed execution capacity, but the current planning work can continue while the team monitors account coverage.",
  "material_change": "no",
  "priority_pressure": "high",
  "suggested_work_item_changes": [],
  "suggested_posture_updates": [
    {
      "kind": "account_rest_review",
      "summary": "Avoid leaning on the flagged account until posture is reviewed."
    }
  ],
  "operator_attention_needed": "none",
  "recommended_next_step": "keep_current_plan",
  "memory_note_lines": [
    "A flagged account triggered observation review before routine planning refresh continued."
  ]
}
```"""

    fake_content_block = MagicMock()
    fake_content_block.text = observation_output
    fake_api_response = MagicMock()
    fake_api_response.content = [fake_content_block]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = fake_api_response

    with patch("anthropic.Anthropic", return_value=mock_client):
        orchestrator = PurposeBuiltOrchestrator(
            session_manager=session_manager,
            community_capability=StubCommunityCapability(),
            work_item_manager=work_item_manager,
            campaign_manager=campaign_manager,
            signal_manager=signal_manager,
        )
        response = orchestrator.handle_turn(
            session=session,
            update=TelegramUpdate(
                chat_id="chat-observation-priority",
                user_id="operator-observation-priority",
                text="what changed most recently?",
            ),
        )

    assert "reviewed the live pressure first" in response.messages[0].text.lower()
    assert mock_client.messages.create.call_count == 1

    observation_work_item = work_item_manager.find_latest(campaign.campaign_id, work_type="observation")
    assert observation_work_item is not None
    assert observation_work_item.status is WorkItemStatus.COMPLETED

    latest_review = signal_manager.get_latest_review_result(campaign.campaign_id)
    assert latest_review is not None
    assert latest_review.signal_ids == [signal.signal_id]


def test_setup_gate_keeps_operator_turn_out_of_observation_routing(tmp_path) -> None:
    session_store = JsonSessionStore(tmp_path / "sessions.json")
    session_manager = SessionManager(session_store)
    campaign_manager = CampaignManager(tmp_path / "campaigns")
    work_item_manager = WorkItemManager(tmp_path / "campaigns")
    signal_manager = CampaignSignalManager(tmp_path / "campaigns")
    session = session_manager.start_session("operator-setup-gate")
    campaign = campaign_manager.ensure_campaign("operator-setup-gate", campaign_id="cmp-setup-gate")
    session_manager.attach_campaign(
        session,
        campaign.campaign_id,
        campaign.workspace_path,
        canonical_memory_files=campaign.canonical_files,
        agent_memory_files=campaign.agent_memory_files,
    )
    work_item_manager.ensure_work_item(
        campaign.campaign_id,
        owner_role="observation",
        work_type="observation",
        goal="Review unresolved campaign signals.",
        priority=WorkItemPriority.HIGH,
        status=WorkItemStatus.PENDING,
    )

    fake_content_block = MagicMock()
    fake_content_block.text = "Let's finish setup first so the campaign has enough context."
    fake_api_response = MagicMock()
    fake_api_response.content = [fake_content_block]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = fake_api_response

    with patch("anthropic.Anthropic", return_value=mock_client):
        orchestrator = PurposeBuiltOrchestrator(
            session_manager=session_manager,
            community_capability=StubCommunityCapability(),
            work_item_manager=work_item_manager,
            campaign_manager=campaign_manager,
            signal_manager=signal_manager,
        )
        response = orchestrator.handle_turn(
            session=session,
            update=TelegramUpdate(
                chat_id="chat-setup-gate",
                user_id="operator-setup-gate",
                text="what should happen next?",
            ),
        )

    assert "finish setup first" in response.messages[0].text.lower()
    observation_work_item = work_item_manager.find_latest(campaign.campaign_id, work_type="observation")
    assert observation_work_item is not None
    assert observation_work_item.status is WorkItemStatus.PENDING
    assert signal_manager.get_latest_review_result(campaign.campaign_id) is None


def test_pending_observation_review_uses_summary_model_override(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    session_manager = SessionManager(JsonSessionStore(tmp_path / "sessions.json"))
    campaign_manager = CampaignManager(campaigns_root)
    work_item_manager = WorkItemManager(campaigns_root)
    signal_manager = CampaignSignalManager(campaigns_root)
    session = session_manager.start_session("operator-observation-model")
    campaign = campaign_manager.ensure_campaign("operator-observation-model", campaign_id="cmp-observation-model")
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
        data={"objective": "Reach AI founders", "target_audience": "AI founders", "geography": "Europe"},
    )
    bridge = CampaignSignalBridge(
        signal_manager,
        observation_work_refresher=ObservationWorkRefresher(signal_manager, work_item_manager),
    )
    bridge.record(
        campaign_id=campaign.campaign_id,
        source_kind="live_execution",
        source_ref="action-1",
        signal_type="policy_block_repeated",
        severity=CampaignSignalSeverity.HIGH,
        summary="Repeated policy friction needs observation review.",
        account_id="reader-1",
        review_eligible=True,
    )

    observation_output = """Observation review completed.

OBSERVATION_REVIEW_JSON
```json
{
  "summary": "Policy friction is worth tracking, but no strategy refresh is required yet.",
  "material_change": "no",
  "priority_pressure": "medium",
  "suggested_work_item_changes": [],
  "suggested_posture_updates": [],
  "operator_attention_needed": "none",
  "recommended_next_step": "keep_current_plan",
  "memory_note_lines": [
    "Observation review ran on the cheaper summary model path."
  ]
}
```"""

    fake_content_block = MagicMock()
    fake_content_block.text = observation_output
    fake_api_response = MagicMock()
    fake_api_response.content = [fake_content_block]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = fake_api_response

    env_updates = {
        "DEFAULT_MODEL": "anthropic/claude-sonnet-4-6",
        "SUMMARY_MODEL": "anthropic/claude-haiku-3-5",
    }

    with patch("anthropic.Anthropic", return_value=mock_client), patch.dict(os.environ, env_updates, clear=False):
        orchestrator = PurposeBuiltOrchestrator(
            session_manager=session_manager,
            work_item_manager=work_item_manager,
            campaign_manager=campaign_manager,
            signal_manager=signal_manager,
        )
        orchestrator.run_pending_observation_work(campaign.campaign_id)

    assert mock_client.messages.create.call_args.kwargs["model"] == "claude-haiku-3-5"
