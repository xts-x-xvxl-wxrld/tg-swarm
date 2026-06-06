"""Campaign-backed persistence helpers for autonomous send state."""

from __future__ import annotations

from pathlib import Path
from threading import RLock

from telegram_app.autonomous_send.models import (
    AutonomousSendMode,
    AutonomousSendPosture,
    AutonomousSendReviewRecord,
    AutonomousSendReviewStatus,
    utc_now,
)
from telegram_app.json_store import load_json_file, write_json_file


class AutonomousSendManager:
    """Persist autonomous send posture and review-needed records per campaign."""

    def __init__(self, campaigns_root: str | Path) -> None:
        self._campaigns_root = Path(campaigns_root).resolve()
        self._lock = RLock()

    def get_posture(self, campaign_id: str) -> AutonomousSendPosture:
        """Return the campaign posture, defaulting conservative when missing."""
        normalized_campaign_id = campaign_id.strip()
        if not normalized_campaign_id:
            return AutonomousSendPosture(campaign_id="")
        payload = load_json_file(self.posture_path(normalized_campaign_id), default={})
        posture = AutonomousSendPosture.from_dict(payload)
        if posture.campaign_id:
            return posture
        return AutonomousSendPosture(campaign_id=normalized_campaign_id)

    def save_posture(self, posture: AutonomousSendPosture) -> AutonomousSendPosture:
        """Persist one campaign posture."""
        with self._lock:
            write_json_file(self.posture_path(posture.campaign_id), posture.to_dict())
        return posture

    def update_posture(
        self,
        campaign_id: str,
        *,
        group_outreach_mode: AutonomousSendMode | None = None,
        group_reply_mode: AutonomousSendMode | None = None,
        dm_reply_mode: AutonomousSendMode | None = None,
        updated_by: str = "",
        notes: str = "",
    ) -> AutonomousSendPosture:
        """Mutate and persist one campaign posture in place."""
        posture = self.get_posture(campaign_id)
        if group_outreach_mode is not None:
            posture.group_outreach_mode = group_outreach_mode
        if group_reply_mode is not None:
            posture.group_reply_mode = group_reply_mode
        if dm_reply_mode is not None:
            posture.dm_reply_mode = dm_reply_mode
        if updated_by.strip():
            posture.updated_by = updated_by.strip()
        if notes.strip():
            posture.notes = notes.strip()
        posture.updated_at = utc_now()
        return self.save_posture(posture)

    def get_review(self, campaign_id: str, review_id: str) -> AutonomousSendReviewRecord | None:
        """Load one review-needed record by id."""
        if not campaign_id or not review_id:
            return None
        payload = self._load_reviews_payload(campaign_id)
        raw_review = payload.get("reviews", {}).get(review_id)
        if not isinstance(raw_review, dict):
            return None
        review = AutonomousSendReviewRecord.from_dict(raw_review)
        return review if review.review_id else None

    def save_review(self, review: AutonomousSendReviewRecord) -> AutonomousSendReviewRecord:
        """Persist one review-needed record."""
        with self._lock:
            payload = self._load_reviews_payload(review.campaign_id)
            raw_reviews = payload.setdefault("reviews", {})
            if not isinstance(raw_reviews, dict):
                raw_reviews = {}
                payload["reviews"] = raw_reviews
            raw_reviews[review.review_id] = review.to_dict()
            payload["updated_at"] = utc_now().isoformat()
            write_json_file(self.reviews_path(review.campaign_id), payload)
        return review

    def list_reviews(self, campaign_id: str) -> list[AutonomousSendReviewRecord]:
        """Return all review-needed records for one campaign."""
        payload = self._load_reviews_payload(campaign_id)
        raw_reviews = payload.get("reviews", {})
        if not isinstance(raw_reviews, dict):
            return []
        reviews = [
            AutonomousSendReviewRecord.from_dict(item)
            for item in raw_reviews.values()
            if isinstance(item, dict)
        ]
        return sorted(reviews, key=lambda item: item.created_at, reverse=True)

    def supersede_pending_reviews(
        self,
        campaign_id: str,
        conversation_id: str,
        *,
        action_type: str = "",
        resolution_note: str = "",
    ) -> list[AutonomousSendReviewRecord]:
        """Retire stale pending review records that no longer belong on the active send path."""
        normalized_campaign_id = campaign_id.strip()
        normalized_conversation_id = conversation_id.strip()
        normalized_action_type = action_type.strip()
        if not normalized_campaign_id or not normalized_conversation_id:
            return []

        superseded_reviews: list[AutonomousSendReviewRecord] = []
        with self._lock:
            payload = self._load_reviews_payload(normalized_campaign_id)
            raw_reviews = payload.get("reviews", {})
            if not isinstance(raw_reviews, dict):
                return []

            now = utc_now()
            changed = False
            for review_id, raw_review in raw_reviews.items():
                if not isinstance(raw_review, dict):
                    continue
                review = AutonomousSendReviewRecord.from_dict(raw_review)
                if review.status is not AutonomousSendReviewStatus.PENDING:
                    continue
                if review.conversation_id != normalized_conversation_id:
                    continue
                if normalized_action_type and review.action_type != normalized_action_type:
                    continue
                review.status = AutonomousSendReviewStatus.SUPERSEDED
                review.resolved_at = now
                review.resolved_by = "autonomous_send_cutover"
                review.resolution_note = (
                    resolution_note.strip()
                    or "Superseded because supported reply-path sends no longer wait for operator review."
                )
                raw_reviews[review_id] = review.to_dict()
                superseded_reviews.append(review)
                changed = True

            if changed:
                payload["updated_at"] = now.isoformat()
                write_json_file(self.reviews_path(normalized_campaign_id), payload)
        return superseded_reviews

    def posture_path(self, campaign_id: str) -> Path:
        """Return the campaign-local posture file path."""
        return self._campaign_root(campaign_id) / "autonomous_send" / "posture.json"

    def reviews_path(self, campaign_id: str) -> Path:
        """Return the campaign-local review-needed state path."""
        return self._campaign_root(campaign_id) / "autonomous_send" / "reviews.json"

    def _load_reviews_payload(self, campaign_id: str) -> dict[str, object]:
        return load_json_file(self.reviews_path(campaign_id), default={"reviews": {}, "updated_at": ""})

    def _campaign_root(self, campaign_id: str) -> Path:
        return self._campaigns_root / campaign_id
