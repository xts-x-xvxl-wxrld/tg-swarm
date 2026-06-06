"""Centralized Anthropic model selection for runtime roles."""

from __future__ import annotations

import os

DEFAULT_MODEL_FALLBACK = "anthropic/claude-sonnet-4-6"
SUMMARY_MODEL_FALLBACK = "anthropic/claude-haiku-3-5"


def resolve_model(role: str = "default") -> str:
    """Resolve the Anthropic model for one runtime role."""
    fallback = DEFAULT_MODEL_FALLBACK
    candidates: list[str | None] = []

    if role == "summary":
        fallback = SUMMARY_MODEL_FALLBACK
        candidates.extend(
            [
                os.getenv("SUMMARY_MODEL"),
                os.getenv("DEFAULT_SUMMARY_MODEL"),
            ]
        )
    elif role == "commercial_reasoning":
        candidates.extend(
            [
                os.getenv("COMMERCIAL_REASONING_MODEL"),
                os.getenv("DEFAULT_COMMERCIAL_REASONING_MODEL"),
            ]
        )

    candidates.append(os.getenv("DEFAULT_MODEL"))
    candidates.append(fallback)

    for candidate in candidates:
        normalized = _normalize_anthropic_model(candidate)
        if normalized:
            return normalized
    return _normalize_anthropic_model(DEFAULT_MODEL_FALLBACK) or "claude-sonnet-4-6"


def _normalize_anthropic_model(value: str | None) -> str:
    if not value:
        return ""
    model = value.strip()
    if not model:
        return ""
    if "/" in model:
        model = model.split("/", 1)[1]
    if model.startswith("claude-"):
        return model
    return ""
