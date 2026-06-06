"""Campaign-scoped storage and dedupe helpers for live campaign signals."""

from __future__ import annotations

from pathlib import Path
from threading import RLock
from uuid import uuid4

from telegram_app.campaign_signals.models import (
    CampaignSignalCategory,
    CampaignSignalCandidate,
    CampaignSignalRecord,
    ObservationOperatorAttention,
    ObservationRecommendedNextStep,
    ObservationReviewBrief,
    ObservationReviewCursor,
    ObservationReviewResult,
    CampaignSignalSeverity,
    CampaignSignalState,
    utc_now,
)
from telegram_app.json_store import load_json_file, write_json_file

_SEVERITY_ORDER = {
    CampaignSignalSeverity.LOW: 1,
    CampaignSignalSeverity.MEDIUM: 2,
    CampaignSignalSeverity.HIGH: 3,
    CampaignSignalSeverity.CRITICAL: 4,
}


class CampaignSignalManager:
    """Own campaign-scoped signal persistence and unresolved lookups."""

    def __init__(self, campaigns_root: str | Path) -> None:
        self._campaigns_root = Path(campaigns_root).resolve()
        self._lock = RLock()

    def list_for_campaign(self, campaign_id: str) -> list[CampaignSignalRecord]:
        """Return all stored signals for one campaign."""
        payload = load_json_file(self._file_path(campaign_id), default={"signals": []})
        raw_signals = payload.get("signals", [])
        if not isinstance(raw_signals, list):
            return []
        return [
            signal
            for signal in (
                CampaignSignalRecord.from_dict(raw_signal)
                for raw_signal in raw_signals
                if isinstance(raw_signal, dict)
            )
            if signal.signal_id
        ]

    def get(self, campaign_id: str, signal_id: str) -> CampaignSignalRecord | None:
        """Fetch one signal by id."""
        for signal in self.list_for_campaign(campaign_id):
            if signal.signal_id == signal_id:
                return signal
        return None

    def list_review_results(self, campaign_id: str) -> list[ObservationReviewResult]:
        """Return persisted observation review results for one campaign."""
        payload = load_json_file(self._reviews_file_path(campaign_id), default={"reviews": []})
        raw_reviews = payload.get("reviews", [])
        if not isinstance(raw_reviews, list):
            return []
        return [
            review
            for review in (
                ObservationReviewResult.from_dict(raw_review)
                for raw_review in raw_reviews
                if isinstance(raw_review, dict)
            )
            if review.review_id
        ]

    def get_latest_review_result(self, campaign_id: str) -> ObservationReviewResult | None:
        """Return the most recent persisted review result for one campaign."""
        reviews = self.list_review_results(campaign_id)
        if not reviews:
            return None
        return max(reviews, key=lambda review: review.created_at)

    def get_review_cursor(self, campaign_id: str) -> ObservationReviewCursor:
        """Load the review cursor, tolerating missing files."""
        payload = load_json_file(self._cursor_file_path(campaign_id), default={})
        cursor = ObservationReviewCursor.from_dict(payload)
        if cursor.campaign_id:
            return cursor
        return ObservationReviewCursor(campaign_id=campaign_id)

    def list_unresolved(
        self,
        campaign_id: str,
        *,
        category: CampaignSignalCategory | None = None,
        review_eligible_only: bool = False,
        limit: int | None = None,
    ) -> list[CampaignSignalRecord]:
        """Return unresolved signals ordered by urgency and recency."""
        signals = [
            signal
            for signal in self.list_for_campaign(campaign_id)
            if signal.state is CampaignSignalState.UNRESOLVED
        ]
        if category is not None:
            signals = [signal for signal in signals if signal.category is category]
        if review_eligible_only:
            signals = [signal for signal in signals if signal.review_eligible]
        ordered = sorted(
            signals,
            key=lambda signal: (
                _SEVERITY_ORDER.get(signal.severity, 0),
                signal.last_happened_at,
                signal.updated_at,
            ),
            reverse=True,
        )
        if limit is None or limit < 1:
            return ordered
        return ordered[:limit]

    def select_review_batch(
        self,
        campaign_id: str,
        *,
        limit: int,
    ) -> list[CampaignSignalRecord]:
        """Return the next bounded batch of review-worthy unresolved signals."""
        if limit < 1:
            return []

        unresolved = self.list_unresolved(campaign_id, review_eligible_only=True)
        if not unresolved:
            return []

        cursor = self.get_review_cursor(campaign_id)
        last_reviewed_ids = set(cursor.last_reviewed_signal_ids)
        prioritized = [
            signal
            for signal in unresolved
            if signal.signal_id not in last_reviewed_ids or self._signal_has_new_pressure(signal)
        ]
        return prioritized[:limit]

    def upsert(
        self,
        candidate: CampaignSignalCandidate,
        *,
        dedupe_key: str,
    ) -> CampaignSignalRecord:
        """Refresh an unresolved matching signal or create a new one."""
        with self._lock:
            signals = self.list_for_campaign(candidate.campaign_id)
            existing = self._find_unresolved_by_dedupe_key(signals, dedupe_key)
            if existing is not None:
                existing.source_kind = candidate.source_kind.strip()
                existing.source_ref = candidate.source_ref.strip()
                existing.summary = candidate.summary.strip() or existing.summary
                existing.category = candidate.category
                existing.context_refs = self._merge_context_refs(existing.context_refs, candidate.context_refs)
                existing.account_id = candidate.account_id.strip() or existing.account_id
                existing.community_id = candidate.community_id.strip() or existing.community_id
                existing.conversation_id = candidate.conversation_id.strip() or existing.conversation_id
                existing.review_eligible = existing.review_eligible or candidate.review_eligible
                existing.severity = self._max_severity(existing.severity, candidate.severity)
                existing.last_happened_at = max(existing.last_happened_at, candidate.happened_at)
                existing.occurrence_count += 1
                self.save(existing)
                return existing

            signal = CampaignSignalRecord(
                signal_id=str(uuid4()),
                campaign_id=candidate.campaign_id.strip(),
                source_kind=candidate.source_kind.strip(),
                source_ref=candidate.source_ref.strip(),
                signal_type=candidate.signal_type.strip(),
                category=candidate.category,
                severity=candidate.severity,
                state=CampaignSignalState.UNRESOLVED,
                dedupe_key=dedupe_key.strip(),
                summary=candidate.summary.strip(),
                context_refs=self._merge_context_refs([], candidate.context_refs),
                account_id=candidate.account_id.strip(),
                community_id=candidate.community_id.strip(),
                conversation_id=candidate.conversation_id.strip(),
                first_happened_at=candidate.happened_at,
                last_happened_at=candidate.happened_at,
                occurrence_count=1,
                review_eligible=candidate.review_eligible,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            self.save(signal)
            return signal

    def save(self, signal: CampaignSignalRecord) -> CampaignSignalRecord:
        """Insert or replace one signal record."""
        with self._lock:
            signal.touch()
            existing_signals = self.list_for_campaign(signal.campaign_id)
            updated = False
            payload_signals: list[dict[str, object]] = []
            for existing_signal in existing_signals:
                if existing_signal.signal_id == signal.signal_id:
                    payload_signals.append(signal.to_dict())
                    updated = True
                else:
                    payload_signals.append(existing_signal.to_dict())
            if not updated:
                payload_signals.append(signal.to_dict())
            write_json_file(self._file_path(signal.campaign_id), {"signals": payload_signals})
            return signal

    def save_review_result(self, result: ObservationReviewResult) -> ObservationReviewResult:
        """Append one durable observation review result."""
        with self._lock:
            existing_reviews = self.list_review_results(result.campaign_id)
            payload_reviews = [review.to_dict() for review in existing_reviews]
            payload_reviews.append(result.to_dict())
            write_json_file(self._reviews_file_path(result.campaign_id), {"reviews": payload_reviews})
            return result

    def save_review_cursor(self, cursor: ObservationReviewCursor) -> ObservationReviewCursor:
        """Persist the compact latest-review cursor."""
        with self._lock:
            write_json_file(self._cursor_file_path(cursor.campaign_id), cursor.to_dict())
            return cursor

    def complete_review(
        self,
        campaign_id: str,
        *,
        work_item_id: str,
        trigger_source: str,
        review_reason: str,
        signal_ids: list[str],
        brief: ObservationReviewBrief,
    ) -> ObservationReviewResult:
        """Persist one review result, advance the cursor, and update signal review state."""
        reviewed_signals = [
            signal
            for signal_id in signal_ids
            if (signal := self.get(campaign_id, signal_id)) is not None
        ]
        result = ObservationReviewResult(
            review_id=str(uuid4()),
            campaign_id=campaign_id,
            work_item_id=work_item_id,
            trigger_source=trigger_source.strip(),
            review_reason=review_reason.strip(),
            signal_ids=[signal.signal_id for signal in reviewed_signals],
            signal_digest_count=len(reviewed_signals),
            summary=brief.summary,
            material_change=brief.material_change,
            priority_pressure=brief.priority_pressure,
            suggested_work_item_changes=list(brief.suggested_work_item_changes),
            suggested_posture_updates=list(brief.suggested_posture_updates),
            operator_attention_needed=brief.operator_attention_needed,
            recommended_next_step=brief.recommended_next_step,
            memory_note_lines=list(brief.memory_note_lines),
            created_at=utc_now(),
        )
        self.save_review_result(result)

        cursor = ObservationReviewCursor(
            campaign_id=campaign_id,
            last_review_id=result.review_id,
            last_reviewed_at=result.created_at,
            last_reviewed_signal_ids=[signal.signal_id for signal in reviewed_signals],
            last_reviewed_signal_dedupe_keys=[signal.dedupe_key for signal in reviewed_signals if signal.dedupe_key],
        )
        self.save_review_cursor(cursor)

        for signal in reviewed_signals:
            signal.last_reviewed_at = result.created_at
            signal.last_review_result_ref = result.review_id
            signal.state = self._post_review_state(signal, brief)
            self.save(signal)
        return result

    def _file_path(self, campaign_id: str) -> Path:
        return self._campaigns_root / campaign_id / "signals" / "signals.json"

    def _reviews_file_path(self, campaign_id: str) -> Path:
        return self._campaigns_root / campaign_id / "signals" / "reviews.json"

    def _cursor_file_path(self, campaign_id: str) -> Path:
        return self._campaigns_root / campaign_id / "signals" / "cursor.json"

    def _find_unresolved_by_dedupe_key(
        self,
        signals: list[CampaignSignalRecord],
        dedupe_key: str,
    ) -> CampaignSignalRecord | None:
        matching = [
            signal
            for signal in signals
            if signal.dedupe_key == dedupe_key and signal.state is CampaignSignalState.UNRESOLVED
        ]
        if not matching:
            return None
        return max(matching, key=lambda signal: signal.updated_at)

    def _max_severity(
        self,
        left: CampaignSignalSeverity,
        right: CampaignSignalSeverity,
    ) -> CampaignSignalSeverity:
        return left if _SEVERITY_ORDER[left] >= _SEVERITY_ORDER[right] else right

    def _merge_context_refs(self, current_refs: list[str], incoming_refs: list[str]) -> list[str]:
        merged: list[str] = []
        for value in [*current_refs, *incoming_refs]:
            normalized = str(value).strip()
            if normalized and normalized not in merged:
                merged.append(normalized)
        return merged[-8:]

    def _signal_has_new_pressure(self, signal: CampaignSignalRecord) -> bool:
        return signal.last_reviewed_at is None or signal.last_happened_at > signal.last_reviewed_at

    def _post_review_state(
        self,
        signal: CampaignSignalRecord,
        brief: ObservationReviewBrief,
    ) -> CampaignSignalState:
        if brief.operator_attention_needed is ObservationOperatorAttention.REQUIRED:
            return CampaignSignalState.UNRESOLVED
        if brief.recommended_next_step is ObservationRecommendedNextStep.OPERATOR_REVIEW:
            return CampaignSignalState.UNRESOLVED
        return CampaignSignalState.REVIEWED
