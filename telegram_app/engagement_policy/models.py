"""Campaign-owned engagement timing and suppression policy contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class ReplyLatencyTier(StrEnum):
    """Supported reply-speed tiers for managed-account conversations."""

    NEAR_IMMEDIATE = "near_immediate"
    SHORT_DELAY = "short_delay"
    LONG_DELAY = "long_delay"
    NO_REPLY = "no_reply"


class ReplyTimingDecisionType(StrEnum):
    """Normalized queue-time decision for one drafted reply."""

    SEND_NOW = "send_now"
    DELAY = "delay"
    SUPPRESS = "suppress"


@dataclass(slots=True)
class ReplyLatencyWindow:
    """Bounded randomized delay range for one latency tier."""

    minimum_seconds: int
    maximum_seconds: int

    def __post_init__(self) -> None:
        self.minimum_seconds = max(int(self.minimum_seconds), 0)
        self.maximum_seconds = max(int(self.maximum_seconds), self.minimum_seconds)

    def to_dict(self) -> dict[str, int]:
        """Serialize the latency window for campaign storage."""
        return {
            "minimum_seconds": self.minimum_seconds,
            "maximum_seconds": self.maximum_seconds,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None, *, default: "ReplyLatencyWindow") -> "ReplyLatencyWindow":
        """Hydrate one latency window with a safe fallback."""
        if not isinstance(payload, dict):
            return cls(default.minimum_seconds, default.maximum_seconds)
        return cls(
            minimum_seconds=int(payload.get("minimum_seconds", default.minimum_seconds) or default.minimum_seconds),
            maximum_seconds=int(payload.get("maximum_seconds", default.maximum_seconds) or default.maximum_seconds),
        )


@dataclass(slots=True)
class QuietHoursPolicy:
    """Timezone-aware quiet-hours configuration stored per campaign."""

    timezone_name: str = "Europe/Budapest"
    start_hour: int = 0
    start_minute: int = 0
    end_hour: int = 8
    end_minute: int = 0
    wakeup_min_delay_seconds: int = 5 * 60
    wakeup_max_delay_seconds: int = 30 * 60

    def __post_init__(self) -> None:
        self.timezone_name = self.timezone_name.strip() or "UTC"
        self.start_hour = _bounded_int(self.start_hour, minimum=0, maximum=23)
        self.start_minute = _bounded_int(self.start_minute, minimum=0, maximum=59)
        self.end_hour = _bounded_int(self.end_hour, minimum=0, maximum=23)
        self.end_minute = _bounded_int(self.end_minute, minimum=0, maximum=59)
        self.wakeup_min_delay_seconds = max(int(self.wakeup_min_delay_seconds), 0)
        self.wakeup_max_delay_seconds = max(
            int(self.wakeup_max_delay_seconds),
            self.wakeup_min_delay_seconds,
        )

    def profile_name(self) -> str:
        """Return a compact operator-facing profile label."""
        zone_label = self.timezone_name.replace("/", "_").lower()
        return (
            f"{zone_label}_"
            f"{self.start_hour:02d}{self.start_minute:02d}_"
            f"{self.end_hour:02d}{self.end_minute:02d}"
        )

    def to_dict(self) -> dict[str, object]:
        """Serialize the quiet-hours config for campaign storage."""
        return {
            "timezone_name": self.timezone_name,
            "start_hour": self.start_hour,
            "start_minute": self.start_minute,
            "end_hour": self.end_hour,
            "end_minute": self.end_minute,
            "wakeup_min_delay_seconds": self.wakeup_min_delay_seconds,
            "wakeup_max_delay_seconds": self.wakeup_max_delay_seconds,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "QuietHoursPolicy":
        """Hydrate quiet-hours config from campaign storage."""
        payload = payload or {}
        return cls(
            timezone_name=str(payload.get("timezone_name", "Europe/Budapest")).strip() or "UTC",
            start_hour=int(payload.get("start_hour", 0) or 0),
            start_minute=int(payload.get("start_minute", 0) or 0),
            end_hour=int(payload.get("end_hour", 8) or 8),
            end_minute=int(payload.get("end_minute", 0) or 0),
            wakeup_min_delay_seconds=int(payload.get("wakeup_min_delay_seconds", 5 * 60) or 5 * 60),
            wakeup_max_delay_seconds=int(payload.get("wakeup_max_delay_seconds", 30 * 60) or 30 * 60),
        )


@dataclass(slots=True)
class NegativeSignalPolicy:
    """Conversation-level suppression thresholds for colder live threads."""

    suppress_low_signal_chatter: bool = True
    suppress_hostile_signal: bool = True
    max_group_follow_ups_without_inbound: int = 2
    max_dm_follow_ups_without_inbound: int = 1

    def __post_init__(self) -> None:
        self.max_group_follow_ups_without_inbound = max(int(self.max_group_follow_ups_without_inbound), 0)
        self.max_dm_follow_ups_without_inbound = max(int(self.max_dm_follow_ups_without_inbound), 0)

    def to_dict(self) -> dict[str, object]:
        """Serialize the suppression settings."""
        return {
            "suppress_low_signal_chatter": self.suppress_low_signal_chatter,
            "suppress_hostile_signal": self.suppress_hostile_signal,
            "max_group_follow_ups_without_inbound": self.max_group_follow_ups_without_inbound,
            "max_dm_follow_ups_without_inbound": self.max_dm_follow_ups_without_inbound,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "NegativeSignalPolicy":
        """Hydrate suppression settings from campaign storage."""
        payload = payload or {}
        return cls(
            suppress_low_signal_chatter=bool(payload.get("suppress_low_signal_chatter", True)),
            suppress_hostile_signal=bool(payload.get("suppress_hostile_signal", True)),
            max_group_follow_ups_without_inbound=int(payload.get("max_group_follow_ups_without_inbound", 2) or 2),
            max_dm_follow_ups_without_inbound=int(payload.get("max_dm_follow_ups_without_inbound", 1) or 1),
        )


@dataclass(slots=True)
class CommunityBehaviorPolicy:
    """Campaign-owned cadence bias for one community or community type."""

    reply_latency_tier: ReplyLatencyTier | None = None
    negative_signal_tolerance: str = "normal"

    def __post_init__(self) -> None:
        self.negative_signal_tolerance = _normalized_tolerance(self.negative_signal_tolerance)

    def to_dict(self) -> dict[str, str]:
        """Serialize community behavior overrides."""
        return {
            "reply_latency_tier": self.reply_latency_tier.value if self.reply_latency_tier is not None else "",
            "negative_signal_tolerance": self.negative_signal_tolerance,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "CommunityBehaviorPolicy":
        """Hydrate one community behavior override."""
        payload = payload or {}
        raw_tier = str(payload.get("reply_latency_tier", "")).strip().lower()
        return cls(
            reply_latency_tier=ReplyLatencyTier._value2member_map_.get(raw_tier),
            negative_signal_tolerance=str(payload.get("negative_signal_tolerance", "normal")).strip() or "normal",
        )


@dataclass(slots=True)
class CampaignEngagementPolicy:
    """Reply-timing and suppression policy stored per campaign."""

    default_reply_latency_tier: ReplyLatencyTier = ReplyLatencyTier.SHORT_DELAY
    latency_windows: dict[str, ReplyLatencyWindow] = field(default_factory=dict)
    quiet_hours: QuietHoursPolicy = field(default_factory=QuietHoursPolicy)
    negative_signal_policy: NegativeSignalPolicy = field(default_factory=NegativeSignalPolicy)
    community_type_defaults: dict[str, CommunityBehaviorPolicy] = field(default_factory=dict)
    community_overrides: dict[str, CommunityBehaviorPolicy] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.latency_windows:
            self.latency_windows = _default_latency_windows()
        if not self.community_type_defaults:
            self.community_type_defaults = _default_community_type_defaults()
        self.community_type_defaults = {
            str(key).strip().lower(): value
            for key, value in self.community_type_defaults.items()
            if str(key).strip()
        }
        self.community_overrides = {
            str(key).strip(): value
            for key, value in self.community_overrides.items()
            if str(key).strip()
        }

    def latency_window_for(self, tier: ReplyLatencyTier) -> ReplyLatencyWindow:
        """Return the configured latency window for one tier."""
        return self.latency_windows.get(tier.value, _default_latency_windows()[tier.value])

    def to_dict(self) -> dict[str, object]:
        """Serialize the campaign engagement policy."""
        return {
            "default_reply_latency_tier": self.default_reply_latency_tier.value,
            "latency_windows": {
                key: value.to_dict()
                for key, value in self.latency_windows.items()
            },
            "quiet_hours": self.quiet_hours.to_dict(),
            "negative_signal_policy": self.negative_signal_policy.to_dict(),
            "community_type_defaults": {
                key: value.to_dict()
                for key, value in self.community_type_defaults.items()
            },
            "community_overrides": {
                key: value.to_dict()
                for key, value in self.community_overrides.items()
            },
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "CampaignEngagementPolicy":
        """Hydrate the campaign engagement policy from storage."""
        payload = payload or {}
        defaults = _default_latency_windows()
        raw_latency_windows = payload.get("latency_windows", {})
        latency_windows = {
            tier.value: ReplyLatencyWindow.from_dict(
                raw_latency_windows.get(tier.value) if isinstance(raw_latency_windows, dict) else None,
                default=defaults[tier.value],
            )
            for tier in ReplyLatencyTier
            if tier is not ReplyLatencyTier.NO_REPLY
        }
        community_type_defaults_payload = payload.get("community_type_defaults", {})
        community_overrides_payload = payload.get("community_overrides", {})
        return cls(
            default_reply_latency_tier=ReplyLatencyTier._value2member_map_.get(
                str(payload.get("default_reply_latency_tier", ReplyLatencyTier.SHORT_DELAY.value)).strip().lower(),
                ReplyLatencyTier.SHORT_DELAY,
            ),
            latency_windows=latency_windows,
            quiet_hours=QuietHoursPolicy.from_dict(
                payload.get("quiet_hours") if isinstance(payload.get("quiet_hours"), dict) else None
            ),
            negative_signal_policy=NegativeSignalPolicy.from_dict(
                payload.get("negative_signal_policy")
                if isinstance(payload.get("negative_signal_policy"), dict)
                else None
            ),
            community_type_defaults={
                str(key).strip().lower(): CommunityBehaviorPolicy.from_dict(value if isinstance(value, dict) else None)
                for key, value in (
                    community_type_defaults_payload.items() if isinstance(community_type_defaults_payload, dict) else []
                )
                if str(key).strip()
            },
            community_overrides={
                str(key).strip(): CommunityBehaviorPolicy.from_dict(value if isinstance(value, dict) else None)
                for key, value in (
                    community_overrides_payload.items() if isinstance(community_overrides_payload, dict) else []
                )
                if str(key).strip()
            },
        )


@dataclass(slots=True)
class CampaignEngagementMetrics:
    """Durable scaffolding for learning which reply patterns are working."""

    decision_counts: dict[str, int] = field(default_factory=dict)
    latency_tier_counts: dict[str, int] = field(default_factory=dict)
    suppression_reason_counts: dict[str, int] = field(default_factory=dict)
    execution_outcome_counts: dict[str, int] = field(default_factory=dict)
    community_counts: dict[str, dict[str, int]] = field(default_factory=dict)
    objection_counts: dict[str, dict[str, int]] = field(default_factory=dict)
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def record_decision(
        self,
        *,
        decision_type: ReplyTimingDecisionType,
        latency_tier: ReplyLatencyTier,
        suppression_reason: str = "",
        community_key: str = "",
        objection_hints: list[str] | None = None,
    ) -> None:
        """Record one timing or suppression decision for later campaign learning."""
        _increment(self.decision_counts, decision_type.value)
        _increment(self.latency_tier_counts, latency_tier.value)
        if suppression_reason.strip():
            _increment(self.suppression_reason_counts, suppression_reason.strip())
        if community_key.strip():
            _increment_nested(self.community_counts, community_key.strip(), decision_type.value)
            _increment_nested(self.community_counts, community_key.strip(), latency_tier.value)
        for objection_hint in objection_hints or []:
            normalized_hint = str(objection_hint).strip()
            if normalized_hint:
                _increment_nested(self.objection_counts, normalized_hint, decision_type.value)
        self.updated_at = datetime.now(UTC)

    def record_execution_outcome(
        self,
        *,
        outcome_code: str,
        latency_tier: ReplyLatencyTier,
        community_key: str = "",
        objection_hints: list[str] | None = None,
    ) -> None:
        """Record one live-execution outcome for future optimization."""
        normalized_outcome = outcome_code.strip() or "unknown"
        _increment(self.execution_outcome_counts, normalized_outcome)
        if community_key.strip():
            _increment_nested(self.community_counts, community_key.strip(), normalized_outcome)
        for objection_hint in objection_hints or []:
            normalized_hint = str(objection_hint).strip()
            if normalized_hint:
                _increment_nested(self.objection_counts, normalized_hint, normalized_outcome)
        _increment(self.latency_tier_counts, latency_tier.value)
        self.updated_at = datetime.now(UTC)

    def to_dict(self) -> dict[str, object]:
        """Serialize the engagement metrics."""
        return {
            "decision_counts": dict(self.decision_counts),
            "latency_tier_counts": dict(self.latency_tier_counts),
            "suppression_reason_counts": dict(self.suppression_reason_counts),
            "execution_outcome_counts": dict(self.execution_outcome_counts),
            "community_counts": {
                key: dict(value)
                for key, value in self.community_counts.items()
            },
            "objection_counts": {
                key: dict(value)
                for key, value in self.objection_counts.items()
            },
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "CampaignEngagementMetrics":
        """Hydrate engagement metrics from storage."""
        payload = payload or {}
        return cls(
            decision_counts=_int_dict(payload.get("decision_counts")),
            latency_tier_counts=_int_dict(payload.get("latency_tier_counts")),
            suppression_reason_counts=_int_dict(payload.get("suppression_reason_counts")),
            execution_outcome_counts=_int_dict(payload.get("execution_outcome_counts")),
            community_counts=_nested_int_dict(payload.get("community_counts")),
            objection_counts=_nested_int_dict(payload.get("objection_counts")),
            updated_at=_parse_datetime(payload.get("updated_at")) or datetime.now(UTC),
        )


@dataclass(slots=True)
class CampaignEngagementPolicyState:
    """Persisted campaign-owned engagement policy plus lightweight outcome metrics."""

    policy: CampaignEngagementPolicy = field(default_factory=CampaignEngagementPolicy)
    metrics: CampaignEngagementMetrics = field(default_factory=CampaignEngagementMetrics)

    def to_dict(self) -> dict[str, object]:
        """Serialize the full campaign engagement policy state."""
        return {
            "policy": self.policy.to_dict(),
            "metrics": self.metrics.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "CampaignEngagementPolicyState":
        """Hydrate the full campaign engagement policy state."""
        payload = payload or {}
        return cls(
            policy=CampaignEngagementPolicy.from_dict(
                payload.get("policy") if isinstance(payload.get("policy"), dict) else None
            ),
            metrics=CampaignEngagementMetrics.from_dict(
                payload.get("metrics") if isinstance(payload.get("metrics"), dict) else None
            ),
        )


@dataclass(slots=True)
class ReplyTimingDecision:
    """Resolved runtime reply timing decision for one drafted message."""

    decision_type: ReplyTimingDecisionType
    latency_tier: ReplyLatencyTier
    execute_at: datetime | None = None
    quiet_hours_profile: str = ""
    suppression_reason: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_metadata(self) -> dict[str, object]:
        """Serialize the queue-time decision into action payload metadata."""
        return {
            "decision_type": self.decision_type.value,
            "latency_tier": self.latency_tier.value,
            "execute_at": self.execute_at.isoformat() if self.execute_at is not None else "",
            "quiet_hours_profile": self.quiet_hours_profile,
            "suppression_reason": self.suppression_reason,
            "evidence": dict(self.evidence),
        }


def _default_latency_windows() -> dict[str, ReplyLatencyWindow]:
    return {
        ReplyLatencyTier.NEAR_IMMEDIATE.value: ReplyLatencyWindow(20, 90),
        ReplyLatencyTier.SHORT_DELAY.value: ReplyLatencyWindow(2 * 60, 10 * 60),
        ReplyLatencyTier.LONG_DELAY.value: ReplyLatencyWindow(15 * 60, 90 * 60),
    }


def _default_community_type_defaults() -> dict[str, CommunityBehaviorPolicy]:
    return {
        "founder": CommunityBehaviorPolicy(
            reply_latency_tier=ReplyLatencyTier.SHORT_DELAY,
            negative_signal_tolerance="normal",
        ),
        "crypto": CommunityBehaviorPolicy(
            reply_latency_tier=ReplyLatencyTier.NEAR_IMMEDIATE,
            negative_signal_tolerance="high",
        ),
        "hobby": CommunityBehaviorPolicy(
            reply_latency_tier=ReplyLatencyTier.LONG_DELAY,
            negative_signal_tolerance="low",
        ),
    }


def _bounded_int(value: object, *, minimum: int, maximum: int) -> int:
    parsed = int(value)
    return max(min(parsed, maximum), minimum)


def _normalized_tolerance(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in {"low", "normal", "high"}:
        return "normal"
    return normalized


def _increment(bucket: dict[str, int], key: str) -> None:
    bucket[key] = int(bucket.get(key, 0)) + 1


def _increment_nested(bucket: dict[str, dict[str, int]], outer_key: str, inner_key: str) -> None:
    nested = bucket.setdefault(outer_key, {})
    nested[inner_key] = int(nested.get(inner_key, 0)) + 1


def _int_dict(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key).strip(): int(item or 0)
        for key, item in value.items()
        if str(key).strip()
    }


def _nested_int_dict(value: object) -> dict[str, dict[str, int]]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, dict[str, int]] = {}
    for key, nested in value.items():
        normalized_key = str(key).strip()
        if not normalized_key or not isinstance(nested, dict):
            continue
        result[normalized_key] = _int_dict(nested)
    return result


def _parse_datetime(value: object) -> datetime | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    return datetime.fromisoformat(normalized)
