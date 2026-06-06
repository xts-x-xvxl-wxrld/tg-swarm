"""Production dispatcher for persisted conversation review triggers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from telegram_app.engagement_brain.coordinator import EngagementBrainCoordinator
from telegram_app.engagement_brain.models import EngagementBrainRunDisposition, EngagementBrainRunResult
from telegram_app.engagement_triage import CheapInboundTriageService, InboundTriageResult
from telegram_app.external_conversations import (
    ConversationReviewTrigger,
    ConversationReviewTriggerType,
    ExternalConversationManager,
    ExternalConversationTimingService,
)


@dataclass(slots=True)
class ConversationReviewDispatchOutcome:
    """One background review-dispatch result for logging and tests."""

    trigger: ConversationReviewTrigger
    status: str
    summary: str
    triage_result: InboundTriageResult | None = None
    run_result: EngagementBrainRunResult | None = None


class ConversationReviewDispatcher:
    """Claim persisted review moments and run the engagement brain safely."""

    def __init__(
        self,
        conversation_manager: ExternalConversationManager,
        coordinator: EngagementBrainCoordinator,
        *,
        conversation_timing_service: ExternalConversationTimingService | None = None,
        triage_service: CheapInboundTriageService | None = None,
        worker_id: str | None = None,
        claim_ttl_seconds: int = 300,
    ) -> None:
        self._conversation_manager = conversation_manager
        self._coordinator = coordinator
        self._worker_id = (worker_id or str(uuid4())).strip()
        self._claim_ttl_seconds = max(claim_ttl_seconds, 1)
        self._conversation_timing_service = conversation_timing_service or ExternalConversationTimingService(
            conversation_manager
        )
        self._triage_service = triage_service

    @property
    def worker_id(self) -> str:
        """Expose the stable worker id for logs and tests."""
        return self._worker_id

    def dispatch_next_review(
        self,
        *,
        now: datetime | None = None,
    ) -> ConversationReviewDispatchOutcome | None:
        """Claim and process the next eligible conversation review trigger."""
        trigger = self._conversation_manager.claim_next_review(
            owner_id=self._worker_id,
            claim_ttl_seconds=self._claim_ttl_seconds,
            now=now,
        )
        if trigger is None:
            return None

        triage_result = (
            self._triage_service.triage_review(
                trigger.campaign_id,
                trigger.conversation_id,
                trigger=trigger,
                now=now,
            )
            if self._triage_service is not None
            else None
        )
        if triage_result is not None and not triage_result.should_promote:
            if trigger.trigger_type is ConversationReviewTriggerType.FOLLOW_UP_DUE:
                self._conversation_timing_service.clear_follow_up_window(
                    trigger.campaign_id,
                    trigger.conversation_id,
                )
            self._conversation_manager.complete_review_claim(
                trigger.campaign_id,
                trigger.conversation_id,
                trigger=trigger,
                disposition="triage_complete",
                summary=triage_result.summary,
            )
            return ConversationReviewDispatchOutcome(
                trigger=trigger,
                status="completed",
                summary=triage_result.summary,
                triage_result=triage_result,
            )

        result = self._coordinator.review_conversation(
            trigger.campaign_id,
            trigger.conversation_id,
            trigger=trigger,
            now=now,
        )
        if result is None:
            self._conversation_manager.release_review_claim(
                trigger.campaign_id,
                trigger.conversation_id,
                trigger_key=trigger.trigger_key,
            )
            return ConversationReviewDispatchOutcome(
                trigger=trigger,
                status="released",
                summary="Released the review claim because bounded conversation context was unavailable.",
                triage_result=triage_result,
            )

        if (
            trigger.trigger_type is ConversationReviewTriggerType.FOLLOW_UP_DUE
            and result.disposition is not EngagementBrainRunDisposition.ENQUEUED
        ):
            self._conversation_timing_service.clear_follow_up_window(
                trigger.campaign_id,
                trigger.conversation_id,
            )

        self._conversation_manager.complete_review_claim(
            trigger.campaign_id,
            trigger.conversation_id,
            trigger=trigger,
            disposition=result.disposition.value,
            summary=result.summary,
            action_id=result.action_id,
        )
        return ConversationReviewDispatchOutcome(
            trigger=trigger,
            status="completed",
            summary=result.summary,
            triage_result=triage_result,
            run_result=result,
        )
