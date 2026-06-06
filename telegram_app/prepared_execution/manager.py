"""Campaign-backed persistence for prepared execution state."""

from __future__ import annotations

from pathlib import Path
from threading import RLock

from telegram_app.json_store import load_json_file, write_json_file
from telegram_app.prepared_execution.models import (
    PreparedExecutionBatch,
    PreparedExecutionBatchStatus,
    PreparedExecutionItem,
)


class PreparedExecutionManager:
    """Persist prepared execution batches and items under each campaign workspace."""

    def __init__(self, campaigns_root: str | Path) -> None:
        self._campaigns_root = Path(campaigns_root).resolve()
        self._lock = RLock()

    def save_batch(self, batch: PreparedExecutionBatch) -> PreparedExecutionBatch:
        """Insert or replace one prepared execution batch."""
        with self._lock:
            batches = self._load_batches(batch.campaign_id)
            batch.touch()
            batches[batch.batch_id] = batch
            self._write_batches(batch.campaign_id, batches)
            return batch

    def get_batch(self, campaign_id: str, batch_id: str) -> PreparedExecutionBatch | None:
        """Load one batch by campaign and identifier."""
        return self._load_batches(campaign_id).get(batch_id)

    def list_batches_for_campaign(self, campaign_id: str) -> list[PreparedExecutionBatch]:
        """Return all prepared execution batches for one campaign."""
        return sorted(
            self._load_batches(campaign_id).values(),
            key=lambda batch: batch.updated_at,
            reverse=True,
        )

    def find_latest_active_batch(self, campaign_id: str) -> PreparedExecutionBatch | None:
        """Return the newest active prepared batch for one campaign."""
        active_batches = [
            batch
            for batch in self.list_batches_for_campaign(campaign_id)
            if batch.is_active()
        ]
        return active_batches[0] if active_batches else None

    def find_latest_batch_by_fingerprint(
        self,
        campaign_id: str,
        source_plan_fingerprint: str,
    ) -> PreparedExecutionBatch | None:
        """Return the newest batch linked to the provided plan fingerprint."""
        normalized_fingerprint = source_plan_fingerprint.strip()
        if not normalized_fingerprint:
            return None
        matches = [
            batch
            for batch in self.list_batches_for_campaign(campaign_id)
            if batch.source_plan_fingerprint == normalized_fingerprint
        ]
        return matches[0] if matches else None

    def save_item(self, item: PreparedExecutionItem) -> PreparedExecutionItem:
        """Insert or replace one prepared execution item."""
        with self._lock:
            items = self._load_items(item.campaign_id)
            item.touch()
            items[item.prepared_item_id] = item
            self._write_items(item.campaign_id, items)
            return item

    def save_items(self, campaign_id: str, items: list[PreparedExecutionItem]) -> list[PreparedExecutionItem]:
        """Insert or replace many prepared execution items in one write."""
        with self._lock:
            existing_items = self._load_items(campaign_id)
            for item in items:
                item.touch()
                existing_items[item.prepared_item_id] = item
            self._write_items(campaign_id, existing_items)
            return items

    def list_items_for_campaign(
        self,
        campaign_id: str,
        *,
        batch_id: str | None = None,
    ) -> list[PreparedExecutionItem]:
        """Return prepared execution items for one campaign, optionally filtered to one batch."""
        items = list(self._load_items(campaign_id).values())
        if batch_id is not None:
            items = [item for item in items if item.batch_id == batch_id]
        return sorted(items, key=lambda item: item.updated_at, reverse=True)

    def get_item(self, campaign_id: str, prepared_item_id: str) -> PreparedExecutionItem | None:
        """Load one prepared item by identifier."""
        return self._load_items(campaign_id).get(prepared_item_id)

    def batches_path(self, campaign_id: str) -> Path:
        """Return the campaign-local prepared-batch state path."""
        return self._campaign_root(campaign_id) / "prepared-execution" / "batches.json"

    def items_path(self, campaign_id: str) -> Path:
        """Return the campaign-local prepared-item state path."""
        return self._campaign_root(campaign_id) / "prepared-execution" / "items.json"

    def _load_batches(self, campaign_id: str) -> dict[str, PreparedExecutionBatch]:
        payload = load_json_file(self.batches_path(campaign_id), default={"batches": {}})
        raw_batches = payload.get("batches", {})
        if not isinstance(raw_batches, dict):
            return {}
        return {
            batch.batch_id: batch
            for batch in (
                PreparedExecutionBatch.from_dict(raw_batch)
                for raw_batch in raw_batches.values()
                if isinstance(raw_batch, dict)
            )
            if batch.batch_id
        }

    def _write_batches(
        self,
        campaign_id: str,
        batches: dict[str, PreparedExecutionBatch],
    ) -> None:
        write_json_file(
            self.batches_path(campaign_id),
            {"batches": {batch_id: batch.to_dict() for batch_id, batch in batches.items()}},
        )

    def _load_items(self, campaign_id: str) -> dict[str, PreparedExecutionItem]:
        payload = load_json_file(self.items_path(campaign_id), default={"items": {}})
        raw_items = payload.get("items", {})
        if not isinstance(raw_items, dict):
            return {}
        return {
            item.prepared_item_id: item
            for item in (
                PreparedExecutionItem.from_dict(raw_item)
                for raw_item in raw_items.values()
                if isinstance(raw_item, dict)
            )
            if item.prepared_item_id
        }

    def _write_items(
        self,
        campaign_id: str,
        items: dict[str, PreparedExecutionItem],
    ) -> None:
        write_json_file(
            self.items_path(campaign_id),
            {"items": {item_id: item.to_dict() for item_id, item in items.items()}},
        )

    def _campaign_root(self, campaign_id: str) -> Path:
        return self._campaigns_root / campaign_id
