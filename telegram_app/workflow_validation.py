"""Helpers for validating machine-readable workflow artifacts from LLM output."""

from __future__ import annotations

import json
from typing import Any

from telegram_app.models import WorkItemPriority

OUTPUT_PROPOSALS_JSON_MARKER = "COMPILED_PROPOSALS_JSON"


def parse_marked_json_block(output: str, marker: str) -> dict[str, Any] | None:
    """Return the JSON object that follows a marker, with one repair pass."""
    payload = parse_marked_json_value_block(output, marker)
    if isinstance(payload, dict):
        return payload
    return None


def parse_marked_json_list_block(output: str, marker: str) -> list[dict[str, Any]] | None:
    """Return the JSON list that follows a marker, with one repair pass."""
    payload = parse_marked_json_value_block(output, marker)
    if not isinstance(payload, list):
        return None
    normalized = [item for item in payload if isinstance(item, dict)]
    if len(normalized) != len(payload):
        return None
    return normalized


def parse_output_proposal_list(output: str) -> list[dict[str, Any]] | None:
    """Return shared output proposals from the post-cutover proposal marker."""
    return parse_marked_json_list_block(output, OUTPUT_PROPOSALS_JSON_MARKER)


def parse_marked_json_value_block(output: str, marker: str) -> Any | None:
    """Return any JSON value that follows a marker, with one repair pass."""
    if marker not in output:
        return None

    _, _, remainder = output.partition(marker)
    candidate = _strip_code_fence(_strip_leading_empty_fences(remainder.strip()))
    if not candidate:
        return None

    for variant in _candidate_variants(candidate):
        try:
            return json.loads(variant)
        except json.JSONDecodeError:
            continue
    return None


def strip_marked_block(output: str, marker: str) -> str:
    """Return the operator-facing text before one machine-readable marker block."""
    if marker not in output:
        return output.strip()
    operator_text, _, _ = output.partition(marker)
    return operator_text.strip()


def validate_strategy_playbook(payload: dict[str, Any] | None) -> str | None:
    """Return an error message when a strategy playbook payload is invalid."""
    if not isinstance(payload, dict):
        return "The strategy response did not include a valid JSON playbook."

    if not _is_non_empty_string(payload.get("campaign_strategy_summary")):
        return "The strategy playbook is missing `campaign_strategy_summary`."

    communities = payload.get("communities")
    if not isinstance(communities, list) or not communities:
        return "The strategy playbook must include at least one community entry."

    voice_profile = payload.get("voice_profile")
    if voice_profile is not None:
        if not isinstance(voice_profile, dict):
            return "The strategy playbook `voice_profile` must be an object."
        for key in ("tone_descriptors", "style_do", "style_avoid"):
            if key in voice_profile and not isinstance(voice_profile.get(key), list):
                return f"The strategy playbook `voice_profile.{key}` must be a list."

    approved_claims = payload.get("approved_claims", [])
    if approved_claims is not None:
        if not isinstance(approved_claims, list):
            return "The strategy playbook `approved_claims` must be a list."
        for index, claim in enumerate(approved_claims, start=1):
            if not isinstance(claim, dict):
                return f"Approved claim {index} must be an object."
            if not _is_non_empty_string(claim.get("claim_id")):
                return f"Approved claim {index} is missing `claim_id`."
            if not _is_non_empty_string(claim.get("text")):
                return f"Approved claim {index} is missing `text`."

    forbidden_claims = payload.get("forbidden_claims", [])
    if forbidden_claims is not None:
        if not isinstance(forbidden_claims, list):
            return "The strategy playbook `forbidden_claims` must be a list."
        for index, claim in enumerate(forbidden_claims, start=1):
            if not isinstance(claim, dict):
                return f"Forbidden claim {index} must be an object."
            if not _is_non_empty_string(claim.get("label")):
                return f"Forbidden claim {index} is missing `label`."
            if not _is_non_empty_string(claim.get("instruction")):
                return f"Forbidden claim {index} is missing `instruction`."

    required_fields = ("messaging_angle", "message_format", "frequency", "timing", "risk_notes")
    for index, community in enumerate(communities, start=1):
        if not isinstance(community, dict):
            return f"Strategy community {index} must be an object."
        if not _is_non_empty_string(community.get("name")):
            return f"Strategy community {index} is missing `name`."
        for field in required_fields:
            if not _is_non_empty_string(community.get(field)):
                return f"Strategy community {index} is missing `{field}`."
        for field in (
            "community_risk_level",
            "tone_guidance",
            "response_posture",
            "allowed_cta",
            "direct_response_rule",
            "clarifying_question_rule",
            "escalation_rule",
        ):
            if field in community and not _is_non_empty_string(community.get(field)):
                return f"Strategy community {index} has an invalid `{field}`."
        for field in ("approved_claim_ids", "forbidden_claim_labels", "risky_topics"):
            if field in community and not isinstance(community.get(field), list):
                return f"Strategy community {index} `{field}` must be a list when present."

    return None


def validate_account_assignment_plan(payload: dict[str, Any] | None) -> str | None:
    """Return an error message when an account plan payload is invalid."""
    if not isinstance(payload, dict):
        return "The account-planning response did not include a valid JSON plan."

    if not _is_non_empty_string(payload.get("plan_summary")):
        return "The account assignment plan is missing `plan_summary`."

    assignments = payload.get("assignments")
    if not isinstance(assignments, list) or not assignments:
        return "The account assignment plan must include at least one assignment."

    for index, assignment in enumerate(assignments, start=1):
        if not isinstance(assignment, dict):
            return f"Assignment {index} must be an object."
        if not _is_non_empty_string(assignment.get("community_name")):
            return f"Assignment {index} is missing `community_name`."
        if not _is_non_empty_string(assignment.get("assigned_account")):
            return f"Assignment {index} is missing `assigned_account`."
        scheduled_posts = assignment.get("scheduled_posts")
        if not isinstance(scheduled_posts, list) or not scheduled_posts:
            return f"Assignment {index} must include at least one scheduled post."

    return None


def validate_observation_review(payload: dict[str, Any] | None) -> str | None:
    """Return an error message when an observation review payload is invalid."""
    if not isinstance(payload, dict):
        return "The observation response did not include a valid JSON review block."

    if not _is_non_empty_string(payload.get("summary")):
        return "The observation review is missing `summary`."

    if str(payload.get("material_change", "")).strip() not in {"yes", "no"}:
        return "The observation review `material_change` must be `yes` or `no`."

    if str(payload.get("priority_pressure", "")).strip() not in {"low", "medium", "high"}:
        return "The observation review `priority_pressure` must be `low`, `medium`, or `high`."

    if str(payload.get("operator_attention_needed", "")).strip() not in {"none", "recommended", "required"}:
        return "The observation review `operator_attention_needed` must be `none`, `recommended`, or `required`."

    if str(payload.get("recommended_next_step", "")).strip() not in {
        "keep_current_plan",
        "refresh_strategy",
        "refresh_account_planning",
        "operator_review",
    }:
        return (
            "The observation review `recommended_next_step` must be "
            "`keep_current_plan`, `refresh_strategy`, `refresh_account_planning`, or `operator_review`."
        )

    suggested_work_item_changes = payload.get("suggested_work_item_changes", [])
    if not isinstance(suggested_work_item_changes, list):
        return "The observation review `suggested_work_item_changes` must be a list."
    for index, change in enumerate(suggested_work_item_changes, start=1):
        if not isinstance(change, dict):
            return f"Observation work-item change {index} must be an object."
        if str(change.get("action", "")).strip() not in {"none", "refresh", "create_if_missing"}:
            return (
                f"Observation work-item change {index} must use action "
                "`none`, `refresh`, or `create_if_missing`."
            )
        if str(change.get("work_type", "")).strip() not in {"strategy", "account_planning"}:
            return f"Observation work-item change {index} must target `strategy` or `account_planning`."

    suggested_posture_updates = payload.get("suggested_posture_updates", [])
    if not isinstance(suggested_posture_updates, list):
        return "The observation review `suggested_posture_updates` must be a list."
    for index, update in enumerate(suggested_posture_updates, start=1):
        if not isinstance(update, dict):
            return f"Observation posture update {index} must be an object."
        if str(update.get("kind", "")).strip() not in {
            "campaign_pause_review",
            "community_avoidance_review",
            "account_rest_review",
        }:
            return (
                f"Observation posture update {index} must use kind "
                "`campaign_pause_review`, `community_avoidance_review`, or `account_rest_review`."
            )

    memory_note_lines = payload.get("memory_note_lines", [])
    if not isinstance(memory_note_lines, list):
        return "The observation review `memory_note_lines` must be a list."
    return None


def validate_schedule_action(payload: dict[str, Any] | None) -> str | None:
    """Return an error message when a schedule action payload is invalid."""
    if not isinstance(payload, dict):
        return "The schedule response did not include a valid JSON action."

    action = str(payload.get("action", "")).strip().lower()
    if action not in {"create", "pause", "resume"}:
        return "The schedule action must be one of `create`, `pause`, or `resume`."

    schedule = payload.get("schedule")
    if not isinstance(schedule, dict):
        return "The schedule action must include a `schedule` object."

    if action == "create":
        return _validate_schedule_create(schedule)
    return _validate_schedule_state_change(schedule)


def _candidate_variants(candidate: str) -> list[str]:
    variants = [candidate]
    for opening, closing in (("{", "}"), ("[", "]")):
        start_index = candidate.find(opening)
        end_index = candidate.rfind(closing)
        if start_index == -1 or end_index <= start_index:
            continue
        repaired = candidate[start_index : end_index + 1].strip()
        if repaired and repaired not in variants:
            variants.append(repaired)
    return variants


def _strip_code_fence(candidate: str) -> str:
    if candidate.startswith("```json"):
        candidate = candidate[len("```json") :].strip()
        if "```" in candidate:
            candidate = candidate.split("```", 1)[0].strip()
    elif candidate.startswith("```"):
        candidate = candidate[3:].strip()
        if "```" in candidate:
            candidate = candidate.split("```", 1)[0].strip()

    if candidate.endswith("```"):
        candidate = candidate[:-3].strip()
    return candidate


def _strip_leading_empty_fences(candidate: str) -> str:
    """Drop dangling empty fence lines that appear before the real JSON block."""
    cleaned = candidate.strip()
    while cleaned.startswith("```"):
        first_line, separator, remainder = cleaned.partition("\n")
        if first_line.strip() != "```" or not separator:
            break
        next_candidate = remainder.lstrip()
        if not next_candidate.startswith("```"):
            break
        cleaned = next_candidate
    return cleaned


def _is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_schedule_create(schedule: dict[str, Any]) -> str | None:
    owner_role = str(schedule.get("owner_role", "")).strip()
    work_type = str(schedule.get("work_type", "")).strip()
    goal = str(schedule.get("goal", "")).strip()
    interval_minutes = schedule.get("interval_minutes")
    priority = str(schedule.get("priority", "")).strip().lower()

    allowed_pairs = {
        "discovery": "discovery",
        "strategy": "strategy",
        "account_planning": "account_manager",
        "observation": "observation",
    }
    if work_type not in allowed_pairs:
        return "The schedule `work_type` must be `discovery`, `strategy`, `account_planning`, or `observation`."
    if owner_role != allowed_pairs[work_type]:
        return f"The schedule `owner_role` must be `{allowed_pairs[work_type]}` for `{work_type}` work."
    if not goal:
        return "The schedule is missing `goal`."
    if not isinstance(interval_minutes, int) or interval_minutes <= 0:
        return "The schedule must include a positive integer `interval_minutes`."
    if priority and priority not in {member.value for member in WorkItemPriority}:
        return "The schedule `priority` must be `low`, `medium`, or `high` when it is provided."

    minimum_value = schedule.get("minimum_value")
    if minimum_value is not None and not isinstance(minimum_value, int):
        return "The schedule `minimum_value` must be an integer when it is provided."

    pause_after = schedule.get("pause_after_consecutive_misses")
    if pause_after is not None and (not isinstance(pause_after, int) or pause_after <= 0):
        return "The schedule `pause_after_consecutive_misses` must be a positive integer when it is provided."

    constraints = schedule.get("constraints")
    if constraints is not None and not isinstance(constraints, list):
        return "The schedule `constraints` must be a list of strings when it is provided."
    return None


def _validate_schedule_state_change(schedule: dict[str, Any]) -> str | None:
    schedule_id = str(schedule.get("schedule_id", "")).strip()
    work_type = str(schedule.get("work_type", "")).strip()
    if not schedule_id and not work_type:
        return "The schedule action must include either `schedule_id` or `work_type`."
    if work_type and work_type not in {"discovery", "strategy", "account_planning", "observation"}:
        return (
            "The schedule `work_type` must be `discovery`, `strategy`, `account_planning`, "
            "or `observation` when it is provided."
        )
    return None
