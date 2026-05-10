"""Shared capability result types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class CapabilityResult:
    """Structured outcome returned by a Telegram capability."""

    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    audit: dict[str, Any] = field(default_factory=dict)
    error: str = ""

