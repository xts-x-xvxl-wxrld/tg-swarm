"""Structured conversion-target records for campaign runtime state."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ConversionTargetKind(StrEnum):
    """Supported destination types for campaign conversion routing."""

    UNKNOWN = "unknown"
    TELEGRAM_DM = "telegram_dm"
    TELEGRAM_BOT = "telegram_bot"
    TELEGRAM_GROUP = "telegram_group"
    TELEGRAM_CHANNEL = "telegram_channel"
    EXTERNAL_WEBSITE = "external_website"


class ConversionTargetFamily(StrEnum):
    """High-level families for campaign conversion routing."""

    UNKNOWN = "unknown"
    TELEGRAM = "telegram"
    EXTERNAL = "external"


@dataclass(slots=True)
class ConversionTargetRecord:
    """One normalized campaign conversion target contract."""

    raw_value: str = ""
    normalized_value: str = ""
    destination_kind: ConversionTargetKind = ConversionTargetKind.UNKNOWN
    destination_family: ConversionTargetFamily = ConversionTargetFamily.UNKNOWN
    delivery_mode: str = ""
    proof_requirement: str = ""
    allowed_action_types: list[str] = field(default_factory=list)
    needs_clarification: bool = False
    source_message_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the record for artifact persistence."""
        return {
            "raw_value": self.raw_value,
            "normalized_value": self.normalized_value,
            "destination_kind": self.destination_kind.value,
            "destination_family": self.destination_family.value,
            "delivery_mode": self.delivery_mode,
            "proof_requirement": self.proof_requirement,
            "allowed_action_types": list(self.allowed_action_types),
            "needs_clarification": self.needs_clarification,
            "source_message_refs": list(self.source_message_refs),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "ConversionTargetRecord":
        """Hydrate a record from persisted artifact data."""
        payload = payload or {}
        raw_kind = payload.get("destination_kind", ConversionTargetKind.UNKNOWN.value)
        raw_family = payload.get("destination_family", ConversionTargetFamily.UNKNOWN.value)
        kind = ConversionTargetKind._value2member_map_.get(raw_kind, ConversionTargetKind.UNKNOWN)
        family = ConversionTargetFamily._value2member_map_.get(raw_family, ConversionTargetFamily.UNKNOWN)
        allowed_action_types = payload.get("allowed_action_types", [])
        source_message_refs = payload.get("source_message_refs", [])
        return cls(
            raw_value=str(payload.get("raw_value", "")),
            normalized_value=str(payload.get("normalized_value", "")),
            destination_kind=kind,
            destination_family=family,
            delivery_mode=str(payload.get("delivery_mode", "")),
            proof_requirement=str(payload.get("proof_requirement", "")),
            allowed_action_types=list(allowed_action_types) if isinstance(allowed_action_types, list) else [],
            needs_clarification=bool(payload.get("needs_clarification", False)),
            source_message_refs=list(source_message_refs) if isinstance(source_message_refs, list) else [],
        )
