"""Deterministic helpers for refreshing observation work from signal pressure."""

from __future__ import annotations

from telegram_app.campaign_signals.manager import CampaignSignalManager
from telegram_app.campaign_signals.models import (
    CampaignSignalRecord,
    CampaignSignalSeverity,
    CampaignSignalState,
)
from telegram_app.models import WorkItemPriority, WorkItemRecord, WorkItemStatus
from telegram_app.work_items import WorkItemManager

OBSERVATION_WORK_TYPE = "observation"
OBSERVATION_OWNER_ROLE = "observation"
OBSERVATION_WORK_GOAL = "Review unresolved campaign signals that may require planning or posture changes."
OBSERVATION_CONTEXT_LIMIT = 8
OBSERVATION_CONSTRAINTS = [
    "Review only compact campaign signals and existing campaign context.",
    "Do not mutate execution or approval state directly.",
]


class ObservationWorkRefresher:
    """Turn deterministic signal pressure into one reusable observation work item."""

    def __init__(
        self,
        signal_manager: CampaignSignalManager,
        work_item_manager: WorkItemManager,
    ) -> None:
        self._signal_manager = signal_manager
        self._work_item_manager = work_item_manager

    def maybe_refresh_for_signal(
        self,
        signal: CampaignSignalRecord,
        *,
        trigger_source: str = "signal_bridge",
        refresh_reason: str = "",
    ) -> WorkItemRecord | None:
        """Create or refresh observation work when one signal creates real review pressure."""
        if not self._requires_review(signal):
            return None
        return self.refresh_for_campaign(
            signal.campaign_id,
            trigger_source=trigger_source,
            refresh_reason=refresh_reason or signal.summary,
        )

    def refresh_for_campaign(
        self,
        campaign_id: str,
        *,
        trigger_source: str = "signal_bridge",
        refresh_reason: str = "",
    ) -> WorkItemRecord | None:
        """Create or update the pending observation work item for one campaign."""
        review_signals = [
            signal
            for signal in self._signal_manager.select_review_batch(
                campaign_id,
                limit=OBSERVATION_CONTEXT_LIMIT,
            )
            if self._requires_review(signal)
        ]
        if not review_signals:
            return None

        top_signal = review_signals[0]
        context_refs = [f"signal:{signal.signal_id}" for signal in review_signals]
        return self._work_item_manager.ensure_work_item(
            campaign_id,
            owner_role=OBSERVATION_OWNER_ROLE,
            work_type=OBSERVATION_WORK_TYPE,
            goal=OBSERVATION_WORK_GOAL,
            constraints=list(OBSERVATION_CONSTRAINTS),
            priority=self._priority_for_signals(review_signals),
            related_memory_refs=[],
            trigger_source=trigger_source.strip(),
            refresh_reason=refresh_reason.strip() or top_signal.summary,
            context_refs=context_refs,
            status=WorkItemStatus.PENDING,
        )

    def _requires_review(self, signal: CampaignSignalRecord) -> bool:
        if signal.state is not CampaignSignalState.UNRESOLVED or not signal.review_eligible:
            return False
        if signal.severity in {CampaignSignalSeverity.HIGH, CampaignSignalSeverity.CRITICAL}:
            return True
        return signal.occurrence_count >= 2

    def _priority_for_signals(
        self,
        review_signals: list[CampaignSignalRecord],
    ) -> WorkItemPriority:
        if any(signal.severity in {CampaignSignalSeverity.HIGH, CampaignSignalSeverity.CRITICAL} for signal in review_signals):
            return WorkItemPriority.HIGH
        if any(signal.occurrence_count >= 3 for signal in review_signals):
            return WorkItemPriority.MEDIUM
        return WorkItemPriority.LOW
