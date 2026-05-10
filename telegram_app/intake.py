"""Structured intake helpers for turning operator turns into reusable workflow state."""

from __future__ import annotations

from typing import Any

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
NOTES_KEY = "notes"
SOURCE_MESSAGES_KEY = "source_messages"

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
    ) -> None:
        """Update structured intake state before the orchestrator processes the turn."""
        if pending_approval is not None:
            return

        normalized_message = message.strip()
        if not normalized_message:
            return

        campaign_brief = get_campaign_brief_artifact(session)
        if campaign_brief is None:
            campaign_brief = self._session_manager.create_workflow_artifact(
                session=session,
                kind=WorkflowArtifactKind.CAMPAIGN_BRIEF,
                title=CAMPAIGN_BRIEF_TITLE,
                summary="Campaign brief started from operator input.",
                data=_default_campaign_brief_data(),
            )

        campaign_brief.data = _merge_campaign_brief_data(
            existing_data=campaign_brief.data,
            message=normalized_message,
        )
        campaign_brief.summary = _build_campaign_brief_summary(campaign_brief.data)
        self._session_manager.save_workflow_artifact(session, campaign_brief)

        snapshot = _build_snapshot_from_campaign_brief(campaign_brief)
        self._session_manager.replace_workflow_snapshot(session, snapshot)


def get_campaign_brief_artifact(session: SessionRecord) -> WorkflowArtifact | None:
    """Return the latest campaign brief artifact saved in session state."""
    artifacts = _load_workflow_artifacts(session)
    campaign_briefs = [
        artifact
        for artifact in artifacts
        if artifact.kind is WorkflowArtifactKind.CAMPAIGN_BRIEF
    ]
    if not campaign_briefs:
        return None
    return max(campaign_briefs, key=lambda artifact: artifact.updated_at)


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


def _default_campaign_brief_data() -> dict[str, Any]:
    return {
        OBJECTIVE_KEY: "",
        TARGET_AUDIENCE_KEY: "",
        OFFER_KEY: "",
        GEOGRAPHY_KEY: "",
        LANGUAGE_KEY: "",
        CONSTRAINTS_KEY: [],
        SUCCESS_CRITERIA_KEY: [],
        NOTES_KEY: [],
        SOURCE_MESSAGES_KEY: [],
    }


def _merge_campaign_brief_data(existing_data: dict[str, Any], message: str) -> dict[str, Any]:
    brief_data = _default_campaign_brief_data()
    brief_data.update(
        {
            key: value
            for key, value in existing_data.items()
            if key in brief_data
        }
    )

    field_updates = _extract_field_updates(message)
    for key, value in field_updates.items():
        if key in (CONSTRAINTS_KEY, SUCCESS_CRITERIA_KEY, NOTES_KEY, SOURCE_MESSAGES_KEY):
            brief_data[key] = _merge_unique_strings(brief_data.get(key, []), value)
        elif value:
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


def _extract_field_updates(message: str) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    remaining_lines = []
    labeled_lines = _extract_labeled_lines(message)

    for field_name, aliases in LABELED_FIELD_ALIASES.items():
        extracted_value = _extract_labeled_value(labeled_lines, aliases)
        if not extracted_value:
            continue

        if field_name in (CONSTRAINTS_KEY, SUCCESS_CRITERIA_KEY):
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

    remaining_lines.extend(
        line
        for line in message.splitlines()
        if not _is_labeled_line(line)
    )
    extra_note = _normalize_text(" ".join(remaining_lines))
    if extra_note and extra_note != updates.get(OBJECTIVE_KEY):
        updates[NOTES_KEY] = [extra_note]

    return updates


def _extract_labeled_lines(message: str) -> dict[str, str]:
    labeled_lines: dict[str, str] = {}
    for raw_line in message.splitlines():
        line = raw_line.strip()
        if ":" not in line:
            continue
        label, _, value = line.partition(":")
        labeled_lines[label.strip().lower()] = _normalize_text(value)
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


def _build_snapshot_from_campaign_brief(campaign_brief: WorkflowArtifact) -> WorkflowSnapshot:
    brief_data = campaign_brief.data
    missing_fields = [
        field_name
        for field_name in READY_FIELDS
        if not _normalize_text(str(brief_data.get(field_name, "")))
    ]
    if missing_fields:
        readable_fields = ", ".join(field_name.replace("_", " ") for field_name in missing_fields)
        return WorkflowSnapshot(
            stage=WorkflowStage.INTAKE,
            summary=f"Campaign brief started. Still need: {readable_fields}.",
            data={
                "campaign_brief_artifact_id": campaign_brief.artifact_id,
                "missing_fields": missing_fields,
            },
        )

    return WorkflowSnapshot(
        stage=WorkflowStage.DISCOVERY,
        summary="Campaign brief is ready for discovery work.",
        data={
            "campaign_brief_artifact_id": campaign_brief.artifact_id,
            "objective": brief_data.get(OBJECTIVE_KEY, ""),
            "target_audience": brief_data.get(TARGET_AUDIENCE_KEY, ""),
        },
    )


def _normalize_text(value: str) -> str:
    cleaned = " ".join(value.strip().split())
    for stopword in STOPWORDS:
        if cleaned.endswith(stopword):
            cleaned = cleaned[: -len(stopword)].strip()
    return cleaned


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
