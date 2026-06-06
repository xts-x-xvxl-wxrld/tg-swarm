"""Build and persist a campaign-owned continuous-autonomy summary."""

from __future__ import annotations

from datetime import UTC, datetime
from collections import defaultdict

from telegram_app.campaign_intent import AUTONOMY_POSTURE_KEY, BOUNDED_MODE_KEY
from telegram_app.campaign_signals.manager import CampaignSignalManager
from telegram_app.campaign_signals.models import (
    CampaignSignalCategory,
    CampaignSignalSeverity,
    ObservationOperatorAttention,
    ObservationRecommendedNextStep,
)
from telegram_app.campaigns import CampaignManager
from telegram_app.external_conversations import ExternalConversationManager, ExternalConversationStatus
from telegram_app.intake import get_campaign_intent_artifact, get_workflow_snapshot
from telegram_app.models import (
    CampaignRecord,
    CampaignStatus,
    ScheduleRecord,
    ScheduleStatus,
    SessionRecord,
    WorkItemRecord,
    WorkItemStatus,
    WorkflowStage,
)
from telegram_app.scheduling import ScheduleManager
from telegram_app.work_items import WorkItemManager
from telegram_app.operator_notifications import OperatorInterventionManager

from .models import ContinuousAutonomyMode, ContinuousOpsState, ContinuousOpsStatus
from .storage import (
    load_continuous_ops_state_for_workspace,
    write_continuous_ops_state_for_workspace,
)

_OPEN_NON_ESCALATED_STATUSES = frozenset(
    {
        WorkItemStatus.PENDING,
        WorkItemStatus.IN_PROGRESS,
        WorkItemStatus.REVIEW_PENDING,
    }
)
_SEVERITY_ORDER = {
    CampaignSignalSeverity.LOW: 1,
    CampaignSignalSeverity.MEDIUM: 2,
    CampaignSignalSeverity.HIGH: 3,
    CampaignSignalSeverity.CRITICAL: 4,
}
_PROMISING_THREAD_STALE_HOURS = 72
_COMMERCIAL_HOTSPOT_WINDOW_HOURS = 24 * 7


class ContinuousOpsManager:
    """Own the compact state that says whether a campaign can keep running."""

    def __init__(
        self,
        campaign_manager: CampaignManager,
        work_item_manager: WorkItemManager,
        schedule_manager: ScheduleManager,
        signal_manager: CampaignSignalManager,
        conversation_manager: ExternalConversationManager | None = None,
        intervention_manager: OperatorInterventionManager | None = None,
    ) -> None:
        self._campaign_manager = campaign_manager
        self._work_item_manager = work_item_manager
        self._schedule_manager = schedule_manager
        self._signal_manager = signal_manager
        self._conversation_manager = conversation_manager
        self._intervention_manager = intervention_manager

    def refresh_for_session(self, session: SessionRecord) -> ContinuousOpsState | None:
        """Recompute and persist state using the current in-memory session view."""
        if not session.campaign_id or not session.campaign_workspace_path:
            return None
        campaign = self._campaign_manager.get(session.campaign_id)
        if campaign is None:
            return None
        return self._refresh(
            campaign,
            session=session,
            workspace_path=session.campaign_workspace_path,
        )

    def refresh_for_campaign(self, campaign_id: str) -> ContinuousOpsState | None:
        """Recompute and persist state from campaign-owned background context."""
        campaign = self._campaign_manager.get(campaign_id)
        if campaign is None:
            return None
        session = self._campaign_manager.build_background_session(
            campaign_id,
            stage=WorkflowStage.COMPLETE,
            summary="Refresh continuous campaign operations state.",
        )
        return self._refresh(
            campaign,
            session=session,
            workspace_path=campaign.workspace_path,
        )

    def get_for_campaign(self, campaign_id: str) -> ContinuousOpsState | None:
        """Return the last persisted state for a campaign when present."""
        campaign = self._campaign_manager.get(campaign_id)
        if campaign is None:
            return None
        return load_continuous_ops_state_for_workspace(campaign.workspace_path)

    def _refresh(
        self,
        campaign: CampaignRecord,
        *,
        session: SessionRecord | None,
        workspace_path: str,
    ) -> ContinuousOpsState:
        previous_state = load_continuous_ops_state_for_workspace(workspace_path)
        work_items = self._work_item_manager.list_open_for_campaign(campaign.campaign_id)
        schedules = self._schedule_manager.list_for_campaign(campaign.campaign_id)
        unresolved_signals = self._signal_manager.list_unresolved(campaign.campaign_id)
        reviewable_signals = self._signal_manager.list_unresolved(
            campaign.campaign_id,
            review_eligible_only=True,
        )
        conversations = (
            self._conversation_manager.list_for_campaign(campaign.campaign_id)
            if self._conversation_manager is not None
            else []
        )
        commercial_summary = self._build_commercial_summary(
            conversations,
            unresolved_signals,
        )
        latest_review = self._signal_manager.get_latest_review_result(campaign.campaign_id)
        workflow_snapshot = get_workflow_snapshot(session) if session is not None else None
        campaign_intent = get_campaign_intent_artifact(session) if session is not None else None
        autonomy_mode = self._resolve_autonomy_mode(
            campaign_intent.data if campaign_intent is not None else {}
        )
        status, summary, blocked_reasons, operator_attention_required = self._determine_status(
            campaign=campaign,
            autonomy_mode=autonomy_mode,
            workflow_snapshot=workflow_snapshot,
            work_items=work_items,
            schedules=schedules,
            latest_review=latest_review,
            reviewable_signal_count=len(reviewable_signals),
        )
        next_scheduled_run_at = min(
            (
                schedule.next_run_at
                for schedule in schedules
                if schedule.status is ScheduleStatus.ACTIVE
            ),
            default=None,
        )
        state = ContinuousOpsState(
            campaign_id=campaign.campaign_id,
            autonomy_mode=autonomy_mode,
            loop_status=status,
            status_summary=summary,
            blocked_reasons=blocked_reasons,
            active_work_types=_unique(
                item.work_type
                for item in work_items
                if item.status in _OPEN_NON_ESCALATED_STATUSES
            ),
            review_pending_work_types=_unique(
                item.work_type
                for item in work_items
                if item.status is WorkItemStatus.REVIEW_PENDING
            ),
            active_schedule_ids=[
                schedule.schedule_id
                for schedule in schedules
                if schedule.status is ScheduleStatus.ACTIVE
            ],
            paused_schedule_ids=[
                schedule.schedule_id
                for schedule in schedules
                if schedule.status is ScheduleStatus.PAUSED
            ],
            next_scheduled_run_at=next_scheduled_run_at,
            unresolved_signal_count=len(unresolved_signals),
            reviewable_signal_count=len(reviewable_signals),
            highest_signal_severity=self._highest_signal_severity(unresolved_signals),
            commercial_summary=commercial_summary["summary"],
            promising_active_thread_count=commercial_summary["promising_active_thread_count"],
            objection_heavy_thread_count=commercial_summary["objection_heavy_thread_count"],
            conversion_ready_thread_count=commercial_summary["conversion_ready_thread_count"],
            unresolved_high_opportunity_thread_count=commercial_summary["unresolved_high_opportunity_thread_count"],
            stale_promising_thread_count=commercial_summary["stale_promising_thread_count"],
            high_yield_account_labels=commercial_summary["high_yield_account_labels"],
            high_yield_community_labels=commercial_summary["high_yield_community_labels"],
            latest_observation_summary=latest_review.summary if latest_review is not None else "",
            latest_observation_attention=(
                latest_review.operator_attention_needed.value
                if latest_review is not None
                else ""
            ),
            latest_observation_next_step=(
                latest_review.recommended_next_step.value
                if latest_review is not None
                else ""
            ),
            operator_attention_required=operator_attention_required,
            last_refreshed_at=datetime.now(UTC),
        )
        write_continuous_ops_state_for_workspace(workspace_path, state)
        if self._intervention_manager is not None:
            self._intervention_manager.refresh_for_campaign(
                campaign.campaign_id,
                continuous_ops_state=state,
            )
        if self._workspace_refresh_needed(previous_state, state):
            self._campaign_manager.refresh_workspace(campaign.campaign_id)
        return state

    def _determine_status(
        self,
        *,
        campaign: CampaignRecord,
        autonomy_mode: ContinuousAutonomyMode,
        workflow_snapshot,
        work_items: list[WorkItemRecord],
        schedules: list[ScheduleRecord],
        latest_review,
        reviewable_signal_count: int,
    ) -> tuple[ContinuousOpsStatus, str, list[str], bool]:
        if campaign.status is CampaignStatus.PAUSED:
            return (
                ContinuousOpsStatus.PAUSED,
                "Campaign is paused, so autonomous work is stopped until it is resumed.",
                [],
                False,
            )

        blocked_reasons: list[str] = []
        operator_attention_required = False
        if latest_review is not None:
            if latest_review.operator_attention_needed is ObservationOperatorAttention.REQUIRED:
                operator_attention_required = True
                blocked_reasons.append(
                    latest_review.summary
                    or "Observation review requires operator attention before autonomous work continues."
                )
            elif latest_review.recommended_next_step is ObservationRecommendedNextStep.OPERATOR_REVIEW:
                operator_attention_required = True
                blocked_reasons.append(
                    latest_review.summary
                    or "Observation review handed the campaign back for operator review."
                )

        for work_item in work_items:
            if work_item.status is not WorkItemStatus.ESCALATED:
                continue
            reason = (work_item.escalation_reason or work_item.result_summary).strip()
            if reason and reason not in blocked_reasons:
                blocked_reasons.append(reason)

        for schedule in schedules:
            if not self._is_auto_paused_schedule(schedule):
                continue
            reason = self._build_schedule_pause_reason(schedule)
            if reason not in blocked_reasons:
                blocked_reasons.append(reason)

        active_work_items = [
            item
            for item in work_items
            if item.status in _OPEN_NON_ESCALATED_STATUSES
        ]
        active_schedules = [
            schedule
            for schedule in schedules
            if schedule.status is ScheduleStatus.ACTIVE
        ]
        if (
            autonomy_mode is ContinuousAutonomyMode.CONTINUOUS
            and workflow_snapshot is not None
            and workflow_snapshot.stage in {WorkflowStage.ACCOUNT_PLANNING, WorkflowStage.COMPLETE}
            and not active_work_items
            and not active_schedules
            and reviewable_signal_count < 1
        ):
            blocked_reasons.append(
                "Continuous autonomy is enabled, but no recurring schedules or open work items are driving the campaign yet."
            )

        if blocked_reasons:
            return (
                ContinuousOpsStatus.BLOCKED,
                blocked_reasons[0],
                blocked_reasons,
                operator_attention_required,
            )

        if active_work_items or active_schedules or reviewable_signal_count > 0:
            return (
                ContinuousOpsStatus.RUNNING,
                self._build_running_summary(
                    autonomy_mode=autonomy_mode,
                    active_work_item_count=len(active_work_items),
                    active_schedule_count=len(active_schedules),
                    reviewable_signal_count=reviewable_signal_count,
                ),
                [],
                False,
            )

        if autonomy_mode is ContinuousAutonomyMode.CONTINUOUS:
            return (
                ContinuousOpsStatus.IDLE,
                "Continuous autonomy is enabled, and the campaign is waiting for the next bounded trigger.",
                [],
                False,
            )
        return (
            ContinuousOpsStatus.IDLE,
            "Campaign is in bounded mode and waiting for operator or schedule triggers.",
            [],
            False,
        )

    def _resolve_autonomy_mode(
        self,
        campaign_intent_data: dict[str, object],
    ) -> ContinuousAutonomyMode:
        autonomy_posture = campaign_intent_data.get(AUTONOMY_POSTURE_KEY, {})
        if not isinstance(autonomy_posture, dict):
            return ContinuousAutonomyMode.CONTINUOUS
        bounded_mode = str(autonomy_posture.get(BOUNDED_MODE_KEY, "")).strip().lower()
        if bounded_mode == "bounded":
            return ContinuousAutonomyMode.BOUNDED
        if bounded_mode == "continuous":
            return ContinuousAutonomyMode.CONTINUOUS
        return ContinuousAutonomyMode.CONTINUOUS

    def _highest_signal_severity(self, unresolved_signals) -> str:
        if not unresolved_signals:
            return ""
        highest = max(
            unresolved_signals,
            key=lambda signal: _SEVERITY_ORDER.get(signal.severity, 0),
        )
        return highest.severity.value

    def _workspace_refresh_needed(
        self,
        previous_state: ContinuousOpsState | None,
        current_state: ContinuousOpsState,
    ) -> bool:
        if previous_state is None:
            return True
        return (
            previous_state.loop_status is not current_state.loop_status
            or previous_state.status_summary != current_state.status_summary
            or previous_state.operator_attention_required != current_state.operator_attention_required
            or previous_state.active_schedule_ids != current_state.active_schedule_ids
            or previous_state.active_work_types != current_state.active_work_types
            or previous_state.reviewable_signal_count != current_state.reviewable_signal_count
            or previous_state.commercial_summary != current_state.commercial_summary
            or previous_state.promising_active_thread_count != current_state.promising_active_thread_count
            or previous_state.conversion_ready_thread_count != current_state.conversion_ready_thread_count
            or previous_state.stale_promising_thread_count != current_state.stale_promising_thread_count
        )

    def _is_auto_paused_schedule(self, schedule: ScheduleRecord) -> bool:
        if schedule.status is not ScheduleStatus.PAUSED:
            return False
        limit = schedule.pause_after_consecutive_misses
        if limit is None or limit <= 0:
            return False
        return schedule.consecutive_miss_count >= limit

    def _build_schedule_pause_reason(self, schedule: ScheduleRecord) -> str:
        if schedule.evaluation_metric and schedule.minimum_value is not None:
            return (
                f"Paused schedule after {schedule.consecutive_miss_count} consecutive misses for "
                f"`{schedule.evaluation_metric}` below the minimum of {schedule.minimum_value}."
            )
        return f"Paused schedule after {schedule.consecutive_miss_count} consecutive failed runs."

    def _build_running_summary(
        self,
        *,
        autonomy_mode: ContinuousAutonomyMode,
        active_work_item_count: int,
        active_schedule_count: int,
        reviewable_signal_count: int,
    ) -> str:
        if active_schedule_count or active_work_item_count:
            return (
                f"{autonomy_mode.value.title()} campaign loop is active with "
                f"{active_schedule_count} schedule(s), {active_work_item_count} open work item(s), "
                f"and {reviewable_signal_count} reviewable signal(s)."
            )
        return "Campaign signals are waiting for bounded observation review."

    def _build_commercial_summary(
        self,
        conversations,
        unresolved_signals,
    ) -> dict[str, object]:
        now = datetime.now(UTC)
        stale_cutoff = now.timestamp() - (_PROMISING_THREAD_STALE_HOURS * 3600)
        hotspot_cutoff = now.timestamp() - (_COMMERCIAL_HOTSPOT_WINDOW_HOURS * 3600)

        promising_active_thread_count = 0
        objection_heavy_thread_count = 0
        conversion_ready_thread_count = 0
        stale_promising_thread_count = 0
        unresolved_high_opportunity_conversation_ids: set[str] = set()

        for signal in unresolved_signals:
            if signal.category not in {CampaignSignalCategory.OPPORTUNITY, CampaignSignalCategory.YIELD}:
                continue
            if signal.conversation_id and _SEVERITY_ORDER.get(signal.severity, 0) >= _SEVERITY_ORDER[CampaignSignalSeverity.HIGH]:
                unresolved_high_opportunity_conversation_ids.add(signal.conversation_id)

        for conversation in conversations:
            if self._is_promising_active_thread(conversation):
                promising_active_thread_count += 1
            if self._is_objection_heavy_thread(conversation):
                objection_heavy_thread_count += 1
            if self._is_conversion_ready_thread(conversation):
                conversion_ready_thread_count += 1
            if self._is_stale_promising_thread(conversation, stale_cutoff=stale_cutoff):
                stale_promising_thread_count += 1

        account_labels = self._build_hotspot_labels(
            unresolved_signals,
            field_name="account_id",
            cutoff_timestamp=hotspot_cutoff,
        )
        community_labels = self._build_hotspot_labels(
            unresolved_signals,
            field_name="community_id",
            cutoff_timestamp=hotspot_cutoff,
        )

        summary_parts = [
            self._count_summary("promising active", promising_active_thread_count),
            self._count_summary("objection-heavy", objection_heavy_thread_count),
            self._count_summary("conversion-ready", conversion_ready_thread_count),
            self._count_summary("unresolved high-opportunity", len(unresolved_high_opportunity_conversation_ids)),
            self._count_summary("stale promising", stale_promising_thread_count),
        ]
        summary_parts = [part for part in summary_parts if part]
        if summary_parts:
            summary = ", ".join(summary_parts[:4])
            if len(summary_parts) > 4:
                summary = summary + f", and {summary_parts[4]}"
            summary = summary[0].upper() + summary[1:] + " thread(s)."
        else:
            summary = "No meaningful commercial traction has been persisted yet."

        return {
            "summary": summary,
            "promising_active_thread_count": promising_active_thread_count,
            "objection_heavy_thread_count": objection_heavy_thread_count,
            "conversion_ready_thread_count": conversion_ready_thread_count,
            "unresolved_high_opportunity_thread_count": len(unresolved_high_opportunity_conversation_ids),
            "stale_promising_thread_count": stale_promising_thread_count,
            "high_yield_account_labels": account_labels,
            "high_yield_community_labels": community_labels,
        }

    def _build_hotspot_labels(
        self,
        signals,
        *,
        field_name: str,
        cutoff_timestamp: float,
    ) -> list[str]:
        score_by_label: dict[str, int] = defaultdict(int)
        yield_by_label: dict[str, bool] = defaultdict(bool)
        latest_by_label: dict[str, datetime] = {}

        for signal in signals:
            if signal.category not in {CampaignSignalCategory.OPPORTUNITY, CampaignSignalCategory.YIELD}:
                continue
            if signal.last_happened_at.timestamp() < cutoff_timestamp:
                continue
            label = getattr(signal, field_name, "").strip()
            if not label:
                continue
            score_by_label[label] += 2 if signal.category is CampaignSignalCategory.YIELD else 1
            yield_by_label[label] = yield_by_label[label] or signal.category is CampaignSignalCategory.YIELD
            latest_by_label[label] = max(latest_by_label.get(label, signal.last_happened_at), signal.last_happened_at)

        ranked = [
            (label, score_by_label[label], latest_by_label[label])
            for label in score_by_label
            if score_by_label[label] >= 2 or yield_by_label[label]
        ]
        ranked.sort(key=lambda item: (item[1], item[2]), reverse=True)
        return [f"{label} ({score} traction)" for label, score, _ in ranked[:3]]

    def _is_promising_active_thread(self, conversation) -> bool:
        if conversation.status is not ExternalConversationStatus.ACTIVE:
            return False
        return self._conversation_has_promising_signal(conversation)

    def _is_objection_heavy_thread(self, conversation) -> bool:
        if conversation.status in {ExternalConversationStatus.CLOSED, ExternalConversationStatus.BLOCKED}:
            return False
        return bool(
            conversation.belief_state.known_objections
            or conversation.qualification_status == "objection_or_unclear"
            or conversation.triage_state.objection_present
        )

    def _is_conversion_ready_thread(self, conversation) -> bool:
        if conversation.status in {ExternalConversationStatus.CLOSED, ExternalConversationStatus.BLOCKED}:
            return False
        return bool(
            conversation.handoff_status in {"ready", "clarification_required", "blocked"}
            or conversation.qualification_status == "conversion_ready"
            or conversation.belief_state.commercial_stage in {
                "handoff_ready",
                "conversion_target_clarification_required",
            }
        )

    def _is_stale_promising_thread(self, conversation, *, stale_cutoff: float) -> bool:
        if conversation.status in {ExternalConversationStatus.CLOSED, ExternalConversationStatus.BLOCKED}:
            return False
        if conversation.handoff_status == "delivered":
            return False
        if not self._conversation_has_promising_signal(conversation):
            return False
        return self._latest_commercial_activity_timestamp(conversation) <= stale_cutoff

    def _conversation_has_promising_signal(self, conversation) -> bool:
        return bool(
            conversation.qualification_status in {"potential_fit", "conversion_ready"}
            or conversation.handoff_status in {"ready", "clarification_required"}
            or conversation.belief_state.commercial_stage in {
                "potential_fit",
                "conversion_ready",
                "handoff_ready",
                "conversion_target_clarification_required",
            }
            or conversation.belief_state.known_fit_signals
            or (
                conversation.triage_state.promoted_to_deep_review
                and conversation.triage_state.interest_level.value in {"medium", "high"}
            )
        )

    def _latest_commercial_activity_timestamp(self, conversation) -> float:
        timestamps = [
            conversation.last_inbound_at,
            conversation.last_outbound_at,
            conversation.belief_state.last_belief_update_at,
            conversation.last_handoff_attempted_at,
            conversation.last_handoff_completed_at,
            conversation.created_at,
        ]
        resolved = [timestamp.timestamp() for timestamp in timestamps if timestamp is not None]
        if not resolved:
            return 0.0
        return max(resolved)

    def _count_summary(self, label: str, count: int) -> str:
        if count < 1:
            return ""
        return f"{count} {label}"


def _unique(values) -> list[str]:
    unique_values: list[str] = []
    for value in values:
        normalized = str(value).strip()
        if normalized and normalized not in unique_values:
            unique_values.append(normalized)
    return unique_values
