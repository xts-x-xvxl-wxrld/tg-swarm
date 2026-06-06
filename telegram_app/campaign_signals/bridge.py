"""Reusable bridge for emitting campaign signals from live runtime seams."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from telegram_app.campaign_signals.manager import CampaignSignalManager
from telegram_app.campaign_signals.models import (
    CampaignSignalCategory,
    CampaignSignalCandidate,
    CampaignSignalRecord,
    CampaignSignalSeverity,
    infer_signal_category,
    utc_now,
)
from telegram_app.campaign_signals.review import ObservationWorkRefresher

if TYPE_CHECKING:
    from telegram_app.continuous_ops.manager import ContinuousOpsManager


class CampaignSignalBridge:
    """Normalize signal candidates, persist them, and refresh observation pressure."""

    def __init__(
        self,
        manager: CampaignSignalManager,
        *,
        observation_work_refresher: ObservationWorkRefresher | None = None,
        continuous_ops_manager: ContinuousOpsManager | None = None,
    ) -> None:
        self._manager = manager
        self._observation_work_refresher = observation_work_refresher
        self._continuous_ops_manager = continuous_ops_manager

    def record(
        self,
        *,
        campaign_id: str,
        source_kind: str,
        source_ref: str,
        signal_type: str,
        category: CampaignSignalCategory | None = None,
        severity: CampaignSignalSeverity,
        summary: str,
        context_refs: list[str] | None = None,
        account_id: str = "",
        community_id: str = "",
        conversation_id: str = "",
        happened_at: datetime | None = None,
        review_eligible: bool = False,
        dedupe_key_hint: str = "",
        trigger_source: str = "signal_bridge",
    ) -> CampaignSignalRecord:
        """Persist one normalized signal and refresh observation work when warranted."""
        candidate = CampaignSignalCandidate(
            campaign_id=campaign_id.strip(),
            source_kind=source_kind.strip(),
            source_ref=source_ref.strip(),
            signal_type=signal_type.strip(),
            category=category or infer_signal_category(signal_type),
            severity=severity,
            summary=summary.strip(),
            context_refs=list(context_refs or []),
            account_id=account_id.strip(),
            community_id=community_id.strip(),
            conversation_id=conversation_id.strip(),
            happened_at=happened_at or utc_now(),
            review_eligible=review_eligible,
            dedupe_key_hint=dedupe_key_hint.strip(),
        )
        dedupe_key = self._build_dedupe_key(candidate)
        signal = self._manager.upsert(candidate, dedupe_key=dedupe_key)
        if self._observation_work_refresher is not None:
            self._observation_work_refresher.maybe_refresh_for_signal(
                signal,
                trigger_source=trigger_source,
                refresh_reason=signal.summary,
            )
        if self._continuous_ops_manager is not None:
            self._continuous_ops_manager.refresh_for_campaign(signal.campaign_id)
        return signal

    def _build_dedupe_key(self, candidate: CampaignSignalCandidate) -> str:
        if candidate.dedupe_key_hint:
            return candidate.dedupe_key_hint

        parts = [candidate.campaign_id, candidate.signal_type, candidate.source_kind]
        if candidate.conversation_id:
            parts.extend(["conversation", candidate.conversation_id])
        elif candidate.community_id:
            parts.extend(["community", candidate.community_id])
        elif candidate.account_id:
            parts.extend(["account", candidate.account_id])
        elif candidate.source_ref:
            parts.extend(["source", candidate.source_ref])
        return "|".join(parts)
