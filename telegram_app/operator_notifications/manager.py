"""Campaign-owned operator notification and recovery helpers."""

from __future__ import annotations

from pathlib import Path
from threading import RLock
from uuid import uuid4

from telegram_app.campaign_signals import CampaignSignalManager, CampaignSignalRecord, CampaignSignalSeverity
from telegram_app.campaigns import CampaignManager
from telegram_app.continuous_ops.models import ContinuousOpsState, ContinuousOpsStatus
from telegram_app.continuous_ops.storage import load_continuous_ops_state_for_workspace
from telegram_app.models import ScheduleRecord, ScheduleStatus
from telegram_app.scheduling import ScheduleManager

from .models import (
    OperatorInterventionDraft,
    OperatorInterventionKind,
    OperatorInterventionRecord,
    OperatorInterventionSeverity,
    OperatorInterventionStatus,
    utc_now,
)
from .storage import load_interventions_for_workspace, write_interventions_for_workspace

_SEVERITY_ORDER = {
    OperatorInterventionSeverity.LOW: 1,
    OperatorInterventionSeverity.MEDIUM: 2,
    OperatorInterventionSeverity.HIGH: 3,
    OperatorInterventionSeverity.CRITICAL: 4,
}


class OperatorInterventionManager:
    """Own compact operator-facing intervention state for one campaign."""

    def __init__(
        self,
        campaign_manager: CampaignManager,
        schedule_manager: ScheduleManager,
        signal_manager: CampaignSignalManager,
    ) -> None:
        self._campaign_manager = campaign_manager
        self._schedule_manager = schedule_manager
        self._signal_manager = signal_manager
        self._lock = RLock()

    def refresh_for_campaign(
        self,
        campaign_id: str,
        *,
        continuous_ops_state: ContinuousOpsState | None = None,
    ) -> list[OperatorInterventionRecord]:
        """Reconcile derived interventions with the current campaign runtime state."""
        campaign = self._campaign_manager.get(campaign_id)
        if campaign is None:
            return []

        workspace_path = Path(campaign.workspace_path)
        state = continuous_ops_state or load_continuous_ops_state_for_workspace(workspace_path)
        schedules = self._schedule_manager.list_for_campaign(campaign_id)
        unresolved_signals = self._signal_manager.list_unresolved(campaign_id, limit=8)
        drafts = self._build_drafts(
            campaign_id,
            continuous_ops_state=state,
            schedules=schedules,
            unresolved_signals=unresolved_signals,
        )
        now = utc_now()
        with self._lock:
            existing_records = load_interventions_for_workspace(workspace_path)
            records_by_key = {
                record.dedupe_key: record
                for record in existing_records
            }
            active_keys = {draft.dedupe_key for draft in drafts}
            updated_records: list[OperatorInterventionRecord] = []

            for draft in drafts:
                record = records_by_key.get(draft.dedupe_key)
                if record is None:
                    updated_records.append(
                        OperatorInterventionRecord(
                            intervention_id=str(uuid4()),
                            campaign_id=campaign_id,
                            kind=draft.kind,
                            dedupe_key=draft.dedupe_key,
                            title=draft.title,
                            body=draft.body,
                            recovery_hint=draft.recovery_hint,
                            severity=draft.severity,
                            related_refs=list(draft.related_refs),
                            first_detected_at=now,
                            last_detected_at=now,
                            last_changed_at=now,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    continue

                record.last_detected_at = now
                changed = self._apply_draft(record, draft, now=now)
                if record.status is OperatorInterventionStatus.RESOLVED:
                    record.status = OperatorInterventionStatus.OPEN
                    record.resolved_at = None
                    record.acknowledged_at = None
                    changed = True
                if changed:
                    record.last_changed_at = now
                    record.touch()
                updated_records.append(record)

            for record in existing_records:
                if record.dedupe_key in active_keys:
                    continue
                if record.status is not OperatorInterventionStatus.RESOLVED:
                    record.status = OperatorInterventionStatus.RESOLVED
                    record.resolved_at = now
                    record.touch()
                updated_records.append(record)

            ordered = sorted(updated_records, key=self._sort_key, reverse=True)
            write_interventions_for_workspace(workspace_path, ordered)
            return ordered

    def list_for_campaign(self, campaign_id: str) -> list[OperatorInterventionRecord]:
        """Return all stored interventions for one campaign."""
        campaign = self._campaign_manager.get(campaign_id)
        if campaign is None:
            return []
        return load_interventions_for_workspace(campaign.workspace_path)

    def list_open_for_campaign(
        self,
        campaign_id: str,
        *,
        include_acknowledged: bool = False,
    ) -> list[OperatorInterventionRecord]:
        """Return unresolved interventions ordered by urgency."""
        records = self.list_for_campaign(campaign_id)
        unresolved = [
            record
            for record in records
            if record.status is not OperatorInterventionStatus.RESOLVED
        ]
        if not include_acknowledged:
            unresolved = [
                record
                for record in unresolved
                if record.status is OperatorInterventionStatus.OPEN
            ]
        return sorted(unresolved, key=self._sort_key, reverse=True)

    def list_deliverable_for_campaign(self, campaign_id: str) -> list[OperatorInterventionRecord]:
        """Return open interventions that have not yet been delivered in their current form."""
        return [
            record
            for record in self.list_open_for_campaign(campaign_id)
            if record.last_delivered_at is None or record.last_changed_at > record.last_delivered_at
        ]

    def acknowledge_all_for_campaign(self, campaign_id: str) -> int:
        """Quiet repeated delivery for every unresolved open intervention."""
        campaign = self._campaign_manager.get(campaign_id)
        if campaign is None:
            return 0
        now = utc_now()
        changed = 0
        with self._lock:
            records = load_interventions_for_workspace(campaign.workspace_path)
            for record in records:
                if record.status is not OperatorInterventionStatus.OPEN:
                    continue
                record.status = OperatorInterventionStatus.ACKNOWLEDGED
                record.acknowledged_at = now
                record.touch()
                changed += 1
            if changed:
                write_interventions_for_workspace(campaign.workspace_path, records)
        return changed

    def mark_delivered(self, campaign_id: str, intervention_ids: list[str]) -> None:
        """Persist delivery state after operator-facing alert copy is sent."""
        if not intervention_ids:
            return
        campaign = self._campaign_manager.get(campaign_id)
        if campaign is None:
            return
        now = utc_now()
        with self._lock:
            records = load_interventions_for_workspace(campaign.workspace_path)
            changed = False
            wanted = set(intervention_ids)
            for record in records:
                if record.intervention_id not in wanted:
                    continue
                record.last_delivered_at = now
                record.delivery_count += 1
                record.touch()
                changed = True
            if changed:
                write_interventions_for_workspace(campaign.workspace_path, records)

    def build_alert_message(
        self,
        campaign_id: str,
        interventions: list[OperatorInterventionRecord],
        *,
        include_footer: bool = True,
    ) -> str:
        """Return compact Telegram-ready copy for one or more interventions."""
        if not interventions:
            return "No open operator interventions are currently recorded for this campaign."

        lines = [f"Operator intervention needed for campaign `{campaign_id}`:"]
        for intervention in interventions:
            lines.append(f"- {intervention.title}: {intervention.body}")
            if intervention.recovery_hint:
                lines.append(f"  Recovery: {intervention.recovery_hint}")
        if include_footer:
            lines.append("")
            lines.append("Reply `ack alerts` to quiet repeats until something changes, or `show alerts` to list current interventions.")
        return "\n".join(lines)

    def _build_drafts(
        self,
        campaign_id: str,
        *,
        continuous_ops_state: ContinuousOpsState | None,
        schedules: list[ScheduleRecord],
        unresolved_signals: list[CampaignSignalRecord],
    ) -> list[OperatorInterventionDraft]:
        if continuous_ops_state is None:
            return []

        drafts: list[OperatorInterventionDraft] = []
        if continuous_ops_state.operator_attention_required:
            drafts.append(
                OperatorInterventionDraft(
                    campaign_id=campaign_id,
                    kind=OperatorInterventionKind.OPERATOR_REVIEW_REQUIRED,
                    dedupe_key="operator-review-required",
                    title="Operator review required",
                    body=(
                        continuous_ops_state.status_summary
                        or "Autonomous work is blocked until the operator reviews the latest campaign issue."
                    ),
                    recovery_hint=(
                        "Review the latest blocked work or observation outcome, then revise the plan, pause the campaign, "
                        "or resume the affected loop once you are comfortable."
                    ),
                    severity=self._attention_severity(continuous_ops_state),
                )
            )

        for schedule in schedules:
            if not self._is_auto_paused_schedule(schedule):
                continue
            drafts.append(
                OperatorInterventionDraft(
                    campaign_id=campaign_id,
                    kind=OperatorInterventionKind.RECURRING_SCHEDULE_PAUSED,
                    dedupe_key=f"auto-paused-schedule:{schedule.schedule_id}",
                    title="Recurring schedule paused itself",
                    body=self._build_schedule_pause_reason(schedule),
                    recovery_hint=(
                        f"Inspect the latest `{schedule.work_type}` misses and say `resume the {schedule.work_type} schedule` "
                        "when you want the loop to continue."
                    ),
                    severity=OperatorInterventionSeverity.MEDIUM,
                    related_refs=[f"schedule:{schedule.schedule_id}"],
                )
            )

        if self._needs_capacity_intervention(unresolved_signals):
            top_signal = self._top_signal(unresolved_signals)
            if top_signal is not None:
                drafts.append(
                    OperatorInterventionDraft(
                        campaign_id=campaign_id,
                        kind=OperatorInterventionKind.EXECUTION_CAPACITY_RISK,
                        dedupe_key="execution-capacity-risk",
                        title="Execution capacity needs review",
                        body=top_signal.summary or "Managed account health or live execution pressure needs operator review.",
                        recovery_hint=(
                            "Inspect the affected managed accounts or community paths, then rest, replace, or pause them "
                            "before the campaign pushes harder."
                        ),
                        severity=self._signal_to_intervention_severity(top_signal.severity),
                        related_refs=[f"signal:{top_signal.signal_id}"],
                    )
                )

        if self._needs_loop_blocked_intervention(continuous_ops_state, drafts):
            drafts.append(
                OperatorInterventionDraft(
                    campaign_id=campaign_id,
                    kind=OperatorInterventionKind.CAMPAIGN_LOOP_BLOCKED,
                    dedupe_key="campaign-loop-blocked",
                    title="Campaign loop is blocked",
                    body=continuous_ops_state.status_summary or "The campaign no longer has a bounded next step.",
                    recovery_hint=self._loop_blocked_recovery_hint(continuous_ops_state),
                    severity=OperatorInterventionSeverity.HIGH,
                )
            )
        return drafts

    def _apply_draft(
        self,
        record: OperatorInterventionRecord,
        draft: OperatorInterventionDraft,
        *,
        now,
    ) -> bool:
        changed = False
        if record.kind is not draft.kind:
            record.kind = draft.kind
            changed = True
        if record.title != draft.title:
            record.title = draft.title
            changed = True
        if record.body != draft.body:
            record.body = draft.body
            changed = True
        if record.recovery_hint != draft.recovery_hint:
            record.recovery_hint = draft.recovery_hint
            changed = True
        if record.severity is not draft.severity:
            record.severity = draft.severity
            changed = True
        if record.related_refs != draft.related_refs:
            record.related_refs = list(draft.related_refs)
            changed = True
        if changed and record.status is OperatorInterventionStatus.ACKNOWLEDGED:
            record.status = OperatorInterventionStatus.OPEN
            record.acknowledged_at = None
            record.resolved_at = None
        return changed

    def _needs_loop_blocked_intervention(
        self,
        state: ContinuousOpsState,
        existing_drafts: list[OperatorInterventionDraft],
    ) -> bool:
        if state.loop_status is not ContinuousOpsStatus.BLOCKED:
            return False
        if state.operator_attention_required:
            return False
        if any(
            draft.kind is OperatorInterventionKind.RECURRING_SCHEDULE_PAUSED
            for draft in existing_drafts
        ):
            return False
        return True

    def _loop_blocked_recovery_hint(self, state: ContinuousOpsState) -> str:
        if any("no recurring schedules or open work items" in reason.lower() for reason in state.blocked_reasons):
            return "Create a recurring schedule or open a new work item so the campaign has a bounded next move again."
        return "Inspect the blocked reason, then resume the paused loop or adjust campaign guidance before continuing."

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
                f"Recurring `{schedule.work_type}` paused itself after {schedule.consecutive_miss_count} misses for "
                f"`{schedule.evaluation_metric}` below {schedule.minimum_value}."
            )
        return (
            f"Recurring `{schedule.work_type}` paused itself after {schedule.consecutive_miss_count} failed runs."
        )

    def _needs_capacity_intervention(self, unresolved_signals: list[CampaignSignalRecord]) -> bool:
        for signal in unresolved_signals:
            if signal.signal_type == "account_flagged_or_banned":
                return True
            if signal.severity in {CampaignSignalSeverity.HIGH, CampaignSignalSeverity.CRITICAL} and signal.review_eligible:
                return True
        return False

    def _top_signal(self, unresolved_signals: list[CampaignSignalRecord]) -> CampaignSignalRecord | None:
        if not unresolved_signals:
            return None
        return max(
            unresolved_signals,
            key=lambda signal: (
                self._signal_priority(signal),
                signal.last_happened_at,
                signal.updated_at,
            ),
        )

    def _signal_priority(self, signal: CampaignSignalRecord) -> int:
        severity = self._signal_to_intervention_severity(signal.severity)
        return _SEVERITY_ORDER[severity]

    def _signal_to_intervention_severity(
        self,
        signal_severity: CampaignSignalSeverity,
    ) -> OperatorInterventionSeverity:
        return {
            CampaignSignalSeverity.LOW: OperatorInterventionSeverity.LOW,
            CampaignSignalSeverity.MEDIUM: OperatorInterventionSeverity.MEDIUM,
            CampaignSignalSeverity.HIGH: OperatorInterventionSeverity.HIGH,
            CampaignSignalSeverity.CRITICAL: OperatorInterventionSeverity.CRITICAL,
        }[signal_severity]

    def _attention_severity(self, state: ContinuousOpsState) -> OperatorInterventionSeverity:
        if state.highest_signal_severity == CampaignSignalSeverity.CRITICAL.value:
            return OperatorInterventionSeverity.CRITICAL
        return OperatorInterventionSeverity.HIGH

    def _sort_key(self, record: OperatorInterventionRecord) -> tuple[int, object]:
        return (_SEVERITY_ORDER[record.severity], record.last_detected_at)
