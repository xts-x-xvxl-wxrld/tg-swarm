"""Helpers for the campaign intent package synthesized during intake."""

from __future__ import annotations

import re
from typing import Any

from telegram_app.conversion_target import infer_destination_kind, normalize_destination_reference

OBJECTIVE_KEY = "objective"
TARGET_AUDIENCE_KEY = "target_audience"
OFFER_KEY = "offer"
GEOGRAPHY_KEY = "geography"
LANGUAGE_KEY = "language"
CONSTRAINTS_KEY = "constraints"
SUCCESS_CRITERIA_KEY = "success_criteria"
SEED_TARGET_GROUPS_KEY = "seed_target_groups"

BUSINESS_CONTEXT_KEY = "business_context"
OFFER_SUMMARY_KEY = "offer_summary"
TARGET_AUDIENCE_SUMMARY_KEY = "target_audience"
GEOGRAPHY_HINTS_KEY = "geography_hints"
LANGUAGE_HINTS_KEY = "language_hints"
SEED_INPUTS_KEY = "seed_inputs"
ASSET_REFS_KEY = "asset_refs"
QUALIFICATION_POSTURE_KEY = "qualification_posture"
CONVERSION_TARGET_SIGNAL_KEY = "conversion_target_signal"
AUTONOMY_POSTURE_KEY = "autonomy_posture"
CAMPAIGN_CONSTRAINTS_KEY = "campaign_constraints"
AMBIGUITIES_KEY = "ambiguities"
SOURCE_MESSAGE_REFS_KEY = "source_message_refs"

RAW_ENTRIES_KEY = "raw_entries"
NORMALIZED_CANDIDATES_KEY = "normalized_candidates"
UNRESOLVED_MENTIONS_KEY = "unresolved_mentions"

RAW_VALUE_KEY = "raw_value"
KIND_HINT_KEY = "kind_hint"
NEEDS_CLARIFICATION_KEY = "needs_clarification"
NORMALIZED_VALUE_KEY = "normalized_value"

OPERATOR_STATED_KEY = "operator_stated"
BOUNDED_MODE_KEY = "bounded_mode"

_LANGUAGE_HINT_PATTERNS = {
    "Arabic": re.compile(r"\barabic\b", re.IGNORECASE),
    "English": re.compile(r"\benglish(?:-speaking)?\b", re.IGNORECASE),
    "French": re.compile(r"\bfrench\b", re.IGNORECASE),
    "German": re.compile(r"\bgerman\b", re.IGNORECASE),
    "Hungarian": re.compile(r"\bhungarian\b", re.IGNORECASE),
    "Russian": re.compile(r"\brussian\b", re.IGNORECASE),
    "Spanish": re.compile(r"\bspanish\b", re.IGNORECASE),
}
_AUTONOMY_PATTERNS = (
    re.compile(r"\bkeep running until [^.!\n]+\b", re.IGNORECASE),
    re.compile(r"\brun until [^.!\n]+\b", re.IGNORECASE),
    re.compile(r"\buntil paused\b", re.IGNORECASE),
)
_CONVERSION_PATTERNS = (
    re.compile(
        r"\b(send|route|handoff)\s+(?:qualified\s+)?(?:leads|prospects)\s+to\s+(?P<target>[^\n;]+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bleads?\s+should\s+end\s+up\s+in\s+(?P<target>[^\n;]+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bqualified\s+leads?\s+should\s+go\s+to\s+(?P<target>[^\n;]+)",
        re.IGNORECASE,
    ),
)
_SEED_LINK_PATTERN = re.compile(r"(?:https?://)?t\.me/[A-Za-z0-9_+/=-]+", re.IGNORECASE)
_HANDLE_PATTERN = re.compile(r"(?<!\w)@[A-Za-z][A-Za-z0-9_]{2,}")


def default_campaign_intent_data() -> dict[str, Any]:
    """Return the default durable shape for one campaign intent package."""
    return {
        BUSINESS_CONTEXT_KEY: "",
        OFFER_SUMMARY_KEY: "",
        TARGET_AUDIENCE_SUMMARY_KEY: "",
        GEOGRAPHY_HINTS_KEY: [],
        LANGUAGE_HINTS_KEY: [],
        SEED_INPUTS_KEY: {
            RAW_ENTRIES_KEY: [],
            NORMALIZED_CANDIDATES_KEY: [],
            UNRESOLVED_MENTIONS_KEY: [],
        },
        ASSET_REFS_KEY: [],
        QUALIFICATION_POSTURE_KEY: "",
        CONVERSION_TARGET_SIGNAL_KEY: {},
        AUTONOMY_POSTURE_KEY: {},
        CAMPAIGN_CONSTRAINTS_KEY: [],
        AMBIGUITIES_KEY: [],
        SOURCE_MESSAGE_REFS_KEY: [],
    }


def merge_campaign_intent_data(
    existing_data: dict[str, Any] | None,
    *,
    message: str,
    source_message_id: str = "",
    field_updates: dict[str, Any] | None = None,
    setup_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Refresh the durable intent package from one operator turn."""
    field_updates = field_updates or {}
    setup_state = setup_state or {}
    intent = _normalize_campaign_intent_data(existing_data)

    business_context = _first_non_empty(
        _normalize_text(field_updates.get(OFFER_KEY, "")),
        _normalize_text(field_updates.get(OBJECTIVE_KEY, "")),
        intent[BUSINESS_CONTEXT_KEY],
    )
    if business_context:
        intent[BUSINESS_CONTEXT_KEY] = business_context

    offer_summary = _first_non_empty(
        _normalize_text(field_updates.get(OFFER_KEY, "")),
        intent[OFFER_SUMMARY_KEY],
    )
    if offer_summary:
        intent[OFFER_SUMMARY_KEY] = offer_summary

    target_audience = _first_non_empty(
        _normalize_text(field_updates.get(TARGET_AUDIENCE_KEY, "")),
        intent[TARGET_AUDIENCE_SUMMARY_KEY],
    )
    if target_audience:
        intent[TARGET_AUDIENCE_SUMMARY_KEY] = target_audience

    intent[GEOGRAPHY_HINTS_KEY] = _merge_unique_strings(
        intent.get(GEOGRAPHY_HINTS_KEY, []),
        _extract_geography_hints(message, field_updates),
    )
    intent[LANGUAGE_HINTS_KEY] = _merge_unique_strings(
        intent.get(LANGUAGE_HINTS_KEY, []),
        _extract_language_hints(message, field_updates),
    )
    intent[SEED_INPUTS_KEY] = _merge_seed_inputs(
        intent.get(SEED_INPUTS_KEY, {}),
        message=message,
        field_updates=field_updates,
    )

    intent[ASSET_REFS_KEY] = _normalize_string_list(setup_state.get(ASSET_REFS_KEY, []))

    qualification_posture = _extract_qualification_posture(message, field_updates)
    if qualification_posture:
        intent[QUALIFICATION_POSTURE_KEY] = qualification_posture

    conversion_signal = _extract_conversion_target_signal(message)
    if conversion_signal:
        intent[CONVERSION_TARGET_SIGNAL_KEY] = conversion_signal
        intent[SEED_INPUTS_KEY] = _remove_conversion_destination_from_seed_inputs(
            intent.get(SEED_INPUTS_KEY, {}),
            conversion_signal,
        )

    autonomy_posture = _extract_autonomy_posture(message)
    if autonomy_posture:
        intent[AUTONOMY_POSTURE_KEY] = autonomy_posture

    intent[CAMPAIGN_CONSTRAINTS_KEY] = _merge_unique_strings(
        intent.get(CAMPAIGN_CONSTRAINTS_KEY, []),
        _normalize_string_list(field_updates.get(CONSTRAINTS_KEY, [])),
    )
    intent[SOURCE_MESSAGE_REFS_KEY] = _merge_unique_strings(
        intent.get(SOURCE_MESSAGE_REFS_KEY, []),
        [_build_source_message_ref(intent.get(SOURCE_MESSAGE_REFS_KEY, []), source_message_id)],
    )
    intent[AMBIGUITIES_KEY] = _build_ambiguities(intent)
    return intent


def build_campaign_intent_summary(intent_data: dict[str, Any] | None) -> str:
    """Return a compact operator-facing summary of the current intent package."""
    intent = _normalize_campaign_intent_data(intent_data)
    parts: list[str] = []

    business_context = str(intent.get(BUSINESS_CONTEXT_KEY, "")).strip()
    if business_context:
        parts.append(f"Campaign focus: {business_context}.")

    target_audience = str(intent.get(TARGET_AUDIENCE_SUMMARY_KEY, "")).strip()
    if target_audience:
        parts.append(f"Audience: {target_audience}.")

    seed_inputs = intent.get(SEED_INPUTS_KEY, {})
    normalized_candidates = []
    if isinstance(seed_inputs, dict):
        normalized_candidates = _normalize_string_list(seed_inputs.get(NORMALIZED_CANDIDATES_KEY, []))
    if normalized_candidates:
        parts.append(f"Recognized {len(normalized_candidates)} seed community candidates.")

    asset_refs = _normalize_string_list(intent.get(ASSET_REFS_KEY, []))
    if asset_refs:
        parts.append(f"Attached {len(asset_refs)} stored campaign assets.")

    conversion_signal = intent.get(CONVERSION_TARGET_SIGNAL_KEY, {})
    if isinstance(conversion_signal, dict):
        raw_value = _normalize_text(conversion_signal.get(RAW_VALUE_KEY, ""))
        if raw_value:
            parts.append(f"Conversion target signal: {raw_value}.")

    ambiguities = _normalize_string_list(intent.get(AMBIGUITIES_KEY, []))
    if ambiguities:
        parts.append(f"Open ambiguities: {len(ambiguities)}.")

    if not parts:
        return "Campaign intent package started from operator input."
    return " ".join(parts)


def build_campaign_brief_from_intent(
    intent_data: dict[str, Any] | None,
    *,
    existing_brief: dict[str, Any] | None = None,
    field_updates: dict[str, Any] | None = None,
    message: str,
) -> dict[str, Any]:
    """Return a compatibility campaign brief derived from the current intent package."""
    field_updates = field_updates or {}
    brief = {
        "objective": "",
        "target_audience": "",
        "offer": "",
        "geography": "",
        "language": "",
        "constraints": [],
        "success_criteria": [],
        "seed_target_groups": [],
        "notes": [],
        "source_messages": [],
    }
    if isinstance(existing_brief, dict):
        for key in brief:
            if key not in existing_brief:
                continue
            if key in {"constraints", "success_criteria", "seed_target_groups", "notes", "source_messages"}:
                brief[key] = _normalize_string_list(existing_brief.get(key, []))
            else:
                brief[key] = _normalize_text(existing_brief.get(key, ""))

    intent = _normalize_campaign_intent_data(intent_data)
    if not brief["objective"]:
        brief["objective"] = str(intent.get(BUSINESS_CONTEXT_KEY, "")).strip()
    brief["objective"] = _first_non_empty(
        _normalize_text(field_updates.get(OBJECTIVE_KEY, "")),
        brief["objective"],
    )
    brief["target_audience"] = _first_non_empty(
        _normalize_text(field_updates.get(TARGET_AUDIENCE_KEY, "")),
        brief["target_audience"],
        str(intent.get(TARGET_AUDIENCE_SUMMARY_KEY, "")).strip(),
    )
    brief["offer"] = _first_non_empty(
        _normalize_text(field_updates.get(OFFER_KEY, "")),
        brief["offer"],
        str(intent.get(OFFER_SUMMARY_KEY, "")).strip(),
    )

    geography_hints = _normalize_string_list(intent.get(GEOGRAPHY_HINTS_KEY, []))
    language_hints = _normalize_string_list(intent.get(LANGUAGE_HINTS_KEY, []))
    brief["geography"] = _first_non_empty(
        _normalize_text(field_updates.get(GEOGRAPHY_KEY, "")),
        brief["geography"],
        geography_hints[0] if geography_hints else "",
    )
    brief["language"] = _first_non_empty(
        _normalize_text(field_updates.get(LANGUAGE_KEY, "")),
        brief["language"],
        ", ".join(language_hints),
    )

    brief["constraints"] = _merge_unique_strings(
        brief["constraints"],
        _normalize_string_list(field_updates.get(CONSTRAINTS_KEY, [])) or _normalize_string_list(intent.get(CAMPAIGN_CONSTRAINTS_KEY, [])),
    )
    brief["success_criteria"] = _merge_unique_strings(
        brief["success_criteria"],
        _normalize_string_list(field_updates.get(SUCCESS_CRITERIA_KEY, [])),
    )

    seed_inputs = intent.get(SEED_INPUTS_KEY, {})
    raw_entries = []
    normalized_candidates = []
    unresolved_mentions = []
    if isinstance(seed_inputs, dict):
        raw_entries = _normalize_string_list(seed_inputs.get(RAW_ENTRIES_KEY, []))
        normalized_candidates = _normalize_string_list(seed_inputs.get(NORMALIZED_CANDIDATES_KEY, []))
        unresolved_mentions = _normalize_string_list(seed_inputs.get(UNRESOLVED_MENTIONS_KEY, []))
    brief["seed_target_groups"] = _merge_unique_strings(
        brief["seed_target_groups"],
        _normalize_string_list(field_updates.get(SEED_TARGET_GROUPS_KEY, []))
        or raw_entries
        or normalized_candidates
        or unresolved_mentions,
    )

    explicit_notes = _normalize_string_list(field_updates.get("notes", []))
    if explicit_notes:
        brief["notes"] = _merge_unique_strings(brief["notes"], explicit_notes)

    if not _normalize_text(field_updates.get(OBJECTIVE_KEY, "")) and not brief["objective"]:
        brief["objective"] = _normalize_text(message)

    brief["source_messages"] = _merge_unique_strings(
        brief["source_messages"],
        [_normalize_text(message)],
    )
    return brief


def prompt_safe_campaign_intent_data(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Return a compact prompt-safe view of the campaign intent package."""
    intent = _normalize_campaign_intent_data(payload)
    return {
        key: value
        for key, value in intent.items()
        if value not in ("", [], {}, None)
    }


def _normalize_campaign_intent_data(payload: dict[str, Any] | None) -> dict[str, Any]:
    base = default_campaign_intent_data()
    if not isinstance(payload, dict):
        return base

    for key in (
        BUSINESS_CONTEXT_KEY,
        OFFER_SUMMARY_KEY,
        TARGET_AUDIENCE_SUMMARY_KEY,
        QUALIFICATION_POSTURE_KEY,
    ):
        base[key] = _normalize_text(payload.get(key, ""))

    for key in (
        GEOGRAPHY_HINTS_KEY,
        LANGUAGE_HINTS_KEY,
        ASSET_REFS_KEY,
        CAMPAIGN_CONSTRAINTS_KEY,
        AMBIGUITIES_KEY,
        SOURCE_MESSAGE_REFS_KEY,
    ):
        base[key] = _normalize_string_list(payload.get(key, []))

    seed_payload = payload.get(SEED_INPUTS_KEY, {})
    if isinstance(seed_payload, dict):
        base[SEED_INPUTS_KEY] = {
            RAW_ENTRIES_KEY: _normalize_string_list(seed_payload.get(RAW_ENTRIES_KEY, [])),
            NORMALIZED_CANDIDATES_KEY: _normalize_string_list(seed_payload.get(NORMALIZED_CANDIDATES_KEY, [])),
            UNRESOLVED_MENTIONS_KEY: _normalize_string_list(seed_payload.get(UNRESOLVED_MENTIONS_KEY, [])),
        }

    conversion_payload = payload.get(CONVERSION_TARGET_SIGNAL_KEY, {})
    if isinstance(conversion_payload, dict):
        base[CONVERSION_TARGET_SIGNAL_KEY] = {
            RAW_VALUE_KEY: _normalize_text(conversion_payload.get(RAW_VALUE_KEY, "")),
            KIND_HINT_KEY: _normalize_text(conversion_payload.get(KIND_HINT_KEY, "")),
            NEEDS_CLARIFICATION_KEY: bool(conversion_payload.get(NEEDS_CLARIFICATION_KEY, False)),
        }
        normalized_value = _normalize_text(conversion_payload.get(NORMALIZED_VALUE_KEY, ""))
        if normalized_value:
            base[CONVERSION_TARGET_SIGNAL_KEY][NORMALIZED_VALUE_KEY] = normalized_value

    autonomy_payload = payload.get(AUTONOMY_POSTURE_KEY, {})
    if isinstance(autonomy_payload, dict):
        base[AUTONOMY_POSTURE_KEY] = {
            OPERATOR_STATED_KEY: _normalize_text(autonomy_payload.get(OPERATOR_STATED_KEY, "")),
            BOUNDED_MODE_KEY: _normalize_text(autonomy_payload.get(BOUNDED_MODE_KEY, "")),
        }
        base[AUTONOMY_POSTURE_KEY] = {
            key: value
            for key, value in base[AUTONOMY_POSTURE_KEY].items()
            if value
        }

    return base


def _extract_geography_hints(message: str, field_updates: dict[str, Any]) -> list[str]:
    explicit_geography = _normalize_text(field_updates.get(GEOGRAPHY_KEY, ""))
    if explicit_geography:
        return [explicit_geography]

    objective = _normalize_text(field_updates.get(OBJECTIVE_KEY, ""))
    if not objective:
        return []

    candidate = _extract_phrase_after_keyword(objective, keyword="in", stop_keywords=("for", "with"))
    if len(candidate.split()) > 5:
        return []
    return [candidate] if candidate else []


def _extract_language_hints(message: str, field_updates: dict[str, Any]) -> list[str]:
    explicit_language = _normalize_text(field_updates.get(LANGUAGE_KEY, ""))
    hints: list[str] = []
    if explicit_language:
        hints.extend(_split_list_like_text(explicit_language))

    for label, pattern in _LANGUAGE_HINT_PATTERNS.items():
        if pattern.search(message):
            hints.append(label)
    return _normalize_string_list(hints)


def _merge_seed_inputs(
    existing_seed_inputs: dict[str, Any] | None,
    *,
    message: str,
    field_updates: dict[str, Any],
) -> dict[str, Any]:
    existing_seed_inputs = existing_seed_inputs if isinstance(existing_seed_inputs, dict) else {}
    raw_entries = _normalize_string_list(existing_seed_inputs.get(RAW_ENTRIES_KEY, []))
    normalized_candidates = _normalize_string_list(existing_seed_inputs.get(NORMALIZED_CANDIDATES_KEY, []))
    unresolved_mentions = _normalize_string_list(existing_seed_inputs.get(UNRESOLVED_MENTIONS_KEY, []))

    seed_entries = _normalize_string_list(field_updates.get(SEED_TARGET_GROUPS_KEY, []))
    detected_entries = _extract_seed_candidates_from_message(message)
    for entry in [*seed_entries, *detected_entries]:
        if entry not in raw_entries:
            raw_entries.append(entry)
        normalized_entry = _normalize_seed_entry(entry)
        if normalized_entry:
            if normalized_entry not in normalized_candidates:
                normalized_candidates.append(normalized_entry)
            continue
        if entry not in unresolved_mentions:
            unresolved_mentions.append(entry)

    return {
        RAW_ENTRIES_KEY: raw_entries,
        NORMALIZED_CANDIDATES_KEY: normalized_candidates,
        UNRESOLVED_MENTIONS_KEY: unresolved_mentions,
    }


def _extract_seed_candidates_from_message(message: str) -> list[str]:
    scrubbed_message = message
    for pattern in _CONVERSION_PATTERNS:
        scrubbed_message = pattern.sub("", scrubbed_message)

    candidates = [match.group(0) for match in _SEED_LINK_PATTERN.finditer(scrubbed_message)]
    candidates.extend(match.group(0) for match in _HANDLE_PATTERN.finditer(scrubbed_message))
    return _normalize_string_list(candidates)


def _extract_qualification_posture(message: str, field_updates: dict[str, Any]) -> str:
    explicit_success = _normalize_string_list(field_updates.get(SUCCESS_CRITERIA_KEY, []))
    if explicit_success:
        return "; ".join(explicit_success[:2])

    for sentence in _split_sentences(message):
        lowered = sentence.lower()
        if "qualif" in lowered or "qualified" in lowered:
            return sentence
    return ""


def _extract_conversion_target_signal(message: str) -> dict[str, Any]:
    for pattern in _CONVERSION_PATTERNS:
        match = pattern.search(message)
        if not match:
            continue
        target = _normalize_target_phrase(match.group("target"))
        if not target:
            continue
        normalized_target = normalize_destination_reference(target)
        kind_hint = infer_destination_kind(target)
        return {
            RAW_VALUE_KEY: target,
            KIND_HINT_KEY: kind_hint,
            NEEDS_CLARIFICATION_KEY: not bool(normalized_target or kind_hint),
            NORMALIZED_VALUE_KEY: normalized_target,
        }
    return {}


def _extract_autonomy_posture(message: str) -> dict[str, Any]:
    for pattern in _AUTONOMY_PATTERNS:
        match = pattern.search(message)
        if not match:
            continue
        operator_stated = _normalize_text(match.group(0))
        if not operator_stated:
            continue
        bounded_mode = "continuous" if "keep running" in operator_stated.lower() or "until paused" in operator_stated.lower() else "default"
        return {
            OPERATOR_STATED_KEY: operator_stated,
            BOUNDED_MODE_KEY: bounded_mode,
        }
    return {}


def _remove_conversion_destination_from_seed_inputs(
    seed_inputs: dict[str, Any],
    conversion_signal: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(seed_inputs, dict):
        return {
            RAW_ENTRIES_KEY: [],
            NORMALIZED_CANDIDATES_KEY: [],
            UNRESOLVED_MENTIONS_KEY: [],
        }

    raw_value = _normalize_text(conversion_signal.get(RAW_VALUE_KEY, ""))
    normalized_value = _normalize_text(conversion_signal.get(NORMALIZED_VALUE_KEY, ""))
    removal_values = {
        value
        for value in (raw_value, normalized_value, _normalize_seed_entry(raw_value))
        if value
    }
    if not removal_values:
        return {
            RAW_ENTRIES_KEY: _normalize_string_list(seed_inputs.get(RAW_ENTRIES_KEY, [])),
            NORMALIZED_CANDIDATES_KEY: _normalize_string_list(seed_inputs.get(NORMALIZED_CANDIDATES_KEY, [])),
            UNRESOLVED_MENTIONS_KEY: _normalize_string_list(seed_inputs.get(UNRESOLVED_MENTIONS_KEY, [])),
        }

    return {
        RAW_ENTRIES_KEY: [
            value
            for value in _normalize_string_list(seed_inputs.get(RAW_ENTRIES_KEY, []))
            if value not in removal_values
        ],
        NORMALIZED_CANDIDATES_KEY: [
            value
            for value in _normalize_string_list(seed_inputs.get(NORMALIZED_CANDIDATES_KEY, []))
            if value not in removal_values
        ],
        UNRESOLVED_MENTIONS_KEY: [
            value
            for value in _normalize_string_list(seed_inputs.get(UNRESOLVED_MENTIONS_KEY, []))
            if value not in removal_values
        ],
    }


def _build_ambiguities(intent: dict[str, Any]) -> list[str]:
    ambiguities: list[str] = []
    if not str(intent.get(BUSINESS_CONTEXT_KEY, "")).strip():
        ambiguities.append("Campaign goal or business context is still unclear.")
    if not str(intent.get(TARGET_AUDIENCE_SUMMARY_KEY, "")).strip():
        ambiguities.append("Target audience is still unclear.")

    seed_inputs = intent.get(SEED_INPUTS_KEY, {})
    if isinstance(seed_inputs, dict):
        unresolved_mentions = _normalize_string_list(seed_inputs.get(UNRESOLVED_MENTIONS_KEY, []))
        if unresolved_mentions:
            ambiguities.append(
                "Unresolved seed inputs: " + ", ".join(unresolved_mentions[:3])
            )

    conversion_signal = intent.get(CONVERSION_TARGET_SIGNAL_KEY, {})
    if isinstance(conversion_signal, dict) and conversion_signal.get(NEEDS_CLARIFICATION_KEY):
        ambiguities.append("Conversion destination needs clarification.")
    return ambiguities
def _build_source_message_ref(existing_refs: list[str] | Any, source_message_id: str) -> str:
    normalized_source_id = _normalize_text(source_message_id)
    if normalized_source_id:
        return normalized_source_id
    ref_count = len(_normalize_string_list(existing_refs))
    return f"turn-{ref_count + 1}"


def _first_non_empty(*values: str) -> str:
    for value in values:
        normalized = _normalize_text(value)
        if normalized:
            return normalized
    return ""


def _merge_unique_strings(existing_values: list[str], new_values: list[str]) -> list[str]:
    merged = _normalize_string_list(existing_values)
    for value in _normalize_string_list(new_values):
        if value not in merged:
            merged.append(value)
    return merged


def _normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized_values: list[str] = []
    for item in value:
        normalized_item = _normalize_text(item)
        if normalized_item and normalized_item not in normalized_values:
            normalized_values.append(normalized_item)
    return normalized_values


def _normalize_seed_entry(value: str) -> str:
    normalized = _normalize_text(value).strip("`")
    if not normalized:
        return ""
    if normalized.startswith("@"):
        return normalized.lower()
    if re.match(r"^(?:https?://)?t\.me/", normalized, re.IGNORECASE):
        lowered = normalized.lower()
        if lowered.startswith("http://") or lowered.startswith("https://"):
            return lowered.replace("http://", "https://", 1)
        return f"https://{lowered}"
    return ""


def _split_list_like_text(value: str) -> list[str]:
    parts = re.split(r",|;|\band\b", value)
    return [item for item in (_normalize_text(part) for part in parts) if item]


def _split_sentences(value: str) -> list[str]:
    return [item for item in (_normalize_text(part) for part in re.split(r"[.!?\n]+", value)) if item]


def _extract_phrase_after_keyword(
    message: str,
    *,
    keyword: str,
    stop_keywords: tuple[str, ...],
) -> str:
    lower_message = message.lower()
    marker = f"{keyword.lower()} "
    start_index = lower_message.find(marker)
    if start_index == -1:
        return ""

    value_start = start_index + len(marker)
    raw_tail = message[value_start:].strip()
    lower_tail = raw_tail.lower()
    end_index = len(raw_tail)
    for marker_text in [*(f" {stop_keyword.lower()} " for stop_keyword in stop_keywords), ".", ",", ";", "\n"]:
        marker_index = lower_tail.find(marker_text) if marker_text.startswith(" ") else raw_tail.find(marker_text)
        if marker_index != -1:
            end_index = min(end_index, marker_index)
    return _normalize_text(raw_tail[:end_index])


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _normalize_target_phrase(value: Any) -> str:
    return _normalize_text(value).strip("`").rstrip(".,;)")
