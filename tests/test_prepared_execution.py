from __future__ import annotations

from telegram_app.live_execution import LiveActionStatus, LiveExecutionManager
from telegram_app.models import WorkItemStatus, WorkflowArtifactKind
from telegram_app.prepared_execution import (
    PreparedExecutionItemStatus,
    PreparedExecutionManager,
    PreparedExecutionService,
)
from telegram_app.sessions import JsonSessionStore, SessionManager
from telegram_app.work_items import WorkItemManager


def test_prepared_execution_activation_persists_batch_and_items(tmp_path) -> None:
    session_manager = SessionManager(JsonSessionStore(tmp_path / "sessions.json"))
    work_item_manager = WorkItemManager(tmp_path / "campaigns")
    live_execution_manager = LiveExecutionManager(tmp_path / "campaigns")
    prepared_execution_manager = PreparedExecutionManager(tmp_path / "campaigns")
    prepared_execution_service = PreparedExecutionService(
        prepared_execution_manager,
        live_execution_manager,
        session_manager=session_manager,
        work_item_manager=work_item_manager,
    )

    session = session_manager.start_session("operator-1")
    campaign_root = tmp_path / "campaigns" / "cmp-1"
    session_manager.attach_campaign(
        session,
        campaign_id="cmp-1",
        campaign_workspace_path=str(campaign_root),
    )
    session_manager.create_workflow_artifact(
        session,
        WorkflowArtifactKind.ACCOUNT_ASSIGNMENT_PLAN,
        "Account assignment plan",
        data={
            "plan_summary": "Activate the first day and hold the next day.",
            "assignments": [
                {
                    "community_name": "EU AI Founders",
                    "community_handle": "@eu_ai_founders",
                    "assigned_account": "account_senior_1",
                    "scheduled_posts": [
                        {
                            "day_offset": 0,
                            "time_window": "09:00-11:00",
                            "message_text": "Day-zero launch draft.",
                        },
                        {
                            "day_offset": 1,
                            "time_window": "10:00-12:00",
                            "message_text": "Day-one follow-up draft.",
                        },
                    ],
                }
            ],
        },
    )
    work_item_manager.ensure_work_item(
        "cmp-1",
        owner_role="account_manager",
        work_type="account_planning",
        goal="Prepare an account assignment plan.",
        status=WorkItemStatus.COMPLETED,
    )

    result = prepared_execution_service.activate_latest_plan(session)

    assert result.status == "activated"
    assert result.queued_count == 1
    assert result.held_count == 1
    assert result.blocked_count == 0
    assert result.batch is not None

    reloaded_manager = PreparedExecutionManager(tmp_path / "campaigns")
    persisted_batches = reloaded_manager.list_batches_for_campaign("cmp-1")
    persisted_items = reloaded_manager.list_items_for_campaign("cmp-1", batch_id=result.batch.batch_id)
    persisted_actions = live_execution_manager.list_queued_for_campaign("cmp-1")

    assert len(persisted_batches) == 1
    assert len(persisted_items) == 2
    assert {item.status for item in persisted_items} == {
        PreparedExecutionItemStatus.PREPARED,
        PreparedExecutionItemStatus.QUEUED,
    }
    assert len(persisted_actions) == 1
    assert persisted_actions[0].source_batch_id == result.batch.batch_id
    assert persisted_actions[0].status is LiveActionStatus.QUEUED


def test_prepared_execution_invalidation_supersedes_old_batch_and_cancels_pending_actions(tmp_path) -> None:
    session_manager = SessionManager(JsonSessionStore(tmp_path / "sessions.json"))
    work_item_manager = WorkItemManager(tmp_path / "campaigns")
    live_execution_manager = LiveExecutionManager(tmp_path / "campaigns")
    prepared_execution_manager = PreparedExecutionManager(tmp_path / "campaigns")
    prepared_execution_service = PreparedExecutionService(
        prepared_execution_manager,
        live_execution_manager,
        session_manager=session_manager,
        work_item_manager=work_item_manager,
    )

    session = session_manager.start_session("operator-2")
    session_manager.attach_campaign(
        session,
        campaign_id="cmp-2",
        campaign_workspace_path=str(tmp_path / "campaigns" / "cmp-2"),
    )
    artifact = session_manager.create_workflow_artifact(
        session,
        WorkflowArtifactKind.ACCOUNT_ASSIGNMENT_PLAN,
        "Account assignment plan",
        data={
            "plan_summary": "Initial plan.",
            "assignments": [
                {
                    "community_name": "EU AI Founders",
                    "community_handle": "@eu_ai_founders",
                    "assigned_account": "account_senior_1",
                    "scheduled_posts": [
                        {
                            "day_offset": 0,
                            "time_window": "09:00-11:00",
                            "message_text": "Initial live draft.",
                        },
                        {
                            "day_offset": 1,
                            "time_window": "10:00-12:00",
                            "message_text": "Future held draft.",
                        },
                    ],
                }
            ],
        },
    )
    work_item_manager.ensure_work_item(
        "cmp-2",
        owner_role="account_manager",
        work_type="account_planning",
        goal="Prepare an account assignment plan.",
        status=WorkItemStatus.COMPLETED,
    )

    first_activation = prepared_execution_service.activate_latest_plan(session)
    assert first_activation.batch is not None

    artifact.data["assignments"][0]["scheduled_posts"][0]["message_text"] = "Revised live draft."
    session_manager.save_workflow_artifact(session, artifact)
    invalidation = prepared_execution_service.invalidate_stale_prepared_state(session)

    assert invalidation.changed
    assert len(invalidation.superseded_batch_ids) == 1
    assert len(invalidation.cancelled_action_ids) == 1

    reloaded_batch = prepared_execution_manager.get_batch("cmp-2", first_activation.batch.batch_id)
    reloaded_items = prepared_execution_manager.list_items_for_campaign(
        "cmp-2",
        batch_id=first_activation.batch.batch_id,
    )
    queued_actions = live_execution_manager.list_for_campaign("cmp-2")

    assert reloaded_batch is not None
    assert reloaded_batch.status.value == "superseded"
    assert {item.status for item in reloaded_items} == {
        PreparedExecutionItemStatus.CANCELLED,
        PreparedExecutionItemStatus.SUPERSEDED,
    }
    assert queued_actions[0].status is LiveActionStatus.CANCELLED
