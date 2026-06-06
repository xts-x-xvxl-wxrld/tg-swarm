"""Progressive warmup budgets for managed Telegram accounts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

WARMUP_RAMP_DAYS = 5
WARMUP_WINDOW_HOURS = 24


class WarmupActionClass(StrEnum):
    """Action buckets that warm up at different rates."""

    READS = "reads"
    JOINS = "joins"
    GROUP_REPLIES = "group_replies"
    DM_REPLIES = "dm_replies"
    OUTBOUND_STARTS = "outbound_starts"
    FOLLOW_UP_REPLIES = "follow_up_replies"


_WARMUP_BUDGETS: dict[WarmupActionClass, tuple[int, ...]] = {
    WarmupActionClass.READS: (250, 400, 650, 900, 1200),
    WarmupActionClass.JOINS: (2, 3, 5, 7, 10),
    WarmupActionClass.GROUP_REPLIES: (4, 8, 12, 18, 24),
    WarmupActionClass.DM_REPLIES: (6, 12, 18, 24, 32),
    WarmupActionClass.OUTBOUND_STARTS: (1, 1, 2, 3, 4),
    WarmupActionClass.FOLLOW_UP_REPLIES: (4, 8, 12, 18, 24),
}

_WARMUP_STAGE_LABELS = (
    "day_1",
    "day_2",
    "day_3",
    "day_4",
    "day_5_plus",
)


@dataclass(slots=True)
class WarmupBudgetStatus:
    """Normalized budget status for one action bucket."""

    action_class: WarmupActionClass
    day_index: int
    stage_label: str
    budget_limit: int
    used_count: int
    remaining_count: int
    window_started_at: datetime
    window_expires_at: datetime

    @property
    def warmup_active(self) -> bool:
        """Return whether the account is still inside the initial ramp window."""
        return self.day_index < WARMUP_RAMP_DAYS - 1

    def to_dict(self) -> dict[str, object]:
        """Serialize one prompt-safe budget status."""
        return {
            "action_class": self.action_class.value,
            "day_index": self.day_index,
            "stage_label": self.stage_label,
            "budget_limit": self.budget_limit,
            "used_count": self.used_count,
            "remaining_count": self.remaining_count,
            "window_started_at": self.window_started_at.isoformat(),
            "window_expires_at": self.window_expires_at.isoformat(),
            "warmup_active": self.warmup_active,
        }


def utc_now() -> datetime:
    """Return the current UTC time."""
    return datetime.now(UTC)


def parse_datetime(value: str | None) -> datetime | None:
    """Parse one ISO-8601 timestamp when present."""
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return datetime.fromisoformat(normalized)


def ensure_onboarded_at(onboarded_at: str, *, now: datetime | None = None) -> str:
    """Normalize an onboarded-at timestamp, defaulting to now when missing."""
    resolved_now = now or utc_now()
    parsed = parse_datetime(onboarded_at)
    if parsed is not None:
        return parsed.astimezone(UTC).isoformat()
    return resolved_now.isoformat()


def warmup_day_index(onboarded_at: str, *, now: datetime | None = None) -> int:
    """Return the zero-based warmup day for one account."""
    resolved_now = now or utc_now()
    parsed = parse_datetime(onboarded_at) or resolved_now
    age = resolved_now - parsed.astimezone(UTC)
    if age.total_seconds() <= 0:
        return 0
    return max(int(age.total_seconds() // (24 * 3600)), 0)


def stage_label_for_day(day_index: int) -> str:
    """Return the compact warmup stage label for a given day index."""
    bounded_day = max(min(day_index, len(_WARMUP_STAGE_LABELS) - 1), 0)
    return _WARMUP_STAGE_LABELS[bounded_day]


def budget_limit_for(action_class: WarmupActionClass, *, day_index: int) -> int:
    """Return the budget limit for one action class on a given day."""
    limits = _WARMUP_BUDGETS[action_class]
    bounded_day = max(min(day_index, len(limits) - 1), 0)
    return limits[bounded_day]


def build_budget_status(
    metadata: dict[str, Any] | None,
    *,
    onboarded_at: str,
    action_class: WarmupActionClass,
    now: datetime | None = None,
) -> WarmupBudgetStatus:
    """Return the current budget status for one account action class."""
    resolved_now = (now or utc_now()).astimezone(UTC)
    metadata = dict(metadata or {})
    activity = _load_activity_bucket(metadata, action_class)
    window_started_at = parse_datetime(str(activity.get("window_started_at", "")).strip())
    used_count = int(activity.get("count", 0) or 0)
    if window_started_at is None or resolved_now - window_started_at >= timedelta(hours=WARMUP_WINDOW_HOURS):
        window_started_at = resolved_now
        used_count = 0
    day_index = warmup_day_index(onboarded_at, now=resolved_now)
    budget_limit = budget_limit_for(action_class, day_index=day_index)
    remaining_count = max(budget_limit - used_count, 0)
    return WarmupBudgetStatus(
        action_class=action_class,
        day_index=day_index,
        stage_label=stage_label_for_day(day_index),
        budget_limit=budget_limit,
        used_count=used_count,
        remaining_count=remaining_count,
        window_started_at=window_started_at,
        window_expires_at=window_started_at + timedelta(hours=WARMUP_WINDOW_HOURS),
    )


def increment_budget_usage(
    metadata: dict[str, Any] | None,
    *,
    onboarded_at: str,
    action_class: WarmupActionClass,
    now: datetime | None = None,
    amount: int = 1,
) -> dict[str, Any]:
    """Persist one successful action against the warmup budget ledger."""
    resolved_now = (now or utc_now()).astimezone(UTC)
    metadata = dict(metadata or {})
    status = build_budget_status(
        metadata,
        onboarded_at=onboarded_at,
        action_class=action_class,
        now=resolved_now,
    )
    activity = _ensure_activity_root(metadata)
    activity[action_class.value] = {
        "window_started_at": status.window_started_at.isoformat(),
        "count": status.used_count + max(amount, 0),
        "last_recorded_at": resolved_now.isoformat(),
    }
    return metadata


def summarize_warmup(
    metadata: dict[str, Any] | None,
    *,
    onboarded_at: str,
    now: datetime | None = None,
) -> dict[str, object]:
    """Return a prompt-safe warmup summary for one account."""
    resolved_now = now or utc_now()
    day_index = warmup_day_index(onboarded_at, now=resolved_now)
    budgets = {
        action_class.value: build_budget_status(
            metadata,
            onboarded_at=onboarded_at,
            action_class=action_class,
            now=resolved_now,
        ).to_dict()
        for action_class in WarmupActionClass
    }
    return {
        "warmup_day": day_index + 1,
        "warmup_stage": stage_label_for_day(day_index),
        "warmup_active": day_index < WARMUP_RAMP_DAYS - 1,
        "action_budgets": budgets,
    }


def _ensure_activity_root(metadata: dict[str, Any]) -> dict[str, Any]:
    activity = metadata.get("warmup_activity", {})
    if not isinstance(activity, dict):
        activity = {}
        metadata["warmup_activity"] = activity
    return activity


def _load_activity_bucket(metadata: dict[str, Any], action_class: WarmupActionClass) -> dict[str, Any]:
    activity = metadata.get("warmup_activity", {})
    if not isinstance(activity, dict):
        return {}
    bucket = activity.get(action_class.value, {})
    if not isinstance(bucket, dict):
        return {}
    return bucket
