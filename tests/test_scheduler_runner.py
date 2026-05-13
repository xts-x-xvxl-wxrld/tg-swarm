from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from telegram_app.campaigns import CampaignManager
from telegram_app.models import WorkItemStatus
from telegram_app.orchestrator.orchestrator import PurposeBuiltOrchestrator, ScheduledExecutionOutcome
from telegram_app.scheduling import ScheduleManager, SchedulerLeaseManager
from telegram_app.sessions import JsonSessionStore, SessionManager
from telegram_app.work_items import WorkItemManager


def test_scheduler_lease_manager_allows_only_one_live_owner(tmp_path) -> None:
    now = datetime(2026, 5, 13, 9, 0, tzinfo=UTC)
    first = SchedulerLeaseManager(tmp_path, owner_id="worker-a", lease_ttl_seconds=30)
    second = SchedulerLeaseManager(tmp_path, owner_id="worker-b", lease_ttl_seconds=30)

    assert first.try_acquire_or_renew(now=now) is True
    assert second.try_acquire_or_renew(now=now) is False
    assert second.try_acquire_or_renew(now=now + timedelta(seconds=31)) is True


def test_scheduled_low_yield_discovery_pauses_after_repeated_misses(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    campaign_manager = CampaignManager(campaigns_root)
    work_item_manager = WorkItemManager(campaigns_root)
    schedule_manager = ScheduleManager(campaigns_root)
    session_manager = SessionManager(JsonSessionStore(tmp_path / "sessions.json"))

    campaign = campaign_manager.ensure_campaign("operator-scheduled", campaign_id="cmp-scheduled")
    session = session_manager.start_session("operator-scheduled")
    session_manager.attach_campaign(
        session,
        campaign_id=campaign.campaign_id,
        campaign_workspace_path=campaign.workspace_path,
    )

    due_time = datetime(2026, 5, 13, 9, 0, tzinfo=UTC)
    schedule = schedule_manager.create_interval_schedule(
        "cmp-scheduled",
        owner_role="discovery",
        work_type="discovery",
        goal="Produce five new validated communities.",
        interval_minutes=120,
        next_run_at=due_time,
        evaluation_metric="validated_community_count",
        minimum_value=5,
        pause_after_consecutive_misses=2,
    )

    with patch("anthropic.Anthropic", return_value=MagicMock()):
        orchestrator = PurposeBuiltOrchestrator(
            session_manager=session_manager,
            work_item_manager=work_item_manager,
            schedule_manager=schedule_manager,
        )

    with patch.object(
        orchestrator,
        "_execute_scheduled_stage",
        return_value=ScheduledExecutionOutcome(
            result_summary="Scheduled discovery refresh found only 2 validated communities.",
            metric_value=2,
        ),
    ):
        first_item = orchestrator.handle_scheduled_work(schedule, now=due_time)
        assert first_item is not None
        assert first_item.status is WorkItemStatus.REVIEW_PENDING

        after_first_run = schedule_manager.get("cmp-scheduled", schedule.schedule_id)
        assert after_first_run is not None
        assert after_first_run.status.value == "active"
        assert after_first_run.consecutive_miss_count == 1

        second_run_time = after_first_run.next_run_at
        second_item = orchestrator.handle_scheduled_work(after_first_run, now=second_run_time)
        assert second_item is not None
        assert second_item.status is WorkItemStatus.ESCALATED
        assert "Paused schedule after 2 consecutive misses" in second_item.escalation_reason

    paused_schedule = schedule_manager.get("cmp-scheduled", schedule.schedule_id)
    assert paused_schedule is not None
    assert paused_schedule.status.value == "paused"
    assert paused_schedule.consecutive_miss_count == 2
    assert paused_schedule.last_outcome_value == 2
