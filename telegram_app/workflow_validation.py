"""Helpers for validating machine-readable workflow artifacts from LLM output."""

from __future__ import annotations

import json
from typing import Any


def parse_marked_json_block(output: str, marker: str) -> dict[str, Any] | None:
    """Return the JSON object that follows a marker, with one repair pass."""
    if marker not in output:
        return None

    _, _, remainder = output.partition(marker)
    candidate = _strip_code_fence(remainder.strip())
    if not candidate:
        return None

    for variant in _candidate_variants(candidate):
        try:
            payload = json.loads(variant)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def validate_strategy_playbook(payload: dict[str, Any] | None) -> str | None:
    """Return an error message when a strategy playbook payload is invalid."""
    if not isinstance(payload, dict):
        return "The strategy response did not include a valid JSON playbook."

    if not _is_non_empty_string(payload.get("campaign_strategy_summary")):
        return "The strategy playbook is missing `campaign_strategy_summary`."

    communities = payload.get("communities")
    if not isinstance(communities, list) or not communities:
        return "The strategy playbook must include at least one community entry."

    required_fields = ("messaging_angle", "message_format", "frequency", "timing", "risk_notes")
    for index, community in enumerate(communities, start=1):
        if not isinstance(community, dict):
            return f"Strategy community {index} must be an object."
        if not _is_non_empty_string(community.get("name")):
            return f"Strategy community {index} is missing `name`."
        for field in required_fields:
            if not _is_non_empty_string(community.get(field)):
                return f"Strategy community {index} is missing `{field}`."

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


def _candidate_variants(candidate: str) -> list[str]:
    variants = [candidate]
    start_index = candidate.find("{")
    end_index = candidate.rfind("}")
    if start_index != -1 and end_index > start_index:
        repaired = candidate[start_index : end_index + 1].strip()
        if repaired and repaired not in variants:
            variants.append(repaired)
    return variants


def _strip_code_fence(candidate: str) -> str:
    if candidate.startswith("```json"):
        candidate = candidate[len("```json") :].strip()
    elif candidate.startswith("```"):
        candidate = candidate[3:].strip()

    if candidate.endswith("```"):
        candidate = candidate[:-3].strip()
    return candidate


def _is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())
