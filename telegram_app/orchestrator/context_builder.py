"""Build the runtime context string injected as a system prompt block each turn."""

from __future__ import annotations

import json
from typing import Any

from telegram_app.campaign_memory import CampaignMemoryManager
from telegram_app.discovery import build_discovery_runtime_instructions
from telegram_app.intake import get_campaign_brief_artifact, get_workflow_snapshot
from telegram_app.models import ApprovalRecord, ScheduleRecord, SessionRecord, WorkItemRecord

PROMPT_OMITTED_CAMPAIGN_BRIEF_KEYS = frozenset({"source_messages"})
_campaign_memory_manager = CampaignMemoryManager()


def build_runtime_context(
    session: SessionRecord,
    pending_approval: ApprovalRecord | None,
    active_work_items: list[WorkItemRecord] | None = None,
    active_schedules: list[ScheduleRecord] | None = None,
    discovery_mode: bool = False,
) -> str:
    """Build the runtime context block injected into orchestrator and specialist prompts."""
    lines = [
        "Telegram runtime context:",
        f"- session_id: {session.session_id}",
        f"- operator_id: {session.operator_id}",
        f"- session_status: {session.status}",
    ]
    if session.campaign_id and session.campaign_workspace_path:
        lines.extend(
            [
                "- campaign_attached: true",
                f"- campaign_id: {session.campaign_id}",
                f"- campaign_workspace_path: {session.campaign_workspace_path}",
                (
                    "- canonical_memory_files: "
                    + json.dumps(session.canonical_memory_files, ensure_ascii=True)
                ),
                (
                    "- agent_memory_files: "
                    + json.dumps(session.agent_memory_files, ensure_ascii=True)
                ),
            ]
        )
        prompt_memory = _campaign_memory_manager.load_prompt_memory(session)
        if prompt_memory:
            lines.append(
                "- campaign_memory_snapshot: "
                + json.dumps(prompt_memory, ensure_ascii=True, sort_keys=True)
            )
    else:
        lines.append("- campaign_attached: false")
    workflow_snapshot = get_workflow_snapshot(session)
    lines.extend(
        [
            f"- workflow_stage: {workflow_snapshot.stage}",
            f"- workflow_summary: {workflow_snapshot.summary}",
            (
                "- workflow_data: "
                + json.dumps(workflow_snapshot.data, ensure_ascii=True, sort_keys=True)
            ),
        ]
    )

    campaign_brief = get_campaign_brief_artifact(session)
    if campaign_brief is not None:
        lines.extend(
            [
                "- campaign_brief_present: true",
                f"- campaign_brief_summary: {campaign_brief.summary}",
                (
                    "- campaign_brief_data: "
                    + json.dumps(_prompt_safe_campaign_brief_data(campaign_brief.data), ensure_ascii=True, sort_keys=True)
                ),
            ]
        )
    else:
        lines.append("- campaign_brief_present: false")

    if pending_approval is not None:
        lines.extend(
            [
                "- pending_approval_present: true",
                f"- pending_approval_category: {pending_approval.category}",
                f"- pending_approval_prompt: {pending_approval.prompt}",
                (
                    "- pending_approval_context: "
                    + json.dumps(pending_approval.context, ensure_ascii=True, sort_keys=True)
                ),
                (
                    "- Interpret the latest operator message in context."
                    " It may be an approval response, a clarification, or a changed request."
                ),
            ]
        )
    else:
        lines.append("- pending_approval_present: false")

    if active_work_items is not None:
        lines.append(f"- active_work_item_count: {len(active_work_items)}")
        if active_work_items:
            serialized_work_items = [
                {
                    "work_item_id": work_item.work_item_id,
                    "owner_role": work_item.owner_role,
                    "work_type": work_item.work_type,
                    "goal": work_item.goal,
                    "status": work_item.status.value,
                    "priority": work_item.priority.value,
                    "result_summary": work_item.result_summary,
                    "schedule_id": work_item.schedule_id,
                }
                for work_item in active_work_items
            ]
            lines.append(
                "- active_work_items: "
                + json.dumps(serialized_work_items, ensure_ascii=True, sort_keys=True)
            )

    if active_schedules is not None:
        lines.append(f"- active_schedule_count: {len(active_schedules)}")
        if active_schedules:
            serialized_schedules = [
                {
                    "schedule_id": schedule.schedule_id,
                    "owner_role": schedule.owner_role,
                    "work_type": schedule.work_type,
                    "goal": schedule.goal,
                    "interval_minutes": schedule.interval_minutes,
                    "next_run_at": schedule.next_run_at.isoformat(),
                    "status": schedule.status.value,
                }
                for schedule in active_schedules
            ]
            lines.append(
                "- active_schedules: "
                + json.dumps(serialized_schedules, ensure_ascii=True, sort_keys=True)
            )

    if discovery_mode:
        discovery_instructions = build_discovery_runtime_instructions(session)
        if discovery_instructions:
            lines.append(discovery_instructions)

    return "\n".join(lines)


def _compact_dict(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if value not in ("", [], {}, None)
    }


def _prompt_safe_campaign_brief_data(payload: dict[str, Any]) -> dict[str, Any]:
    compact_payload = _compact_dict(payload)
    return {
        key: value
        for key, value in compact_payload.items()
        if key not in PROMPT_OMITTED_CAMPAIGN_BRIEF_KEYS
    }
