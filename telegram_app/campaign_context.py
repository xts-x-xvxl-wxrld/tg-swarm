"""Helpers for promoting durable operator nuance into campaign context."""

from __future__ import annotations

from datetime import UTC, datetime
import re
from typing import Any

from telegram_app.models import SessionRecord, WorkflowArtifact, WorkflowArtifactKind

CAMPAIGN_CONTEXT_TITLE = "Campaign context profile"

OPERATOR_PREFERENCES_KEY = "operator_preferences"
VOICE_PROFILE_KEY = "voice_profile"
VOICE_PREFERRED_TRAITS_KEY = "preferred_traits"
VOICE_AVOID_TRAITS_KEY = "avoid_traits"
VOICE_STYLE_NOTES_KEY = "style_notes"
VOICE_CTA_PREFERENCES_KEY = "cta_preferences"
EXECUTION_CONSTRAINTS_KEY = "execution_constraints"
PERSISTENT_DECISIONS_KEY = "persistent_decisions"
OPEN_AMBIGUITIES_KEY = "open_ambiguities"
REVISION_THREADS_KEY = "revision_threads"

SCOPE_KEY = "scope"
STATUS_KEY = "status"
SUMMARY_KEY = "summary"
REQUESTED_CHANGES_KEY = "requested_changes"
PRESERVE_KEY = "preserve"
OPEN_QUESTIONS_KEY = "open_questions"
UPDATED_AT_KEY = "updated_at"
SOURCE_MESSAGE_REFS_KEY = "source_message_refs"

REVISION_STATUS_ACTIVE = "active"
REVISION_STATUS_ACCEPTED = "accepted"
REVISION_STATUS_SUPERSEDED = "superseded"

_VOICE_LABEL_PATTERN = re.compile(r"(?im)^(?:tone|voice|style)\s*:\s*(?P<value>.+)$")
_PREFERENCES_LABEL_PATTERN = re.compile(r"(?im)^(?:preferences?|operator preferences?)\s*:\s*(?P<value>.+)$")
_CTA_LABEL_PATTERN = re.compile(r"(?im)^cta\s*:\s*(?P<value>.+)$")
_CONSTRAINTS_LABEL_PATTERN = re.compile(r"(?im)^(?:constraints?|guardrails?)\s*:\s*(?P<value>.+)$")
_DECISIONS_LABEL_PATTERN = re.compile(r"(?im)^(?:decision|decisions)\s*:\s*(?P<value>.+)$")
_QUESTIONS_LABEL_PATTERN = re.compile(r"(?im)^(?:question|questions|ambiguity|ambiguities)\s*:\s*(?P<value>.+)$")

_VOICE_KEYWORDS = ("tone", "voice", "style", "sound", "messaging", "copy", "cta", "hook", "angle")
_CONSTRAINT_KEYWORDS = (
    "avoid",
    "do not",
    "don't",
    "must",
    "must not",
    "never",
    "only",
    "at least",
    "no ",
    "senior account",
    "pacing",
    "schedule",
    "community",
    "dm",
    "post",
)
_PREFERENCE_CUES = ("prefer", "please", "want", "would like", "keep it", "make it", "let's keep")
_DECISION_CUES = ("we're focusing", "we are focusing", "go with", "stick with", "let's focus on")
_PRESERVE_CUES = ("keep ", "preserve ", "maintain ", "don't change", "do not change", "still keep")


def default_campaign_context_data() -> dict[str, Any]:
    """Return the default durable shape for promoted operator nuance."""
    return {
        OPERATOR_PREFERENCES_KEY: [],
        VOICE_PROFILE_KEY: {
            VOICE_PREFERRED_TRAITS_KEY: [],
            VOICE_AVOID_TRAITS_KEY: [],
            VOICE_STYLE_NOTES_KEY: [],
            VOICE_CTA_PREFERENCES_KEY: [],
        },
        EXECUTION_CONSTRAINTS_KEY: [],
        PERSISTENT_DECISIONS_KEY: [],
        OPEN_AMBIGUITIES_KEY: [],
        REVISION_THREADS_KEY: [],
    }


def get_campaign_context_artifact(session: SessionRecord) -> WorkflowArtifact | None:
    """Return the latest campaign-context artifact saved in session state."""
    artifacts = _load_workflow_artifacts(session)
    matches = [artifact for artifact in artifacts if artifact.kind is WorkflowArtifactKind.CAMPAIGN_CONTEXT]
    if not matches:
        return None
    return max(matches, key=lambda artifact: artifact.updated_at)


def merge_campaign_context_data(
    existing_data: dict[str, Any] | None,
    *,
    message: str,
    source_message_id: str = "",
) -> dict[str, Any]:
    """Promote stable cross-turn nuance from one operator message."""
    context = _normalize_campaign_context_data(existing_data)
    normalized_message = _normalize_text(message)
    if not normalized_message:
        return context

    context[OPERATOR_PREFERENCES_KEY] = _merge_unique_strings(
        context.get(OPERATOR_PREFERENCES_KEY, []),
        [*_extract_labeled_values(_PREFERENCES_LABEL_PATTERN, message), *_extract_operator_preferences(message)],
        limit=12,
    )

    voice_profile = context[VOICE_PROFILE_KEY]
    preferred_traits, avoid_traits, style_notes, cta_preferences = _extract_voice_guidance(message)
    voice_profile[VOICE_PREFERRED_TRAITS_KEY] = _merge_unique_strings(
        voice_profile.get(VOICE_PREFERRED_TRAITS_KEY, []),
        preferred_traits,
        limit=12,
    )
    voice_profile[VOICE_AVOID_TRAITS_KEY] = _merge_unique_strings(
        voice_profile.get(VOICE_AVOID_TRAITS_KEY, []),
        avoid_traits,
        limit=12,
    )
    voice_profile[VOICE_STYLE_NOTES_KEY] = _merge_unique_strings(
        voice_profile.get(VOICE_STYLE_NOTES_KEY, []),
        style_notes,
        limit=12,
    )
    voice_profile[VOICE_CTA_PREFERENCES_KEY] = _merge_unique_strings(
        voice_profile.get(VOICE_CTA_PREFERENCES_KEY, []),
        cta_preferences,
        limit=8,
    )

    context[EXECUTION_CONSTRAINTS_KEY] = _merge_unique_strings(
        context.get(EXECUTION_CONSTRAINTS_KEY, []),
        _extract_execution_constraints(message),
        limit=16,
    )
    context[PERSISTENT_DECISIONS_KEY] = _merge_unique_strings(
        context.get(PERSISTENT_DECISIONS_KEY, []),
        _extract_persistent_decisions(message),
        limit=16,
    )
    context[OPEN_AMBIGUITIES_KEY] = _merge_unique_strings(
        context.get(OPEN_AMBIGUITIES_KEY, []),
        _extract_open_ambiguities(message),
        limit=12,
    )
    return context


def promote_campaign_context_revision(
    existing_data: dict[str, Any] | None,
    *,
    scope: str,
    message: str,
    source_message_id: str = "",
) -> dict[str, Any]:
    """Promote one review-time revision request into durable structured context."""
    context = merge_campaign_context_data(
        existing_data,
        message=message,
        source_message_id=source_message_id,
    )
    normalized_scope = _normalize_text(scope)
    normalized_message = _normalize_text(message)
    if not normalized_scope or not normalized_message:
        return context

    revision_threads = _normalize_revision_threads(context.get(REVISION_THREADS_KEY, []))
    for revision in revision_threads:
        if revision[SCOPE_KEY] == normalized_scope and revision[STATUS_KEY] == REVISION_STATUS_ACTIVE:
            revision[STATUS_KEY] = REVISION_STATUS_SUPERSEDED
            revision[UPDATED_AT_KEY] = _now_iso()

    requested_changes, preserve_lines = _extract_revision_parts(message)
    open_questions = _extract_open_ambiguities(message)
    revision_threads.append(
        {
            SCOPE_KEY: normalized_scope,
            STATUS_KEY: REVISION_STATUS_ACTIVE,
            SUMMARY_KEY: normalized_message,
            REQUESTED_CHANGES_KEY: requested_changes or [normalized_message],
            PRESERVE_KEY: preserve_lines,
            OPEN_QUESTIONS_KEY: open_questions,
            UPDATED_AT_KEY: _now_iso(),
            SOURCE_MESSAGE_REFS_KEY: [_build_source_message_ref(source_message_id)],
        }
    )
    context[REVISION_THREADS_KEY] = revision_threads[-8:]
    return context


def resolve_campaign_context_revision(
    existing_data: dict[str, Any] | None,
    *,
    scope: str,
    accepted: bool,
) -> dict[str, Any]:
    """Resolve the latest active revision for one scope."""
    context = _normalize_campaign_context_data(existing_data)
    normalized_scope = _normalize_text(scope)
    if not normalized_scope:
        return context

    revision_threads = _normalize_revision_threads(context.get(REVISION_THREADS_KEY, []))
    target_revision: dict[str, Any] | None = None
    for revision in reversed(revision_threads):
        if revision[SCOPE_KEY] != normalized_scope or revision[STATUS_KEY] != REVISION_STATUS_ACTIVE:
            continue
        target_revision = revision
        break
    if target_revision is None:
        return context

    target_revision[STATUS_KEY] = REVISION_STATUS_ACCEPTED if accepted else REVISION_STATUS_SUPERSEDED
    target_revision[UPDATED_AT_KEY] = _now_iso()
    if accepted:
        promoted_decisions = [
            f"{normalized_scope}: {line}"
            for line in [*target_revision[REQUESTED_CHANGES_KEY], *target_revision[PRESERVE_KEY]]
            if _normalize_text(line)
        ]
        if not promoted_decisions:
            promoted_decisions = [f"{normalized_scope}: {target_revision[SUMMARY_KEY]}"]
        context[PERSISTENT_DECISIONS_KEY] = _merge_unique_strings(
            context.get(PERSISTENT_DECISIONS_KEY, []),
            promoted_decisions,
            limit=16,
        )
    context[REVISION_THREADS_KEY] = revision_threads[-8:]
    return context


def prompt_safe_campaign_context_data(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Return a compact prompt-safe view of promoted operator nuance."""
    context = _normalize_campaign_context_data(payload)
    revisions = _normalize_revision_threads(context.get(REVISION_THREADS_KEY, []))
    active_revisions = [
        _compact_revision(revision)
        for revision in revisions
        if revision[STATUS_KEY] == REVISION_STATUS_ACTIVE
    ][-2:]
    accepted_revisions = _latest_accepted_revisions(revisions)

    compact_payload = {
        OPERATOR_PREFERENCES_KEY: context.get(OPERATOR_PREFERENCES_KEY, [])[-6:],
        VOICE_PROFILE_KEY: {
            VOICE_PREFERRED_TRAITS_KEY: context[VOICE_PROFILE_KEY][VOICE_PREFERRED_TRAITS_KEY][-6:],
            VOICE_AVOID_TRAITS_KEY: context[VOICE_PROFILE_KEY][VOICE_AVOID_TRAITS_KEY][-6:],
            VOICE_STYLE_NOTES_KEY: context[VOICE_PROFILE_KEY][VOICE_STYLE_NOTES_KEY][-6:],
            VOICE_CTA_PREFERENCES_KEY: context[VOICE_PROFILE_KEY][VOICE_CTA_PREFERENCES_KEY][-4:],
        },
        EXECUTION_CONSTRAINTS_KEY: context.get(EXECUTION_CONSTRAINTS_KEY, [])[-8:],
        PERSISTENT_DECISIONS_KEY: context.get(PERSISTENT_DECISIONS_KEY, [])[-8:],
        OPEN_AMBIGUITIES_KEY: context.get(OPEN_AMBIGUITIES_KEY, [])[-6:],
        "active_revisions": active_revisions,
        "accepted_revisions": accepted_revisions,
    }
    return {
        key: value
        for key, value in compact_payload.items()
        if value not in ("", [], {}, None)
    }


def build_campaign_context_summary(payload: dict[str, Any] | None) -> str:
    """Return a compact operator-facing summary of the current campaign context."""
    context = _normalize_campaign_context_data(payload)
    revisions = _normalize_revision_threads(context.get(REVISION_THREADS_KEY, []))
    active_revision_count = sum(1 for revision in revisions if revision[STATUS_KEY] == REVISION_STATUS_ACTIVE)
    parts: list[str] = []
    if context.get(OPERATOR_PREFERENCES_KEY):
        parts.append(f"{len(context[OPERATOR_PREFERENCES_KEY])} operator preferences")
    preferred_traits = context[VOICE_PROFILE_KEY][VOICE_PREFERRED_TRAITS_KEY]
    if preferred_traits:
        parts.append(f"{len(preferred_traits)} voice preferences")
    if context.get(EXECUTION_CONSTRAINTS_KEY):
        parts.append(f"{len(context[EXECUTION_CONSTRAINTS_KEY])} execution constraints")
    if context.get(PERSISTENT_DECISIONS_KEY):
        parts.append(f"{len(context[PERSISTENT_DECISIONS_KEY])} persistent decisions")
    if context.get(OPEN_AMBIGUITIES_KEY):
        parts.append(f"{len(context[OPEN_AMBIGUITIES_KEY])} open ambiguities")
    if active_revision_count:
        parts.append(f"{active_revision_count} active revisions")
    if not parts:
        return "No durable campaign-context guidance has been promoted yet."
    return "Campaign context tracks " + ", ".join(parts) + "."


def _load_workflow_artifacts(session: SessionRecord) -> list[WorkflowArtifact]:
    payloads = session.workflow_state.get("workflow_artifacts", [])
    if not isinstance(payloads, list):
        return []
    return [
        WorkflowArtifact.from_dict(payload)
        for payload in payloads
        if isinstance(payload, dict)
    ]


def _normalize_campaign_context_data(payload: dict[str, Any] | None) -> dict[str, Any]:
    base = default_campaign_context_data()
    if not isinstance(payload, dict):
        return base

    base[OPERATOR_PREFERENCES_KEY] = _normalize_string_list(payload.get(OPERATOR_PREFERENCES_KEY, []))
    base[EXECUTION_CONSTRAINTS_KEY] = _normalize_string_list(payload.get(EXECUTION_CONSTRAINTS_KEY, []))
    base[PERSISTENT_DECISIONS_KEY] = _normalize_string_list(payload.get(PERSISTENT_DECISIONS_KEY, []))
    base[OPEN_AMBIGUITIES_KEY] = _normalize_string_list(payload.get(OPEN_AMBIGUITIES_KEY, []))

    voice_profile = payload.get(VOICE_PROFILE_KEY, {})
    if isinstance(voice_profile, dict):
        base[VOICE_PROFILE_KEY] = {
            VOICE_PREFERRED_TRAITS_KEY: _normalize_string_list(voice_profile.get(VOICE_PREFERRED_TRAITS_KEY, [])),
            VOICE_AVOID_TRAITS_KEY: _normalize_string_list(voice_profile.get(VOICE_AVOID_TRAITS_KEY, [])),
            VOICE_STYLE_NOTES_KEY: _normalize_string_list(voice_profile.get(VOICE_STYLE_NOTES_KEY, [])),
            VOICE_CTA_PREFERENCES_KEY: _normalize_string_list(voice_profile.get(VOICE_CTA_PREFERENCES_KEY, [])),
        }

    base[REVISION_THREADS_KEY] = _normalize_revision_threads(payload.get(REVISION_THREADS_KEY, []))
    return base


def _normalize_revision_threads(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    revisions: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        scope = _normalize_text(item.get(SCOPE_KEY, ""))
        status = _normalize_text(item.get(STATUS_KEY, "")) or REVISION_STATUS_ACTIVE
        summary = _normalize_text(item.get(SUMMARY_KEY, ""))
        if not scope or not summary:
            continue
        revisions.append(
            {
                SCOPE_KEY: scope,
                STATUS_KEY: status,
                SUMMARY_KEY: summary,
                REQUESTED_CHANGES_KEY: _normalize_string_list(item.get(REQUESTED_CHANGES_KEY, [])),
                PRESERVE_KEY: _normalize_string_list(item.get(PRESERVE_KEY, [])),
                OPEN_QUESTIONS_KEY: _normalize_string_list(item.get(OPEN_QUESTIONS_KEY, [])),
                UPDATED_AT_KEY: _normalize_text(item.get(UPDATED_AT_KEY, "")),
                SOURCE_MESSAGE_REFS_KEY: _normalize_string_list(item.get(SOURCE_MESSAGE_REFS_KEY, [])),
            }
        )
    return revisions


def _extract_operator_preferences(message: str) -> list[str]:
    clauses = _message_clauses(message)
    return [
        clause
        for clause in clauses
        if any(cue in clause.lower() for cue in _PREFERENCE_CUES)
        and not any(keyword in clause.lower() for keyword in _VOICE_KEYWORDS)
    ]


def _extract_voice_guidance(message: str) -> tuple[list[str], list[str], list[str], list[str]]:
    preferred_traits: list[str] = []
    avoid_traits: list[str] = []
    style_notes: list[str] = []
    cta_preferences: list[str] = _extract_labeled_values(_CTA_LABEL_PATTERN, message)

    for labeled_voice in _extract_labeled_values(_VOICE_LABEL_PATTERN, message):
        for item in _split_list_items(labeled_voice):
            if _contains_negative_cue(item):
                avoid_traits.append(item)
            else:
                preferred_traits.append(item)

    for clause in _message_clauses(message):
        lowered = clause.lower()
        if not any(keyword in lowered for keyword in _VOICE_KEYWORDS):
            continue
        if "cta" in lowered:
            cta_preferences.append(clause)
            continue
        split_clause_items = _split_list_items(clause)
        if _contains_negative_cue(clause):
            avoid_traits.extend([item for item in split_clause_items if _contains_negative_cue(item)])
            preferred_traits.extend([item for item in split_clause_items if not _contains_negative_cue(item)])
            continue
        if any(cue in lowered for cue in _PRESERVE_CUES) or any(cue in lowered for cue in _PREFERENCE_CUES):
            preferred_traits.extend(split_clause_items or [clause])
            continue
        style_notes.append(clause)

    return (
        _normalize_string_list(preferred_traits),
        _normalize_string_list(avoid_traits),
        _normalize_string_list(style_notes),
        _normalize_string_list(cta_preferences),
    )


def _extract_execution_constraints(message: str) -> list[str]:
    explicit_constraints = _extract_labeled_values(_CONSTRAINTS_LABEL_PATTERN, message)
    clauses = _message_clauses(message)
    inferred_constraints = [
        clause
        for clause in clauses
        if any(keyword in clause.lower() for keyword in _CONSTRAINT_KEYWORDS)
        and not any(keyword in clause.lower() for keyword in _VOICE_KEYWORDS)
    ]
    return _normalize_string_list([*explicit_constraints, *inferred_constraints])


def _extract_persistent_decisions(message: str) -> list[str]:
    explicit_decisions = _extract_labeled_values(_DECISIONS_LABEL_PATTERN, message)
    inferred_decisions = [
        clause
        for clause in _message_clauses(message)
        if any(cue in clause.lower() for cue in _DECISION_CUES)
    ]
    return _normalize_string_list([*explicit_decisions, *inferred_decisions])


def _extract_open_ambiguities(message: str) -> list[str]:
    explicit_questions = _extract_labeled_values(_QUESTIONS_LABEL_PATTERN, message)
    inferred_questions = [
        clause
        for clause in _message_clauses(message)
        if clause.endswith("?") or any(
            cue in clause.lower()
            for cue in ("unclear", "not sure", "question", "decide whether", "either", "or should")
        )
    ]
    return _normalize_string_list([*explicit_questions, *inferred_questions])


def _extract_revision_parts(message: str) -> tuple[list[str], list[str]]:
    requested_changes: list[str] = []
    preserve_lines: list[str] = []
    for clause in _revision_clauses(message):
        lowered = clause.lower()
        if any(cue in lowered for cue in _PRESERVE_CUES):
            preserve_lines.append(clause)
            continue
        if clause.endswith("?"):
            continue
        requested_changes.append(clause)
    return _normalize_string_list(requested_changes), _normalize_string_list(preserve_lines)


def _compact_revision(revision: dict[str, Any]) -> dict[str, Any]:
    compact_payload = {
        SCOPE_KEY: revision[SCOPE_KEY],
        STATUS_KEY: revision[STATUS_KEY],
        SUMMARY_KEY: revision[SUMMARY_KEY],
        REQUESTED_CHANGES_KEY: revision[REQUESTED_CHANGES_KEY][:4],
        PRESERVE_KEY: revision[PRESERVE_KEY][:4],
        OPEN_QUESTIONS_KEY: revision[OPEN_QUESTIONS_KEY][:3],
    }
    return {
        key: value
        for key, value in compact_payload.items()
        if value not in ("", [], {}, None)
    }


def _latest_accepted_revisions(revisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest_by_scope: dict[str, dict[str, Any]] = {}
    for revision in revisions:
        if revision[STATUS_KEY] != REVISION_STATUS_ACCEPTED:
            continue
        latest_by_scope[revision[SCOPE_KEY]] = revision
    return [_compact_revision(revision) for revision in latest_by_scope.values()][-3:]


def _extract_labeled_values(pattern: re.Pattern[str], message: str) -> list[str]:
    values: list[str] = []
    for match in pattern.finditer(message):
        values.extend(_split_list_items(match.group("value")))
    return _normalize_string_list(values)


def _message_clauses(message: str) -> list[str]:
    raw_parts = re.split(r"[\n;]+", message)
    clauses: list[str] = []
    for raw_part in raw_parts:
        part = _normalize_text(raw_part)
        if not part:
            continue
        if any(pattern.match(part) for pattern in (
            _VOICE_LABEL_PATTERN,
            _PREFERENCES_LABEL_PATTERN,
            _CTA_LABEL_PATTERN,
            _CONSTRAINTS_LABEL_PATTERN,
            _DECISIONS_LABEL_PATTERN,
            _QUESTIONS_LABEL_PATTERN,
        )):
            continue
        clauses.append(part)
    return clauses


def _revision_clauses(message: str) -> list[str]:
    clauses: list[str] = []
    for raw_part in re.split(r"[\n;]+|\band\b", message):
        part = _normalize_text(raw_part)
        if part:
            clauses.append(part)
    return clauses


def _split_list_items(value: str) -> list[str]:
    parts = re.split(r",|;|\band\b", value)
    return [item for item in (_normalize_text(part) for part in parts) if item]


def _merge_unique_strings(existing_values: list[str], new_values: list[str], *, limit: int) -> list[str]:
    merged = _normalize_string_list(existing_values)
    for value in _normalize_string_list(new_values):
        if value not in merged:
            merged.append(value)
    return merged[-limit:]


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


def _contains_negative_cue(value: str) -> bool:
    lowered = value.lower()
    return any(cue in lowered for cue in ("avoid", "not ", "don't", "do not", "never", "less "))


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _build_source_message_ref(source_message_id: str) -> str:
    return _normalize_text(source_message_id) or "operator-turn"
