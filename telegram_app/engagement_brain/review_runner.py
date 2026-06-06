"""Dedicated worker loop for persisted conversation review triggers."""

from __future__ import annotations

import logging
import time

from telegram_app.engagement_brain.review_dispatcher import (
    ConversationReviewDispatchOutcome,
    ConversationReviewDispatcher,
)

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL_SECONDS = 5.0


class ConversationReviewRunner:
    """Run bounded conversation reviews from a dedicated background worker."""

    def __init__(
        self,
        dispatcher: ConversationReviewDispatcher,
        *,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    ) -> None:
        self._dispatcher = dispatcher
        self._poll_interval_seconds = poll_interval_seconds

    def run_once(self) -> ConversationReviewDispatchOutcome | None:
        """Dispatch the next eligible review, if one exists."""
        outcome = self._dispatcher.dispatch_next_review()
        if outcome is not None:
            logger.info(
                "Processed conversation review trigger %s for %s with status=%s.",
                outcome.trigger.trigger_key,
                outcome.trigger.conversation_id,
                outcome.status,
            )
        return outcome

    def run_forever(self) -> None:
        """Run the conversation-review worker continuously."""
        logger.info(
            "Starting conversation review runner. worker_id=%s",
            self._dispatcher.worker_id,
        )
        while True:
            try:
                self.run_once()
            except Exception:
                logger.exception("Conversation review tick failed.")
            time.sleep(self._poll_interval_seconds)
