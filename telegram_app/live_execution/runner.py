"""Dedicated worker loop for queued live execution actions."""

from __future__ import annotations

import logging
import time

from telegram_app.live_execution.models import LiveActionRecord
from telegram_app.live_execution.service import LiveExecutionService

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL_SECONDS = 5.0


class LiveExecutionRunner:
    """Run queued managed-account execution work from a dedicated worker."""

    def __init__(
        self,
        service: LiveExecutionService,
        *,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    ) -> None:
        self._service = service
        self._poll_interval_seconds = poll_interval_seconds

    def run_once(self) -> LiveActionRecord | None:
        """Dispatch the next ready live action, if one exists."""
        action = self._service.dispatch_next_ready()
        if action is not None:
            logger.info(
                "Processed live action %s with status=%s.",
                action.action_id,
                action.status.value,
            )
        return action

    def run_forever(self) -> None:
        """Run the live execution worker loop continuously."""
        logger.info("Starting live execution runner. worker_id=%s", self._service.worker_id)
        while True:
            try:
                self.run_once()
            except Exception:
                logger.exception("Live execution tick failed.")
            time.sleep(self._poll_interval_seconds)
