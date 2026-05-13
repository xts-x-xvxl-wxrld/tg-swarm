"""Minimal scheduled-work dispatch helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from telegram_app.models import ScheduleRecord, WorkItemRecord
from telegram_app.scheduling.manager import ScheduleManager


class ScheduledWorkHandler(Protocol):
    """Protocol implemented by orchestrators that can react to due schedules."""

    def handle_scheduled_work(
        self,
        schedule: ScheduleRecord,
        *,
        now: datetime | None = None,
    ) -> WorkItemRecord | None:
        """Create or refresh campaign work for a due schedule."""


class ScheduledWorkDispatcher:
    """Dispatch due campaign schedules through the orchestrator."""

    def __init__(self, schedule_manager: ScheduleManager, handler: ScheduledWorkHandler) -> None:
        self._schedule_manager = schedule_manager
        self._handler = handler

    def dispatch_due_work(self, *, now: datetime | None = None) -> list[WorkItemRecord]:
        """Dispatch every due active schedule and return any resulting work items."""
        current_time = now or datetime.now(UTC)
        dispatched_items: list[WorkItemRecord] = []
        for schedule in self._schedule_manager.list_due(current_time):
            work_item = self._handler.handle_scheduled_work(schedule, now=current_time)
            if work_item is not None:
                dispatched_items.append(work_item)
        return dispatched_items
