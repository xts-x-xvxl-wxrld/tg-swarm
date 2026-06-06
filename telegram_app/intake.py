"""Structured intake helpers for turning operator turns into reusable workflow state."""

from __future__ import annotations

import re
from typing import Any

from telegram_app.campaign_intent import (
    AMBIGUITIES_KEY as INTENT_AMBIGUITIES_KEY,
    ASSET_REFS_KEY as INTENT_ASSET_REFS_KEY,
    CAMPAIGN_CONSTRAINTS_KEY as INTENT_CAMPAIGN_CONSTRAINTS_KEY,
    CONVERSION_TARGET_SIGNAL_KEY,
    RAW_VALUE_KEY as INTENT_RAW_VALUE_KEY,
    SEED_INPUTS_KEY,
    SOURCE_MESSAGE_REFS_KEY,
    build_campaign_brief_from_intent,
    build_campaign_intent_summary,
    merge_campaign_intent_data,
)
from telegram_app.campaign_context import (
    CAMPAIGN_CONTEXT_TITLE,
    build_campaign_context_summary,
    get_campaign_context_artifact,
    merge_campaign_context_data,
)
from telegram_app.conversion_target import (
    DESTINATION_KIND_KEY as CONVERSION_DESTINATION_KIND_KEY,
    NORMALIZED_VALUE_KEY as CONVERSION_NORMALIZED_VALUE_KEY,
    RAW_VALUE_KEY as CONVERSION_RAW_VALUE_KEY,
    build_conversion_target_data,
    build_conversion_target_summary,
)
from telegram_app.campaign_setup import (
    derive_campaign_setup_state,
    get_campaign_setup_state,
    is_explicit_discovery_start_message,
    is_low_signal_setup_acknowledgement,
    save_campaign_setup_state,
    setup_is_ready_for_confirmation,
)
from telegram_app.models import (
    ApprovalRecord,
    SessionRecord,
    WorkflowArtifact,
    WorkflowArtifactKind,
    WorkflowSnapshot,
    WorkflowStage,
)
from telegram_app.sessions import SessionManager

OBJECTIVE_KEY = "objective"
TARGET_AUDIENCE_KEY = "target_audience"
OFFER_KEY = "offer"
GEOGRAPHY_KEY = "geography"
LANGUAGE_KEY = "language"
CONSTRAINTS_KEY = "constraints"
SUCCESS_CRITERIA_KEY = "success_criteria"
SEED_TARGET_GROUPS_KEY = "seed_target_groups"
NOTES_KEY = "notes"
SOURCE_MESSAGES_KEY = "source_messages"

CAMPAIGN_INTENT_TITLE = "Campaign intent package"
CONVERSION_TARGET_TITLE = "Conversion target"
CAMPAIGN_BRIEF_TITLE = "Campaign brief"
READY_FIELDS = (OBJECTIVE_KEY, TARGET_AUDIENCE_KEY)
LABELED_FIELD_ALIASES = {
    OBJECTIVE_KEY: ("goal", "objective", "campaign", "task"),
    TARGET_AUDIENCE_KEY: ("audience", "target audience", "icp"),
    OFFER_KEY: ("offer", "product", "service"),
    GEOGRAPHY_KEY: ("geography", "region", "location", "country", "market"),
    LANGUAGE_KEY: ("language", "languages"),
    CONSTRAINTS_KEY: ("constraint", "constraints", "rules", "guardrails"),
    SUCCESS_CRITERIA_KEY: ("success", "success criteria", "kpi", "kpis"),
    SEED_TARGET_GROUPS_KEY: ("seed groups", "seed group", "target groups", "target group", "seed communities"),
}
STOPWORDS = (".", ",", ";")


class StructuredIntakeCoordinator:
    """Maintains a structured campaign brief and workflow snapshot for a session."""

    def __init__(self, session_manager: SessionManager) -> None:
        self._session_manager = session_manager

    def ingest_operator_turn(
        self,
        session: SessionRecord,
        message: str,
        pending_approval: ApprovalRecord | None = None,
        source_message_id: str = "",
    ) -> None:
        """Update structured intake state before the orchestrator processes the turn."""
        if pending_approval is not None:
            return

        current_snapshot = get_workflow_snapshot(session)
        if current_snapshot.stage is not WorkflowStage.INTAKE:
            return

        normalized_message = message.strip()
        if not normalized_message:
            return

        low_signal_acknowledgement = is_low_signal_setup_acknowledgement(normalized_message)
        field_updates, _explicit_fields = _extract_field_updates(normalized_message)
        if campaign_has_started(session) and low_signal_acknowledgement:
            field_updates = {}
        has_structured_updates = _has_non_note_field_updates(field_updates)
        existing_setup_state = get_campaign_setup_state(session)
        campaign_intent = get_campaign_intent_artifact(session)
        campaign_context = get_campaign_context_artifact(session)
        campaign_brief = get_campaign_brief_artifact(session)
        if (
            campaign_brief is None
            and campaign_intent is None
            and not has_structured_updates
            and low_signal_acknowledgement
        ):
            return

        if campaign_intent is None:
            campaign_intent = self._session_manager.create_workflow_artifact(
                session=session,
                kind=WorkflowArtifactKind.CAMPAIGN_INTENT,
                title=CAMPAIGN_INTENT_TITLE,
                summary="Campaign intent package started from operator input.",
                data={},
            )

        if campaign_brief is None:
            campaign_brief = self._session_manager.create_workflow_artifact(
                session=session,
                kind=WorkflowArtifactKind.CAMPAIGN_BRIEF,
                title=CAMPAIGN_BRIEF_TITLE,
                summary="Campaign brief started from operator input.",
                data=_default_campaign_brief_data(),
            )

        if campaign_context is None:
            campaign_context = self._session_manager.create_workflow_artifact(
                session=session,
                kind=WorkflowArtifactKind.CAMPAIGN_CONTEXT,
                title=CAMPAIGN_CONTEXT_TITLE,
                summary="Campaign context promotion has not captured durable nuance yet.",
                data={},
            )

        if has_structured_updates or not low_signal_acknowledgement:
            campaign_intent.data = merge_campaign_intent_data(
                campaign_intent.data,
                message=normalized_message,
                source_message_id=source_message_id,
                field_updates=field_updates,
                setup_state=existing_setup_state,
            )
            campaign_brief.data = build_campaign_brief_from_intent(
                campaign_intent.data,
                existing_brief=campaign_brief.data,
                field_updates=field_updates,
                message=normalized_message,
            )
            campaign_context.data = merge_campaign_context_data(
                campaign_context.data,
                message=normalized_message,
                source_message_id=source_message_id,
            )
        campaign_intent.summary = build_campaign_intent_summary(campaign_intent.data)
        self._session_manager.save_workflow_artifact(session, campaign_intent)
        campaign_context.summary = build_campaign_context_summary(campaign_context.data)
        self._session_manager.save_workflow_artifact(session, campaign_context)

        conversion_target = get_conversion_target_artifact(session)
        conversion_target_data = build_conversion_target_data(
            campaign_intent.data,
            existing_data=conversion_target.data if conversion_target is not None else None,
        )
        if conversion_target_data:
            if conversion_target is None:
                conversion_target = self._session_manager.create_workflow_artifact(
                    session=session,
                    kind=WorkflowArtifactKind.CONVERSION_TARGET,
                    title=CONVERSION_TARGET_TITLE,
                    summary="Conversion target inferred from operator input.",
                    data=conversion_target_data,
                )
            conversion_target.data = conversion_target_data
            conversion_target.summary = build_conversion_target_summary(conversion_target.data)
            self._session_manager.save_workflow_artifact(session, conversion_target)

        campaign_brief.summary = _build_campaign_brief_summary(campaign_brief.data)
        self._session_manager.save_workflow_artifact(session, campaign_brief)

        setup_state = derive_campaign_setup_state(
            campaign_brief.data,
            intent_data=campaign_intent.data,
            existing_state=existing_setup_state,
        )
        if setup_is_ready_for_confirmation(setup_state) and is_explicit_discovery_start_message(normalized_message):
            setup_state = derive_campaign_setup_state(
                campaign_brief.data,
                intent_data=campaign_intent.data,
                existing_state=setup_state,
                confirmed=True,
            )
        save_campaign_setup_state(session, setup_state)

        snapshot = _build_snapshot_from_campaign_brief(
            campaign_brief,
            campaign_intent=campaign_intent,
            conversion_target=conversion_target,
            setup_state=setup_state,
        )
        self._session_manager.replace_workflow_snapshot(session, snapshot)


def get_campaign_intent_artifact(session: SessionRecord) -> WorkflowArtifact | None:
    """Return the latest campaign intent artifact saved in session state."""
    return _get_latest_workflow_artifact(session, WorkflowArtifactKind.CAMPAIGN_INTENT)


def get_campaign_brief_artifact(session: SessionRecord) -> WorkflowArtifact | None:
    """Return the latest campaign brief artifact saved in session state."""
    return _get_latest_workflow_artifact(session, WorkflowArtifactKind.CAMPAIGN_BRIEF)


def get_conversion_target_artifact(session: SessionRecord) -> WorkflowArtifact | None:
    """Return the latest conversion-target artifact saved in session state."""
    return _get_latest_workflow_artifact(session, WorkflowArtifactKind.CONVERSION_TARGET)


def get_workflow_snapshot(session: SessionRecord) -> WorkflowSnapshot:
    """Return the current workflow snapshot stored in session state."""
    payload = session.workflow_state.get("workflow_snapshot", {})
    if not isinstance(payload, dict):
        payload = {}
    return WorkflowSnapshot.from_dict(payload)


def _load_workflow_artifacts(session: SessionRecord) -> list[WorkflowArtifact]:
    payloads = session.workflow_state.get("workflow_artifacts", [])
    if not isinstance(payloads, list):
        return []
    return [
        WorkflowArtifact.from_dict(payload)
        for payload in payloads
        if isinstance(payload, dict)
    ]


def campaign_has_started(session: SessionRecord) -> bool:
    """Return true when any intake artifact already exists for the session."""
    return get_campaign_intent_artifact(session) is not None or get_campaign_brief_artifact(session) is not None


def _get_latest_workflow_artifact(
    session: SessionRecord,
    kind: WorkflowArtifactKind,
) -> WorkflowArtifact | None:
    artifacts = [artifact for artifact in _load_workflow_artifacts(session) if artifact.kind is kind]
    if not artifacts:
        return None
    return max(artifacts, key=lambda artifact: artifact.updated_at)


def _default_campaign_brief_data() -> dict[str, Any]:
    return {
        OBJECTIVE_KEY: "",
        TARGET_AUDIENCE_KEY: "",
        OFFER_KEY: "",
        GEOGRAPHY_KEY: "",
        LANGUAGE_KEY: "",
        CONSTRAINTS_KEY: [],
        SUCCESS_CRITERIA_KEY: [],
        SEED_TARGET_GROUPS_KEY: [],
        NOTES_KEY: [],
        SOURCE_MESSAGES_KEY: [],
    }


def _merge_campaign_brief_data(
    existing_data: dict[str, Any],
    message: str,
    *,
    field_updates: dict[str, Any] | None = None,
    explicit_fields: set[str] | None = None,
) -> dict[str, Any]:
    brief_data = _default_campaign_brief_data()
    brief_data.update(
        {
            key: value
            for key, value in existing_data.items()
            if key in brief_data
        }
    )

    field_updates = field_updates or {}
    explicit_fields = explicit_fields or set()
    for key, value in field_updates.items():
        if key in (
            CONSTRAINTS_KEY,
            SUCCESS_CRITERIA_KEY,
            SEED_TARGET_GROUPS_KEY,
            NOTES_KEY,
            SOURCE_MESSAGES_KEY,
        ):
            brief_data[key] = _merge_unique_strings(brief_data.get(key, []), value)
        elif key in explicit_fields and value:
            brief_data[key] = value
        elif value and not brief_data.get(key):
            brief_data[key] = value

    if not field_updates.get(OBJECTIVE_KEY):
        if not brief_data[OBJECTIVE_KEY]:
            brief_data[OBJECTIVE_KEY] = message
        else:
            brief_data[NOTES_KEY] = _merge_unique_strings(brief_data[NOTES_KEY], [message])

    brief_data[SOURCE_MESSAGES_KEY] = _merge_unique_strings(
        brief_data[SOURCE_MESSAGES_KEY],
        [message],
    )
    return brief_data


def _extract_field_updates(message: str) -> tuple[dict[str, Any], set[str]]:
    updates: dict[str, Any] = {}
    explicit_fields: set[str] = set()
    remaining_segments: list[str] = []
    labeled_lines = _extract_labeled_lines(message)

    for field_name, aliases in LABELED_FIELD_ALIASES.items():
        extracted_value = _extract_labeled_value(labeled_lines, aliases)
        if not extracted_value:
            continue
        explicit_fields.add(field_name)

        if field_name in (CONSTRAINTS_KEY, SUCCESS_CRITERIA_KEY):
            updates[field_name] = _split_list_items(extracted_value)
        elif field_name == SEED_TARGET_GROUPS_KEY:
            updates[field_name] = _split_list_items(extracted_value)
        else:
            updates[field_name] = extracted_value

    if not labeled_lines:
        if OBJECTIVE_KEY not in updates:
            inferred_objective = _infer_objective(message)
            if inferred_objective:
                updates[OBJECTIVE_KEY] = inferred_objective

        if TARGET_AUDIENCE_KEY not in updates:
            inferred_audience = _infer_target_audience(message)
            if inferred_audience:
                updates[TARGET_AUDIENCE_KEY] = inferred_audience

        if GEOGRAPHY_KEY not in updates:
            inferred_geography = _infer_geography(message)
            if inferred_geography:
                updates[GEOGRAPHY_KEY] = inferred_geography

    if explicit_fields:
        remaining_segments.extend(_extract_unlabeled_segments(message))
    else:
        remaining_segments.extend(
            line
            for line in message.splitlines()
            if not _is_labeled_line(line)
        )
    extra_note = _normalize_text(" ".join(remaining_segments))
    if extra_note and extra_note != updates.get(OBJECTIVE_KEY):
        updates[NOTES_KEY] = [extra_note]

    return updates, explicit_fields


def _extract_labeled_lines(message: str) -> dict[str, str]:
    labeled_lines: dict[str, str] = {}
    for match in _labeled_field_pattern().finditer(message):
        label = match.group("label").strip().lower()
        value = _normalize_text(match.group("value"))
        if value:
            labeled_lines[label] = value
    return labeled_lines


def _extract_labeled_value(labeled_lines: dict[str, str], aliases: tuple[str, ...]) -> str:
    for alias in aliases:
        value = labeled_lines.get(alias.lower(), "")
        if value:
            return value
    return ""


def _infer_objective(message: str) -> str:
    first_line = message.splitlines()[0]
    return _normalize_text(first_line)


def _infer_target_audience(message: str) -> str:
    return _extract_phrase_after_keyword(message, keyword="for", stop_keywords=("in", "with"))


def _infer_geography(message: str) -> str:
    candidate = _extract_phrase_after_keyword(message, keyword="in", stop_keywords=("for", "with"))
    if len(candidate.split()) > 5:
        return ""
    return candidate


def _split_list_items(value: str) -> list[str]:
    separators = [",", ";", "\n", " and "]
    parts = [value]
    for separator in separators:
        next_parts: list[str] = []
        for part in parts:
            next_parts.extend(part.split(separator))
        parts = next_parts
    return [item for item in (_normalize_text(part) for part in parts) if item]


def _merge_unique_strings(existing_values: list[str], new_values: list[str]) -> list[str]:
    merged = list(existing_values)
    for value in new_values:
        if value and value not in merged:
            merged.append(value)
    return merged


def _build_campaign_brief_summary(brief_data: dict[str, Any]) -> str:
    objective = brief_data.get(OBJECTIVE_KEY, "")
    audience = brief_data.get(TARGET_AUDIENCE_KEY, "")
    geography = brief_data.get(GEOGRAPHY_KEY, "")
    if objective and audience and geography:
        return f"{objective} Audience: {audience}. Geography: {geography}."
    if objective and audience:
        return f"{objective} Audience: {audience}."
    if objective:
        return objective
    return "Campaign brief started from operator input."


def _build_snapshot_from_campaign_brief(
    campaign_brief: WorkflowArtifact,
    *,
    campaign_intent: WorkflowArtifact | None = None,
    conversion_target: WorkflowArtifact | None = None,
    setup_state: dict[str, Any] | None = None,
) -> WorkflowSnapshot:
    brief_data = campaign_brief.data
    intent_data = campaign_intent.data if campaign_intent is not None else {}
    setup_state = dict(setup_state or {})
    readiness_status = str(setup_state.get("readiness_status", "")).strip()
    if readiness_status == "confirmed":
        return WorkflowSnapshot(
            stage=WorkflowStage.DISCOVERY,
            summary="Campaign setup confirmed. Ready for discovery work.",
            data={
                "campaign_intent_artifact_id": campaign_intent.artifact_id if campaign_intent is not None else "",
                "campaign_brief_artifact_id": campaign_brief.artifact_id,
                "objective": brief_data.get(OBJECTIVE_KEY, ""),
                "target_audience": brief_data.get(TARGET_AUDIENCE_KEY, ""),
                "campaign_setup_readiness_status": readiness_status,
                **_build_conversion_target_snapshot_data(
                    conversion_target,
                    fallback_signal=(
                        intent_data.get(CONVERSION_TARGET_SIGNAL_KEY, {})
                        if isinstance(intent_data, dict)
                        else {}
                    ),
                ),
            },
        )

    missing_fields = [
        field_name
        for field_name in READY_FIELDS
        if not _normalize_text(str(brief_data.get(field_name, "")))
    ]
    if missing_fields:
        return WorkflowSnapshot(
            stage=WorkflowStage.INTAKE,
            summary=_build_setup_progress_summary(setup_state, missing_fields),
            data={
                "campaign_intent_artifact_id": campaign_intent.artifact_id if campaign_intent is not None else "",
                "campaign_brief_artifact_id": campaign_brief.artifact_id,
                "missing_fields": missing_fields,
                "campaign_setup_readiness_status": readiness_status or "collecting_inputs",
                "last_missing_question_hint": setup_state.get("last_missing_question_hint", ""),
                **_build_conversion_target_snapshot_data(
                    conversion_target,
                    fallback_signal=(
                        intent_data.get(CONVERSION_TARGET_SIGNAL_KEY, {})
                        if isinstance(intent_data, dict)
                        else {}
                    ),
                ),
            },
        )

    return WorkflowSnapshot(
        stage=WorkflowStage.INTAKE,
        summary="Campaign setup is ready. Confirm when you want to begin discovery.",
        data={
            "campaign_intent_artifact_id": campaign_intent.artifact_id if campaign_intent is not None else "",
            "campaign_brief_artifact_id": campaign_brief.artifact_id,
            "objective": brief_data.get(OBJECTIVE_KEY, ""),
            "target_audience": brief_data.get(TARGET_AUDIENCE_KEY, ""),
            "campaign_setup_readiness_status": readiness_status or "ready_to_confirm",
            "seed_target_groups": brief_data.get(SEED_TARGET_GROUPS_KEY, []),
            "asset_ref_count": len(intent_data.get(INTENT_ASSET_REFS_KEY, []))
            if isinstance(intent_data, dict)
            else 0,
            "recent_asset_refs": intent_data.get(INTENT_ASSET_REFS_KEY, [])[-5:]
            if isinstance(intent_data, dict)
            else [],
            "campaign_intent_summary": campaign_intent.summary if campaign_intent is not None else "",
            "campaign_intent_ambiguities": intent_data.get(INTENT_AMBIGUITIES_KEY, [])
            if isinstance(intent_data, dict)
            else [],
            **_build_conversion_target_snapshot_data(
                conversion_target,
                fallback_signal=(
                    intent_data.get(CONVERSION_TARGET_SIGNAL_KEY, {})
                    if isinstance(intent_data, dict)
                    else {}
                ),
            ),
        },
    )


def _build_conversion_target_snapshot_data(
    conversion_target: WorkflowArtifact | None,
    *,
    fallback_signal: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = conversion_target.data if conversion_target is not None and isinstance(conversion_target.data, dict) else {}
    fallback_signal = fallback_signal if isinstance(fallback_signal, dict) else {}
    raw_value = _normalize_text(
        payload.get(CONVERSION_RAW_VALUE_KEY, "")
        or fallback_signal.get(INTENT_RAW_VALUE_KEY, "")
    )
    destination_kind = _normalize_text(payload.get(CONVERSION_DESTINATION_KIND_KEY, ""))
    normalized_value = _normalize_text(payload.get(CONVERSION_NORMALIZED_VALUE_KEY, ""))
    summary = conversion_target.summary if conversion_target is not None else ""
    return {
        "conversion_target_artifact_id": conversion_target.artifact_id if conversion_target is not None else "",
        "conversion_target_summary": summary,
        "conversion_target_kind": destination_kind,
        "conversion_target_normalized_value": normalized_value,
        "conversion_target_signal": raw_value,
    }


def _normalize_text(value: str) -> str:
    cleaned = " ".join(value.strip().split())
    for stopword in STOPWORDS:
        if cleaned.endswith(stopword):
            cleaned = cleaned[: -len(stopword)].strip()
    return cleaned


def _extract_unlabeled_segments(message: str) -> list[str]:
    segments: list[str] = []
    last_end = 0
    for match in _labeled_field_pattern().finditer(message):
        leading = _normalize_text(message[last_end:match.start()])
        if leading:
            segments.append(leading)
        last_end = match.end()

    trailing = _normalize_text(message[last_end:])
    if trailing:
        segments.append(trailing)
    return segments


def _labeled_field_pattern() -> re.Pattern[str]:
    aliases = sorted(
        {
            alias
            for alias_group in LABELED_FIELD_ALIASES.values()
            for alias in alias_group
        },
        key=len,
        reverse=True,
    )
    alias_pattern = "|".join(re.escape(alias) for alias in aliases)
    return re.compile(
        rf"(?is)(?P<label>{alias_pattern})\s*:\s*(?P<value>.*?)(?=(?:\s+(?:{alias_pattern})\s*:)|\n|$)"
    )


def _extract_phrase_after_keyword(
    message: str,
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
    tail = raw_tail
    lower_tail = raw_tail.lower()
    stop_markers = [f" {stop_keyword.lower()} " for stop_keyword in stop_keywords]
    punctuation_markers = [".", ",", ";", "\n"]

    end_index = len(raw_tail)
    for marker in [*stop_markers, *punctuation_markers]:
        marker_index = lower_tail.find(marker) if marker.startswith(" ") else raw_tail.find(marker)
        if marker_index != -1:
            end_index = min(end_index, marker_index)

    tail = raw_tail[:end_index]
    return _normalize_text(tail)


def _is_labeled_line(line: str) -> bool:
    stripped = line.strip().lower()
    if ":" not in stripped:
        return False
    label, _, _ = stripped.partition(":")
    return any(label == alias for aliases in LABELED_FIELD_ALIASES.values() for alias in aliases)


def _build_setup_progress_summary(setup_state: dict[str, Any], missing_fields: list[str]) -> str:
    question_hint = _normalize_text(str(setup_state.get("last_missing_question_hint", "")))
    if question_hint:
        return f"Campaign setup in progress. Next useful question: {question_hint}"

    readable_fields = ", ".join(field_name.replace("_", " ") for field_name in missing_fields)
    return f"Campaign setup in progress. Still need: {readable_fields}."


def _has_non_note_field_updates(field_updates: dict[str, Any]) -> bool:
    return any(
        key
        for key in field_updates
        if key not in {NOTES_KEY, SOURCE_MESSAGES_KEY}
    )
