"""Campaign-scoped work-item storage and lifecycle helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from uuid import uuid4

from telegram_app.json_store import load_json_file, write_json_file
from telegram_app.models import WorkItemPriority, WorkItemRecord, WorkItemStatus

_OPEN_STATUSES = frozenset(
    {
        WorkItemStatus.PENDING,
        WorkItemStatus.IN_PROGRESS,
        WorkItemStatus.REVIEW_PENDING,
        WorkItemStatus.ESCALATED,
    }
)
_PRIORITY_ORDER = {
    WorkItemPriority.HIGH: 3,
    WorkItemPriority.MEDIUM: 2,
    WorkItemPriority.LOW: 1,
}
_STATUS_ORDER = {
    WorkItemStatus.REVIEW_PENDING: 3,
    WorkItemStatus.IN_PROGRESS: 2,
    WorkItemStatus.PENDING: 1,
    WorkItemStatus.ESCALATED: 0,
}


class WorkItemManager:
    """Own campaign-scoped work-item persistence."""

    def __init__(self, campaigns_root: str | Path) -> None:
        self._campaigns_root = Path(campaigns_root).resolve()
        self._lock = RLock()

    def ensure_work_item(
        self,
        campaign_id: str,
        *,
        owner_role: str,
        work_type: str,
        goal: str,
        constraints: list[str] | None = None,
        priority: WorkItemPriority = WorkItemPriority.MEDIUM,
        due_at: datetime | None = None,
        related_memory_refs: list[str] | None = None,
        schedule_id: str | None = None,
        status: WorkItemStatus = WorkItemStatus.IN_PROGRESS,
    ) -> WorkItemRecord:
        """Return the open work item for this slot or create a new one."""
        with self._lock:
            work_items = self.list_for_campaign(campaign_id)
            matching_items = [
                item
                for item in work_items
                if item.owner_role == owner_role
                and item.work_type == work_type
                and item.schedule_id == schedule_id
                and item.status in _OPEN_STATUSES
            ]
            if matching_items:
                work_item = max(matching_items, key=lambda item: item.updated_at)
                work_item.goal = goal
                work_item.constraints = list(constraints or [])
                work_item.priority = priority
                work_item.due_at = due_at
                work_item.related_memory_refs = list(related_memory_refs or [])
                if work_item.status is WorkItemStatus.PENDING and status is not WorkItemStatus.PENDING:
                    work_item.status = status
                work_item.touch()
                self.save(work_item)
                return work_item

            work_item = WorkItemRecord(
                work_item_id=str(uuid4()),
                campaign_id=campaign_id,
                owner_role=owner_role,
                work_type=work_type,
                goal=goal,
                constraints=list(constraints or []),
                priority=priority,
                status=status,
                due_at=due_at,
                related_memory_refs=list(related_memory_refs or []),
                schedule_id=schedule_id,
            )
            self.save(work_item)
            return work_item

    def get(self, campaign_id: str, work_item_id: str) -> WorkItemRecord | None:
        """Fetch one work item by id."""
        for item in self.list_for_campaign(campaign_id):
            if item.work_item_id == work_item_id:
                return item
        return None

    def list_for_campaign(self, campaign_id: str) -> list[WorkItemRecord]:
        """Return all work items for a campaign."""
        payload = load_json_file(self._file_path(campaign_id), default={"work_items": []})
        raw_items = payload.get("work_items", [])
        if not isinstance(raw_items, list):
            return []
        return [
            item
            for item in (WorkItemRecord.from_dict(raw_item) for raw_item in raw_items if isinstance(raw_item, dict))
            if item.work_item_id
        ]

    def list_open_for_campaign(self, campaign_id: str) -> list[WorkItemRecord]:
        """Return active non-terminal work items for a campaign."""
        return [item for item in self.list_for_campaign(campaign_id) if item.status in _OPEN_STATUSES]

    def get_primary_open_item(self, campaign_id: str) -> WorkItemRecord | None:
        """Return the highest-signal active work item for routing."""
        open_items = self.list_open_for_campaign(campaign_id)
        if not open_items:
            return None
        return max(
            open_items,
            key=lambda item: (
                _STATUS_ORDER.get(item.status, -1),
                _PRIORITY_ORDER.get(item.priority, 0),
                item.updated_at,
            ),
        )

    def save(self, work_item: WorkItemRecord) -> WorkItemRecord:
        """Insert or replace a work item record."""
        with self._lock:
            work_item.touch()
            existing_items = self.list_for_campaign(work_item.campaign_id)
            updated = False
            payload_items: list[dict[str, object]] = []
            for existing_item in existing_items:
                if existing_item.work_item_id == work_item.work_item_id:
                    payload_items.append(work_item.to_dict())
                    updated = True
                else:
                    payload_items.append(existing_item.to_dict())
            if not updated:
                payload_items.append(work_item.to_dict())
            write_json_file(self._file_path(work_item.campaign_id), {"work_items": payload_items})
            return work_item

    def update_status(
        self,
        campaign_id: str,
        work_item_id: str,
        *,
        status: WorkItemStatus,
        result_summary: str | None = None,
        escalation_reason: str | None = None,
        related_memory_refs: list[str] | None = None,
    ) -> WorkItemRecord | None:
        """Update the lifecycle state and summary fields for a work item."""
        with self._lock:
            work_item = self.get(campaign_id, work_item_id)
            if work_item is None:
                return None

            work_item.status = status
            if result_summary is not None:
                work_item.result_summary = result_summary
            if escalation_reason is not None:
                work_item.escalation_reason = escalation_reason
            if related_memory_refs is not None:
                work_item.related_memory_refs = list(related_memory_refs)
            if status in {WorkItemStatus.COMPLETED, WorkItemStatus.CANCELLED}:
                work_item.completed_at = datetime.now(UTC)
            elif status in _OPEN_STATUSES:
                work_item.completed_at = None
            self.save(work_item)
            return work_item

    def _file_path(self, campaign_id: str) -> Path:
        return self._campaigns_root / campaign_id / "work-items.json"
