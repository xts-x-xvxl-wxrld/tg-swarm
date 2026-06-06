"""Durable campaign-level continuous-operations state."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class ContinuousAutonomyMode(StrEnum):
    """Effective campaign autonomy posture for the current runtime."""

    BOUNDED = "bounded"
    CONTINUOUS = "continuous"


class ContinuousOpsStatus(StrEnum):
    """High-level operating status for one campaign loop."""

    IDLE = "idle"
    RUNNING = "running"
    BLOCKED = "blocked"
    PAUSED = "paused"


@dataclass(slots=True)
class ContinuousOpsState:
    """Compact persisted summary of how one campaign should keep operating."""

    campaign_id: str
    autonomy_mode: ContinuousAutonomyMode = ContinuousAutonomyMode.CONTINUOUS
    loop_status: ContinuousOpsStatus = ContinuousOpsStatus.IDLE
    status_summary: str = ""
    blocked_reasons: list[str] = field(default_factory=list)
    active_work_types: list[str] = field(default_factory=list)
    review_pending_work_types: list[str] = field(default_factory=list)
    active_schedule_ids: list[str] = field(default_factory=list)
    paused_schedule_ids: list[str] = field(default_factory=list)
    next_scheduled_run_at: datetime | None = None
    unresolved_signal_count: int = 0
    reviewable_signal_count: int = 0
    highest_signal_severity: str = ""
    commercial_summary: str = ""
    promising_active_thread_count: int = 0
    objection_heavy_thread_count: int = 0
    conversion_ready_thread_count: int = 0
    unresolved_high_opportunity_thread_count: int = 0
    stale_promising_thread_count: int = 0
    high_yield_account_labels: list[str] = field(default_factory=list)
    high_yield_community_labels: list[str] = field(default_factory=list)
    latest_observation_summary: str = ""
    latest_observation_attention: str = ""
    latest_observation_next_step: str = ""
    operator_attention_required: bool = False
    last_refreshed_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Serialize the state for campaign-local JSON persistence."""
        return {
            "campaign_id": self.campaign_id,
            "autonomy_mode": self.autonomy_mode.value,
            "loop_status": self.loop_status.value,
            "status_summary": self.status_summary,
            "blocked_reasons": list(self.blocked_reasons),
            "active_work_types": list(self.active_work_types),
            "review_pending_work_types": list(self.review_pending_work_types),
            "active_schedule_ids": list(self.active_schedule_ids),
            "paused_schedule_ids": list(self.paused_schedule_ids),
            "next_scheduled_run_at": (
                self.next_scheduled_run_at.isoformat()
                if self.next_scheduled_run_at is not None
                else None
            ),
            "unresolved_signal_count": self.unresolved_signal_count,
            "reviewable_signal_count": self.reviewable_signal_count,
            "highest_signal_severity": self.highest_signal_severity,
            "commercial_summary": self.commercial_summary,
            "promising_active_thread_count": self.promising_active_thread_count,
            "objection_heavy_thread_count": self.objection_heavy_thread_count,
            "conversion_ready_thread_count": self.conversion_ready_thread_count,
            "unresolved_high_opportunity_thread_count": self.unresolved_high_opportunity_thread_count,
            "stale_promising_thread_count": self.stale_promising_thread_count,
            "high_yield_account_labels": list(self.high_yield_account_labels),
            "high_yield_community_labels": list(self.high_yield_community_labels),
            "latest_observation_summary": self.latest_observation_summary,
            "latest_observation_attention": self.latest_observation_attention,
            "latest_observation_next_step": self.latest_observation_next_step,
            "operator_attention_required": self.operator_attention_required,
            "last_refreshed_at": self.last_refreshed_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "ContinuousOpsState":
        """Hydrate a stored state from JSON."""
        payload = payload or {}
        raw_autonomy_mode = str(
            payload.get("autonomy_mode", ContinuousAutonomyMode.CONTINUOUS.value)
        ).strip()
        raw_loop_status = str(
            payload.get("loop_status", ContinuousOpsStatus.IDLE.value)
        ).strip()
        blocked_reasons = payload.get("blocked_reasons", [])
        active_work_types = payload.get("active_work_types", [])
        review_pending_work_types = payload.get("review_pending_work_types", [])
        active_schedule_ids = payload.get("active_schedule_ids", [])
        paused_schedule_ids = payload.get("paused_schedule_ids", [])
        high_yield_account_labels = payload.get("high_yield_account_labels", [])
        high_yield_community_labels = payload.get("high_yield_community_labels", [])
        return cls(
            campaign_id=str(payload.get("campaign_id", "")).strip(),
            autonomy_mode=ContinuousAutonomyMode._value2member_map_.get(
                raw_autonomy_mode,
                ContinuousAutonomyMode.CONTINUOUS,
            ),
            loop_status=ContinuousOpsStatus._value2member_map_.get(
                raw_loop_status,
                ContinuousOpsStatus.IDLE,
            ),
            status_summary=str(payload.get("status_summary", "")).strip(),
            blocked_reasons=[
                str(value).strip()
                for value in blocked_reasons
                if isinstance(blocked_reasons, list) and str(value).strip()
            ],
            active_work_types=[
                str(value).strip()
                for value in active_work_types
                if isinstance(active_work_types, list) and str(value).strip()
            ],
            review_pending_work_types=[
                str(value).strip()
                for value in review_pending_work_types
                if isinstance(review_pending_work_types, list) and str(value).strip()
            ],
            active_schedule_ids=[
                str(value).strip()
                for value in active_schedule_ids
                if isinstance(active_schedule_ids, list) and str(value).strip()
            ],
            paused_schedule_ids=[
                str(value).strip()
                for value in paused_schedule_ids
                if isinstance(paused_schedule_ids, list) and str(value).strip()
            ],
            next_scheduled_run_at=_parse_datetime(payload.get("next_scheduled_run_at")),
            unresolved_signal_count=max(int(payload.get("unresolved_signal_count", 0) or 0), 0),
            reviewable_signal_count=max(int(payload.get("reviewable_signal_count", 0) or 0), 0),
            highest_signal_severity=str(payload.get("highest_signal_severity", "")).strip(),
            commercial_summary=str(payload.get("commercial_summary", "")).strip(),
            promising_active_thread_count=max(int(payload.get("promising_active_thread_count", 0) or 0), 0),
            objection_heavy_thread_count=max(int(payload.get("objection_heavy_thread_count", 0) or 0), 0),
            conversion_ready_thread_count=max(int(payload.get("conversion_ready_thread_count", 0) or 0), 0),
            unresolved_high_opportunity_thread_count=max(
                int(payload.get("unresolved_high_opportunity_thread_count", 0) or 0),
                0,
            ),
            stale_promising_thread_count=max(int(payload.get("stale_promising_thread_count", 0) or 0), 0),
            high_yield_account_labels=[
                str(value).strip()
                for value in high_yield_account_labels
                if isinstance(high_yield_account_labels, list) and str(value).strip()
            ],
            high_yield_community_labels=[
                str(value).strip()
                for value in high_yield_community_labels
                if isinstance(high_yield_community_labels, list) and str(value).strip()
            ],
            latest_observation_summary=str(payload.get("latest_observation_summary", "")).strip(),
            latest_observation_attention=str(payload.get("latest_observation_attention", "")).strip(),
            latest_observation_next_step=str(payload.get("latest_observation_next_step", "")).strip(),
            operator_attention_required=bool(payload.get("operator_attention_required", False)),
            last_refreshed_at=_parse_datetime(payload.get("last_refreshed_at")) or datetime.now(UTC),
        )


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
