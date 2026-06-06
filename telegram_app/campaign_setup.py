"""Deterministic helpers for campaign setup state during intake."""

from __future__ import annotations

from typing import Any

from telegram_app.campaign_intent import (
    ASSET_REFS_KEY as INTENT_ASSET_REFS_KEY,
    BUSINESS_CONTEXT_KEY,
    CAMPAIGN_CONSTRAINTS_KEY,
    GEOGRAPHY_HINTS_KEY,
    TARGET_AUDIENCE_SUMMARY_KEY,
)
from telegram_app.models import SessionRecord

CAMPAIGN_SETUP_STATE_KEY = "campaign_setup_state"

READINESS_COLLECTING_INPUTS = "collecting_inputs"
READINESS_READY_TO_CONFIRM = "ready_to_confirm"
READINESS_CONFIRMED = "confirmed"

GOAL_KEY = "goal"
AUDIENCE_KEY = "audience"
OFFER_CONTEXT_KEY = "offer_context"
GEOGRAPHY_KEY = "geography"
CONSTRAINTS_KEY = "constraints"
SUCCESS_INTENT_KEY = "success_intent"
SEED_TARGET_GROUPS_KEY = "seed_target_groups"
ASSET_REFS_KEY = "asset_refs"
READINESS_STATUS_KEY = "readiness_status"
LAST_MISSING_QUESTION_HINT_KEY = "last_missing_question_hint"
MISSING_FIELDS_KEY = "missing_fields"

_REQUIRED_FIELDS = (GOAL_KEY, AUDIENCE_KEY)
_QUESTION_HINTS = {
    GOAL_KEY: "What is the main campaign goal?",
    AUDIENCE_KEY: "Who is the main audience?",
    OFFER_CONTEXT_KEY: "What product, offer, or service should this campaign represent?",
    GEOGRAPHY_KEY: "Is there a geography or market focus to keep in mind?",
}
_EXPLICIT_DISCOVERY_START_PHRASES = (
    "start discovery",
    "begin discovery",
    "kick off discovery",
    "move to discovery",
    "start the discovery",
    "begin the discovery",
    "start research",
    "begin research",
    "kick off research",
    "start the search",
    "begin the search",
)
_LOW_SIGNAL_ACKNOWLEDGEMENTS = {
    "ok",
    "okay",
    "sounds good",
    "got it",
    "thanks",
    "thank you",
    "sure",
    "continue",
}


def get_campaign_setup_state(session: SessionRecord) -> dict[str, Any]:
    """Return the persisted campaign setup state for one session."""
    payload = session.workflow_state.get(CAMPAIGN_SETUP_STATE_KEY, {})
    if not isinstance(payload, dict):
        payload = {}
    return _merge_setup_state(_default_campaign_setup_state(), payload)


def save_campaign_setup_state(session: SessionRecord, state: dict[str, Any]) -> None:
    """Persist campaign setup state back into session workflow storage."""
    session.workflow_state[CAMPAIGN_SETUP_STATE_KEY] = _merge_setup_state(
        _default_campaign_setup_state(),
        state,
    )


def derive_campaign_setup_state(
    brief_data: dict[str, Any] | None,
    *,
    intent_data: dict[str, Any] | None = None,
    existing_state: dict[str, Any] | None = None,
    confirmed: bool = False,
) -> dict[str, Any]:
    """Build the current campaign setup state from the current intent plus brief compatibility data."""
    state = _merge_setup_state(_default_campaign_setup_state(), existing_state or {})
    brief = dict(brief_data or {})
    intent = dict(intent_data or {})

    geography_hints = _normalize_string_list(intent.get(GEOGRAPHY_HINTS_KEY, []))
    intent_constraints = _normalize_string_list(intent.get(CAMPAIGN_CONSTRAINTS_KEY, []))
    state[GOAL_KEY] = _normalize_text(brief.get("objective", "")) or _normalize_text(intent.get(BUSINESS_CONTEXT_KEY, ""))
    state[AUDIENCE_KEY] = _normalize_text(brief.get("target_audience", "")) or _normalize_text(intent.get(TARGET_AUDIENCE_SUMMARY_KEY, ""))
    state[OFFER_CONTEXT_KEY] = _normalize_text(brief.get("offer", ""))
    state[GEOGRAPHY_KEY] = _normalize_text(brief.get("geography", "")) or (geography_hints[0] if geography_hints else "")
    state[CONSTRAINTS_KEY] = _normalize_string_list(brief.get("constraints", [])) or intent_constraints
    state[SUCCESS_INTENT_KEY] = _normalize_string_list(brief.get("success_criteria", []))
    state[SEED_TARGET_GROUPS_KEY] = _normalize_string_list(brief.get("seed_target_groups", []))
    state[ASSET_REFS_KEY] = _normalize_string_list(intent.get(INTENT_ASSET_REFS_KEY, [])) or _normalize_string_list(state.get(ASSET_REFS_KEY, []))

    missing_fields = _missing_required_fields(state)
    state[MISSING_FIELDS_KEY] = missing_fields
    if confirmed:
        state[READINESS_STATUS_KEY] = READINESS_CONFIRMED
        state[LAST_MISSING_QUESTION_HINT_KEY] = ""
    elif missing_fields:
        state[READINESS_STATUS_KEY] = READINESS_COLLECTING_INPUTS
        state[LAST_MISSING_QUESTION_HINT_KEY] = _QUESTION_HINTS.get(missing_fields[0], "")
    else:
        state[READINESS_STATUS_KEY] = READINESS_READY_TO_CONFIRM
        state[LAST_MISSING_QUESTION_HINT_KEY] = ""

    return state


def setup_is_ready_for_confirmation(state: dict[str, Any]) -> bool:
    """Return true when the operator can explicitly begin discovery."""
    return str(state.get(READINESS_STATUS_KEY, "")).strip() in {
        READINESS_READY_TO_CONFIRM,
        READINESS_CONFIRMED,
    }


def setup_is_confirmed(state: dict[str, Any]) -> bool:
    """Return true when the operator has explicitly started discovery."""
    return str(state.get(READINESS_STATUS_KEY, "")).strip() == READINESS_CONFIRMED


def is_explicit_discovery_start_message(message: str) -> bool:
    """Return true when the operator explicitly asks to begin discovery."""
    normalized = _normalize_text(message).lower()
    if not normalized:
        return False
    return any(phrase in normalized for phrase in _EXPLICIT_DISCOVERY_START_PHRASES)


def is_low_signal_setup_acknowledgement(message: str) -> bool:
    """Return true when a message is a pure acknowledgement, not new setup detail."""
    normalized = _normalize_text(message).lower()
    if not normalized:
        return True
    if is_explicit_discovery_start_message(normalized):
        return True
    return normalized in _LOW_SIGNAL_ACKNOWLEDGEMENTS


def _default_campaign_setup_state() -> dict[str, Any]:
    return {
        GOAL_KEY: "",
        AUDIENCE_KEY: "",
        OFFER_CONTEXT_KEY: "",
        GEOGRAPHY_KEY: "",
        CONSTRAINTS_KEY: [],
        SUCCESS_INTENT_KEY: [],
        SEED_TARGET_GROUPS_KEY: [],
        ASSET_REFS_KEY: [],
        READINESS_STATUS_KEY: READINESS_COLLECTING_INPUTS,
        LAST_MISSING_QUESTION_HINT_KEY: _QUESTION_HINTS[GOAL_KEY],
        MISSING_FIELDS_KEY: list(_REQUIRED_FIELDS),
    }


def _merge_setup_state(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if key in {
            CONSTRAINTS_KEY,
            SUCCESS_INTENT_KEY,
            SEED_TARGET_GROUPS_KEY,
            ASSET_REFS_KEY,
            MISSING_FIELDS_KEY,
        }:
            merged[key] = _normalize_string_list(value)
            continue
        merged[key] = _normalize_text(value) if key != READINESS_STATUS_KEY else _normalize_text(value)
    return merged


def _missing_required_fields(state: dict[str, Any]) -> list[str]:
    return [
        field_name
        for field_name in _REQUIRED_FIELDS
        if not _normalize_text(state.get(field_name, ""))
    ]


def _normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized_values: list[str] = []
    for item in value:
        normalized_item = _normalize_text(item)
        if normalized_item and normalized_item not in normalized_values:
            normalized_values.append(normalized_item)
    return normalized_values


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())
