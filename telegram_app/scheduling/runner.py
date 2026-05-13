"""Dedicated scheduler-worker helpers for recurring campaign work."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging
import os
from pathlib import Path
import time
from uuid import uuid4

from telegram_app.json_store import load_json_file, write_json_file
from telegram_app.models import WorkItemRecord
from telegram_app.scheduling.dispatcher import ScheduledWorkDispatcher

logger = logging.getLogger(__name__)

DEFAULT_LEASE_TTL_SECONDS = 30
DEFAULT_POLL_INTERVAL_SECONDS = 10.0
DEFAULT_GUARD_STALE_SECONDS = 10.0
DEFAULT_GUARD_WAIT_SECONDS = 0.05
DEFAULT_GUARD_ATTEMPTS = 5


class SchedulerLeaseManager:
    """Coordinate one active scheduler worker with a filesystem-backed lease."""

    def __init__(
        self,
        state_dir: str | Path,
        *,
        owner_id: str | None = None,
        lease_ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS,
    ) -> None:
        self._state_dir = Path(state_dir)
        self._owner_id = owner_id or str(uuid4())
        self._lease_ttl_seconds = lease_ttl_seconds
        self._lease_path = self._state_dir / "scheduler-lease.json"
        self._guard_path = self._state_dir / "scheduler-lease.lock"

    @property
    def owner_id(self) -> str:
        """Expose the scheduler-owner identifier for logs and tests."""
        return self._owner_id

    def try_acquire_or_renew(self, *, now: datetime | None = None) -> bool:
        """Acquire or renew leadership when no other non-expired worker owns it."""
        current_time = now or datetime.now(UTC)
        if not self._acquire_guard(current_time):
            return False

        try:
            lease_payload = load_json_file(self._lease_path, default={})
            active_owner = str(lease_payload.get("owner_id", "")).strip()
            expires_at = self._parse_datetime(lease_payload.get("expires_at"))
            if active_owner and active_owner != self._owner_id and expires_at is not None and expires_at > current_time:
                return False

            write_json_file(
                self._lease_path,
                {
                    "owner_id": self._owner_id,
                    "expires_at": (current_time + timedelta(seconds=self._lease_ttl_seconds)).isoformat(),
                    "updated_at": current_time.isoformat(),
                },
            )
            return True
        finally:
            self._release_guard()

    def _acquire_guard(self, current_time: datetime) -> bool:
        self._state_dir.mkdir(parents=True, exist_ok=True)
        for _attempt in range(DEFAULT_GUARD_ATTEMPTS):
            try:
                file_descriptor = os.open(
                    self._guard_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
                os.close(file_descriptor)
                return True
            except FileExistsError:
                if self._guard_is_stale(current_time):
                    self._guard_path.unlink(missing_ok=True)
                    continue
                time.sleep(DEFAULT_GUARD_WAIT_SECONDS)
        return False

    def _guard_is_stale(self, current_time: datetime) -> bool:
        if not self._guard_path.exists():
            return False
        age_seconds = current_time.timestamp() - self._guard_path.stat().st_mtime
        return age_seconds >= DEFAULT_GUARD_STALE_SECONDS

    def _release_guard(self) -> None:
        self._guard_path.unlink(missing_ok=True)

    def _parse_datetime(self, raw_value: object) -> datetime | None:
        if not isinstance(raw_value, str) or not raw_value.strip():
            return None
        try:
            return datetime.fromisoformat(raw_value)
        except ValueError:
            return None


class ScheduledWorkRunner:
    """Run scheduled work from a dedicated worker loop."""

    def __init__(
        self,
        dispatcher: ScheduledWorkDispatcher,
        lease_manager: SchedulerLeaseManager,
        *,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    ) -> None:
        self._dispatcher = dispatcher
        self._lease_manager = lease_manager
        self._poll_interval_seconds = poll_interval_seconds

    def run_once(self, *, now: datetime | None = None) -> list[WorkItemRecord]:
        """Dispatch due work when this worker currently holds the scheduler lease."""
        if not self._lease_manager.try_acquire_or_renew(now=now):
            logger.debug("Skipping scheduler tick because another worker currently owns the lease.")
            return []
        dispatched_items = self._dispatcher.dispatch_due_work(now=now)
        if dispatched_items:
            logger.info("Dispatched %d scheduled work item(s).", len(dispatched_items))
        return dispatched_items

    def run_forever(self) -> None:
        """Run the scheduler loop continuously as a dedicated process."""
        logger.info("Starting scheduled work runner. owner_id=%s", self._lease_manager.owner_id)
        while True:
            try:
                self.run_once()
            except Exception:
                logger.exception("Scheduled work tick failed.")
            time.sleep(self._poll_interval_seconds)
