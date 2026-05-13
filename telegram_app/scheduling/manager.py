"""Campaign-scoped recurring schedule persistence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock
from uuid import uuid4

from telegram_app.json_store import load_json_file, write_json_file
from telegram_app.models import ScheduleRecord, ScheduleStatus, WorkItemPriority


class ScheduleManager:
    """Own recurring schedule persistence for campaigns."""

    def __init__(self, campaigns_root: str | Path) -> None:
        self._campaigns_root = Path(campaigns_root).resolve()
        self._lock = RLock()

    def create_interval_schedule(
        self,
        campaign_id: str,
        *,
        owner_role: str,
        work_type: str,
        goal: str,
        interval_minutes: int,
        constraints: list[str] | None = None,
        priority: WorkItemPriority = WorkItemPriority.MEDIUM,
        next_run_at: datetime | None = None,
        evaluation_metric: str = "",
        minimum_value: int | None = None,
        pause_after_consecutive_misses: int | None = None,
    ) -> ScheduleRecord:
        """Create and persist a simple recurring schedule."""
        schedule = ScheduleRecord(
            schedule_id=str(uuid4()),
            campaign_id=campaign_id,
            owner_role=owner_role,
            work_type=work_type,
            goal=goal,
            interval_minutes=interval_minutes,
            next_run_at=next_run_at or datetime.now(UTC) + timedelta(minutes=interval_minutes),
            constraints=list(constraints or []),
            priority=priority,
            evaluation_metric=evaluation_metric.strip(),
            minimum_value=minimum_value,
            pause_after_consecutive_misses=pause_after_consecutive_misses,
        )
        self.save(schedule)
        return schedule

    def get(self, campaign_id: str, schedule_id: str) -> ScheduleRecord | None:
        """Fetch one schedule by id."""
        for schedule in self.list_for_campaign(campaign_id):
            if schedule.schedule_id == schedule_id:
                return schedule
        return None

    def list_for_campaign(self, campaign_id: str) -> list[ScheduleRecord]:
        """Return all schedules for a campaign."""
        payload = load_json_file(self._file_path(campaign_id), default={"schedules": []})
        raw_schedules = payload.get("schedules", [])
        if not isinstance(raw_schedules, list):
            return []
        return [
            schedule
            for schedule in (
                ScheduleRecord.from_dict(raw_schedule)
                for raw_schedule in raw_schedules
                if isinstance(raw_schedule, dict)
            )
            if schedule.schedule_id
        ]

    def list_due(self, now: datetime | None = None) -> list[ScheduleRecord]:
        """Return all active schedules whose next run time has arrived."""
        current_time = now or datetime.now(UTC)
        due_schedules: list[ScheduleRecord] = []
        if not self._campaigns_root.exists():
            return due_schedules

        for campaign_dir in self._campaigns_root.iterdir():
            if not campaign_dir.is_dir():
                continue
            for schedule in self.list_for_campaign(campaign_dir.name):
                if schedule.status is ScheduleStatus.ACTIVE and schedule.next_run_at <= current_time:
                    due_schedules.append(schedule)
        return due_schedules

    def save(self, schedule: ScheduleRecord) -> ScheduleRecord:
        """Insert or replace a schedule record."""
        with self._lock:
            schedule.touch()
            schedules = self.list_for_campaign(schedule.campaign_id)
            updated = False
            payloads: list[dict[str, object]] = []
            for existing_schedule in schedules:
                if existing_schedule.schedule_id == schedule.schedule_id:
                    payloads.append(schedule.to_dict())
                    updated = True
                else:
                    payloads.append(existing_schedule.to_dict())
            if not updated:
                payloads.append(schedule.to_dict())
            write_json_file(self._file_path(schedule.campaign_id), {"schedules": payloads})
            return schedule

    def find_latest(
        self,
        campaign_id: str,
        *,
        work_type: str | None = None,
        owner_role: str | None = None,
        statuses: set[ScheduleStatus] | None = None,
    ) -> ScheduleRecord | None:
        """Return the most recently updated schedule matching the requested filters."""
        schedules = self.list_for_campaign(campaign_id)
        if work_type is not None:
            schedules = [schedule for schedule in schedules if schedule.work_type == work_type]
        if owner_role is not None:
            schedules = [schedule for schedule in schedules if schedule.owner_role == owner_role]
        if statuses is not None:
            schedules = [schedule for schedule in schedules if schedule.status in statuses]
        if not schedules:
            return None
        return max(schedules, key=lambda schedule: schedule.updated_at)

    def update_status(
        self,
        campaign_id: str,
        schedule_id: str,
        *,
        status: ScheduleStatus,
        reset_next_run_at: bool = False,
    ) -> ScheduleRecord | None:
        """Update one schedule lifecycle state."""
        with self._lock:
            schedule = self.get(campaign_id, schedule_id)
            if schedule is None:
                return None
            schedule.status = status
            if reset_next_run_at:
                schedule.next_run_at = datetime.now(UTC) + timedelta(minutes=schedule.interval_minutes)
            self.save(schedule)
            return schedule

    def record_run(
        self,
        campaign_id: str,
        schedule_id: str,
        *,
        ran_at: datetime | None = None,
    ) -> ScheduleRecord | None:
        """Advance the schedule after a dispatch without outcome metadata."""
        return self.record_outcome(campaign_id, schedule_id, ran_at=ran_at)

    def record_outcome(
        self,
        campaign_id: str,
        schedule_id: str,
        *,
        ran_at: datetime | None = None,
        metric_value: int | None = None,
        outcome_summary: str = "",
        error: str = "",
    ) -> ScheduleRecord | None:
        """Advance a schedule and capture outcome metadata for the run."""
        with self._lock:
            schedule = self.get(campaign_id, schedule_id)
            if schedule is None:
                return None
            current_time = ran_at or datetime.now(UTC)
            schedule.last_run_at = current_time
            schedule.next_run_at = current_time + timedelta(minutes=schedule.interval_minutes)
            schedule.last_outcome_value = metric_value
            schedule.last_error = error.strip()
            schedule.last_outcome_summary = (outcome_summary or error).strip()
            if self._did_miss_target(schedule, metric_value=metric_value, error=error):
                schedule.consecutive_miss_count += 1
            else:
                schedule.consecutive_miss_count = 0
            if self._should_pause(schedule):
                schedule.status = ScheduleStatus.PAUSED
            self.save(schedule)
            return schedule

    def _file_path(self, campaign_id: str) -> Path:
        return self._campaigns_root / campaign_id / "schedules.json"

    def _did_miss_target(
        self,
        schedule: ScheduleRecord,
        *,
        metric_value: int | None,
        error: str,
    ) -> bool:
        if error.strip():
            return True
        if not schedule.evaluation_metric or schedule.minimum_value is None:
            return False
        if metric_value is None:
            return True
        return metric_value < schedule.minimum_value

    def _should_pause(self, schedule: ScheduleRecord) -> bool:
        limit = schedule.pause_after_consecutive_misses
        if limit is None or limit <= 0:
            return False
        return schedule.consecutive_miss_count >= limit
