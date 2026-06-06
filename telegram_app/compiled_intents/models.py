"""Typed compiled-intent records persisted before runtime mutation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


def utc_now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(UTC)


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return datetime.fromisoformat(value)


class CompiledIntentSafetyClass(StrEnum):
    """Compact safety classes used by deterministic policy and audit trails."""

    ADVISORY = "advisory"
    STATE_MUTATION = "state_mutation"
    SCHEDULE_MUTATION = "schedule_mutation"
    EXECUTION_ADJACENT = "execution_adjacent"
    EXTERNAL_WRITE = "external_write"


class CompiledIntentStatus(StrEnum):
    """Lifecycle states for one compiled intent."""

    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    BLOCKED = "blocked"
    APPLIED = "applied"


@dataclass(slots=True)
class CompiledIntentRecord:
    """Durable typed proposal used for runtime mutation and inspection."""

    intent_id: str
    campaign_id: str
    kind: str
    summary: str
    payload: dict[str, Any] = field(default_factory=dict)
    grounding_refs: list[str] = field(default_factory=list)
    source_role: str = ""
    confidence: float | None = None
    ambiguity: str = ""
    safety_class: CompiledIntentSafetyClass = CompiledIntentSafetyClass.ADVISORY
    status: CompiledIntentStatus = CompiledIntentStatus.PROPOSED
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    accepted_at: datetime | None = None
    rejected_at: datetime | None = None
    blocked_at: datetime | None = None
    applied_at: datetime | None = None
    rejection_reason: str = ""
    blocked_reason: str = ""
    application_result: str = ""

    def touch(self) -> None:
        """Refresh the update timestamp after a mutation."""
        self.updated_at = utc_now()

    def mark_accepted(self) -> None:
        """Advance the record into the accepted state."""
        self.status = CompiledIntentStatus.ACCEPTED
        self.accepted_at = utc_now()
        self.rejected_at = None
        self.blocked_at = None
        self.rejection_reason = ""
        self.blocked_reason = ""
        self.touch()

    def mark_rejected(self, reason: str) -> None:
        """Advance the record into the rejected state."""
        self.status = CompiledIntentStatus.REJECTED
        self.rejected_at = utc_now()
        self.blocked_at = None
        self.rejection_reason = reason.strip()
        self.blocked_reason = ""
        self.touch()

    def mark_blocked(self, reason: str) -> None:
        """Advance the record into the blocked state."""
        self.status = CompiledIntentStatus.BLOCKED
        self.blocked_at = utc_now()
        self.blocked_reason = reason.strip()
        self.touch()

    def mark_applied(self, result: str) -> None:
        """Advance the record into the applied state."""
        self.status = CompiledIntentStatus.APPLIED
        self.applied_at = utc_now()
        self.blocked_at = None
        self.application_result = result.strip()
        self.blocked_reason = ""
        self.touch()

    def to_dict(self) -> dict[str, Any]:
        """Serialize the record for JSON-backed campaign storage."""
        return {
            "intent_id": self.intent_id,
            "campaign_id": self.campaign_id,
            "kind": self.kind,
            "summary": self.summary,
            "payload": dict(self.payload),
            "grounding_refs": list(self.grounding_refs),
            "source_role": self.source_role,
            "confidence": self.confidence,
            "ambiguity": self.ambiguity,
            "safety_class": self.safety_class.value,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "accepted_at": self.accepted_at.isoformat() if self.accepted_at is not None else None,
            "rejected_at": self.rejected_at.isoformat() if self.rejected_at is not None else None,
            "blocked_at": self.blocked_at.isoformat() if self.blocked_at is not None else None,
            "applied_at": self.applied_at.isoformat() if self.applied_at is not None else None,
            "rejection_reason": self.rejection_reason,
            "blocked_reason": self.blocked_reason,
            "application_result": self.application_result,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "CompiledIntentRecord":
        """Hydrate a compiled-intent record from JSON."""
        payload = payload or {}
        raw_safety_class = str(payload.get("safety_class", CompiledIntentSafetyClass.ADVISORY.value))
        raw_status = str(payload.get("status", CompiledIntentStatus.PROPOSED.value))
        return cls(
            intent_id=str(payload.get("intent_id", "")).strip(),
            campaign_id=str(payload.get("campaign_id", "")).strip(),
            kind=str(payload.get("kind", "")).strip(),
            summary=str(payload.get("summary", "")).strip(),
            payload=dict(payload.get("payload", {})) if isinstance(payload.get("payload"), dict) else {},
            grounding_refs=[
                str(value).strip()
                for value in payload.get("grounding_refs", [])
                if isinstance(payload.get("grounding_refs"), list) and str(value).strip()
            ],
            source_role=str(payload.get("source_role", "")).strip(),
            confidence=float(payload["confidence"]) if isinstance(payload.get("confidence"), (int, float)) else None,
            ambiguity=str(payload.get("ambiguity", "")).strip(),
            safety_class=CompiledIntentSafetyClass._value2member_map_.get(
                raw_safety_class,
                CompiledIntentSafetyClass.ADVISORY,
            ),
            status=CompiledIntentStatus._value2member_map_.get(
                raw_status,
                CompiledIntentStatus.PROPOSED,
            ),
            created_at=_parse_datetime(payload.get("created_at")) or utc_now(),
            updated_at=_parse_datetime(payload.get("updated_at")) or utc_now(),
            accepted_at=_parse_datetime(payload.get("accepted_at")),
            rejected_at=_parse_datetime(payload.get("rejected_at")),
            blocked_at=_parse_datetime(payload.get("blocked_at")),
            applied_at=_parse_datetime(payload.get("applied_at")),
            rejection_reason=str(payload.get("rejection_reason", "")).strip(),
            blocked_reason=str(payload.get("blocked_reason", "")).strip(),
            application_result=str(payload.get("application_result", "")).strip(),
        )
