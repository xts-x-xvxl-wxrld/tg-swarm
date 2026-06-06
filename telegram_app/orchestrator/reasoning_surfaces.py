"""Shared reasoning-surface vocabulary for the Telegram runtime."""

from __future__ import annotations

from typing import Final

CONTROL_BRAIN_SURFACE: Final[str] = "operator_control_brain"
PLANNING_SURFACE: Final[str] = "campaign_planning"
CHEAP_TRIAGE_SURFACE: Final[str] = "cheap_inbound_triage"
PROMOTED_THREAD_SURFACE: Final[str] = "promoted_thread_reasoning"
OBSERVATION_SURFACE: Final[str] = "campaign_observation"
DETERMINISTIC_EXECUTION_SURFACE: Final[str] = "deterministic_execution"

_SURFACE_CATALOG: Final[tuple[dict[str, str], ...]] = (
    {
        "surface": CONTROL_BRAIN_SURFACE,
        "role": "control_brain",
        "status": "operator_facing",
        "summary": "Interprets freeform operator intent, runtime pressure, and bounded work selection.",
    },
    {
        "surface": PLANNING_SURFACE,
        "role": "planning_work_families",
        "status": "active",
        "summary": "Hosts bounded planning work families such as discovery, strategy, account planning, and future planning reviews.",
    },
    {
        "surface": CHEAP_TRIAGE_SURFACE,
        "role": "inbound_triage",
        "status": "active",
        "summary": "Handles low-cost inbound reading and decides what needs deeper review.",
    },
    {
        "surface": PROMOTED_THREAD_SURFACE,
        "role": "commercial_reasoning",
        "status": "active",
        "summary": "Handles promoted-thread reasoning, belief-state updates, and bounded next-move proposals.",
    },
    {
        "surface": OBSERVATION_SURFACE,
        "role": "campaign_review",
        "status": "active",
        "summary": "Reviews campaign-level signals, priority pressure, and follow-on planning needs.",
    },
    {
        "surface": DETERMINISTIC_EXECUTION_SURFACE,
        "role": "policy_and_execution",
        "status": "runtime_owned",
        "summary": "Owns policy, consent, readiness, queueing, retries, and external writes.",
    },
)


def build_reasoning_surface_catalog() -> list[dict[str, str]]:
    """Return a prompt-safe description of the runtime's reasoning surfaces."""
    return [dict(item) for item in _SURFACE_CATALOG]


def reasoning_surface_for_work_type(work_type: str) -> str:
    """Map a work type to its conceptual reasoning surface."""
    normalized = str(work_type or "").strip()
    if normalized == "observation":
        return OBSERVATION_SURFACE
    if normalized:
        return PLANNING_SURFACE
    return CONTROL_BRAIN_SURFACE
