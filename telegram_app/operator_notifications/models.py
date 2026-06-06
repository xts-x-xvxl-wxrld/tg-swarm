"""Durable operator-intervention records for campaign recovery flows."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


def utc_now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(UTC)


def parse_datetime(value: object) -> datetime | None:
    """Parse an ISO timestamp, returning None when missing or invalid."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


class OperatorInterventionKind(StrEnum):
    """Small taxonomy of operator-facing intervention families."""

    OPERATOR_REVIEW_REQUIRED = "operator_review_required"
    CAMPAIGN_LOOP_BLOCKED = "campaign_loop_blocked"
    RECURRING_SCHEDULE_PAUSED = "recurring_schedule_paused"
    EXECUTION_CAPACITY_RISK = "execution_capacity_risk"


class OperatorInterventionSeverity(StrEnum):
    """Relative urgency for one operator intervention."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class OperatorInterventionStatus(StrEnum):
    """Lifecycle states for one operator intervention."""

    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


@dataclass(slots=True)
class OperatorInterventionDraft:
    """Derived intervention before it is persisted."""

    campaign_id: str
    kind: OperatorInterventionKind
    dedupe_key: str
    title: str
    body: str
    recovery_hint: str = ""
    severity: OperatorInterventionSeverity = OperatorInterventionSeverity.MEDIUM
    related_refs: list[str] = field(default_factory=list)


@dataclass(slots=True)
class OperatorInterventionRecord:
    """Durable operator-facing intervention state for one campaign."""

    intervention_id: str
    campaign_id: str
    kind: OperatorInterventionKind
    dedupe_key: str
    title: str
    body: str
    recovery_hint: str = ""
    severity: OperatorInterventionSeverity = OperatorInterventionSeverity.MEDIUM
    status: OperatorInterventionStatus = OperatorInterventionStatus.OPEN
    related_refs: list[str] = field(default_factory=list)
    delivery_count: int = 0
    first_detected_at: datetime = field(default_factory=utc_now)
    last_detected_at: datetime = field(default_factory=utc_now)
    last_changed_at: datetime = field(default_factory=utc_now)
    last_delivered_at: datetime | None = None
    acknowledged_at: datetime | None = None
    resolved_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def touch(self) -> None:
        """Refresh the general update timestamp after a mutation."""
        self.updated_at = utc_now()

    def to_dict(self) -> dict[str, Any]:
        """Serialize the intervention for JSON-backed persistence."""
        return {
            "intervention_id": self.intervention_id,
            "campaign_id": self.campaign_id,
            "kind": self.kind.value,
            "dedupe_key": self.dedupe_key,
            "title": self.title,
            "body": self.body,
            "recovery_hint": self.recovery_hint,
            "severity": self.severity.value,
            "status": self.status.value,
            "related_refs": list(self.related_refs),
            "delivery_count": self.delivery_count,
            "first_detected_at": self.first_detected_at.isoformat(),
            "last_detected_at": self.last_detected_at.isoformat(),
            "last_changed_at": self.last_changed_at.isoformat(),
            "last_delivered_at": self.last_delivered_at.isoformat() if self.last_delivered_at else "",
            "acknowledged_at": self.acknowledged_at.isoformat() if self.acknowledged_at else "",
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else "",
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "OperatorInterventionRecord":
        """Hydrate one intervention record from JSON."""
        payload = payload or {}
        raw_kind = str(
            payload.get("kind", OperatorInterventionKind.CAMPAIGN_LOOP_BLOCKED.value)
        ).strip()
        raw_severity = str(
            payload.get("severity", OperatorInterventionSeverity.MEDIUM.value)
        ).strip()
        raw_status = str(
            payload.get("status", OperatorInterventionStatus.OPEN.value)
        ).strip()
        raw_refs = payload.get("related_refs", [])
        return cls(
            intervention_id=str(payload.get("intervention_id", "")).strip(),
            campaign_id=str(payload.get("campaign_id", "")).strip(),
            kind=OperatorInterventionKind._value2member_map_.get(
                raw_kind,
                OperatorInterventionKind.CAMPAIGN_LOOP_BLOCKED,
            ),
            dedupe_key=str(payload.get("dedupe_key", "")).strip(),
            title=str(payload.get("title", "")).strip(),
            body=str(payload.get("body", "")).strip(),
            recovery_hint=str(payload.get("recovery_hint", "")).strip(),
            severity=OperatorInterventionSeverity._value2member_map_.get(
                raw_severity,
                OperatorInterventionSeverity.MEDIUM,
            ),
            status=OperatorInterventionStatus._value2member_map_.get(
                raw_status,
                OperatorInterventionStatus.OPEN,
            ),
            related_refs=[
                str(value).strip()
                for value in raw_refs
                if isinstance(raw_refs, list) and str(value).strip()
            ],
            delivery_count=max(int(payload.get("delivery_count", 0) or 0), 0),
            first_detected_at=parse_datetime(payload.get("first_detected_at")) or utc_now(),
            last_detected_at=parse_datetime(payload.get("last_detected_at")) or utc_now(),
            last_changed_at=parse_datetime(payload.get("last_changed_at")) or utc_now(),
            last_delivered_at=parse_datetime(payload.get("last_delivered_at")),
            acknowledged_at=parse_datetime(payload.get("acknowledged_at")),
            resolved_at=parse_datetime(payload.get("resolved_at")),
            created_at=parse_datetime(payload.get("created_at")) or utc_now(),
            updated_at=parse_datetime(payload.get("updated_at")) or utc_now(),
        )
