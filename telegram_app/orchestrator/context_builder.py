"""Build the runtime context string injected as a system prompt block each turn."""

from __future__ import annotations

import json
from typing import Any

from telegram_app.agent_runtime import AgentRuntimeBroker
from telegram_app.campaign_intent import prompt_safe_campaign_intent_data
from telegram_app.campaign_context import (
    get_campaign_context_artifact,
    prompt_safe_campaign_context_data,
)
from telegram_app.conversion_target import prompt_safe_conversion_target_data
from telegram_app.campaign_assets import CampaignAssetManager
from telegram_app.campaign_setup import get_campaign_setup_state
from telegram_app.continuous_ops.storage import load_continuous_ops_state_for_workspace
from telegram_app.campaign_memory import CampaignMemoryManager
from telegram_app.discovery import build_discovery_runtime_instructions
from telegram_app.intake import (
    get_campaign_brief_artifact,
    get_campaign_intent_artifact,
    get_conversion_target_artifact,
    get_workflow_snapshot,
)
from telegram_app.models import ApprovalRecord, ScheduleRecord, SessionRecord, WorkItemRecord
from telegram_app.operator_notifications import load_interventions_for_workspace
from telegram_app.orchestrator.reasoning_surfaces import (
    CONTROL_BRAIN_SURFACE,
    build_reasoning_surface_catalog,
    reasoning_surface_for_work_type,
)

PROMPT_OMITTED_CAMPAIGN_BRIEF_KEYS = frozenset({"source_messages"})
_campaign_memory_manager = CampaignMemoryManager()
_campaign_asset_manager = CampaignAssetManager()


def build_runtime_context(
    session: SessionRecord,
    pending_approval: ApprovalRecord | None,
    active_work_items: list[WorkItemRecord] | None = None,
    active_schedules: list[ScheduleRecord] | None = None,
    discovery_mode: bool = False,
    observation_context: dict[str, Any] | None = None,
    work_type: str | None = None,
    conversation_id: str | None = None,
    agent_runtime_broker: AgentRuntimeBroker | None = None,
) -> str:
    """Build the runtime context block injected into control-brain and reasoning-surface prompts."""
    lines = [
        "Telegram runtime context:",
        f"- session_id: {session.session_id}",
        f"- operator_id: {session.operator_id}",
        f"- session_status: {session.status}",
        f"- control_brain_surface: {CONTROL_BRAIN_SURFACE}",
        "- routing_model: work_and_pressure_first",
        "- reasoning_surfaces: "
        + json.dumps(build_reasoning_surface_catalog(), ensure_ascii=True, sort_keys=True),
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
        continuous_ops_state = load_continuous_ops_state_for_workspace(
            session.campaign_workspace_path,
        )
        if continuous_ops_state is not None:
            lines.extend(
                [
                    "- continuous_ops_present: true",
                    f"- continuous_ops_status: {continuous_ops_state.loop_status.value}",
                    f"- continuous_ops_summary: {continuous_ops_state.status_summary}",
                    (
                        "- continuous_ops_data: "
                        + json.dumps(
                            continuous_ops_state.to_dict(),
                            ensure_ascii=True,
                            sort_keys=True,
                        )
                    ),
                ]
            )
        interventions = load_interventions_for_workspace(session.campaign_workspace_path)
        unresolved_interventions = [
            intervention
            for intervention in interventions
            if intervention.status.value != "resolved"
        ]
        if unresolved_interventions:
            lines.extend(
                [
                    "- operator_interventions_present: true",
                    (
                        "- operator_intervention_data: "
                        + json.dumps(
                            [
                                {
                                    "kind": intervention.kind.value,
                                    "status": intervention.status.value,
                                    "severity": intervention.severity.value,
                                    "title": intervention.title,
                                    "body": intervention.body,
                                    "recovery_hint": intervention.recovery_hint,
                                }
                                for intervention in unresolved_interventions[:5]
                            ],
                            ensure_ascii=True,
                            sort_keys=True,
                        )
                    ),
                ]
            )
        else:
            lines.append("- operator_interventions_present: false")
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
    setup_state = get_campaign_setup_state(session)
    lines.append(
        "- campaign_setup_state: "
        + json.dumps(_compact_dict(setup_state), ensure_ascii=True, sort_keys=True)
    )
    if session.campaign_workspace_path:
        preferred_asset_ids = setup_state.get("asset_refs", [])
        if not isinstance(preferred_asset_ids, list):
            preferred_asset_ids = []
        asset_refs = _campaign_asset_manager.build_prompt_asset_refs(
            session.campaign_workspace_path,
            preferred_asset_ids=[str(asset_id) for asset_id in preferred_asset_ids],
        )
        lines.append(f"- campaign_assets_present: {'true' if bool(asset_refs) else 'false'}")
        if asset_refs:
            lines.append(
                "- campaign_asset_refs: "
                + json.dumps([asset_ref["asset_id"] for asset_ref in asset_refs], ensure_ascii=True)
            )
            lines.append(
                "- campaign_asset_summaries: "
                + json.dumps(asset_refs, ensure_ascii=True, sort_keys=True)
            )

    campaign_brief = get_campaign_brief_artifact(session)
    campaign_context = get_campaign_context_artifact(session)
    campaign_intent = get_campaign_intent_artifact(session)
    conversion_target = get_conversion_target_artifact(session)
    if campaign_context is not None:
        lines.extend(
            [
                "- campaign_context_present: true",
                f"- campaign_context_summary: {campaign_context.summary}",
                (
                    "- campaign_context_data: "
                    + json.dumps(
                        prompt_safe_campaign_context_data(campaign_context.data),
                        ensure_ascii=True,
                        sort_keys=True,
                    )
                ),
            ]
        )
    else:
        lines.append("- campaign_context_present: false")
    if campaign_intent is not None:
        lines.extend(
            [
                "- campaign_intent_present: true",
                f"- campaign_intent_summary: {campaign_intent.summary}",
                (
                    "- campaign_intent_data: "
                    + json.dumps(prompt_safe_campaign_intent_data(campaign_intent.data), ensure_ascii=True, sort_keys=True)
                ),
            ]
        )
    else:
        lines.append("- campaign_intent_present: false")

    if conversion_target is not None:
        lines.extend(
            [
                "- conversion_target_present: true",
                f"- conversion_target_summary: {conversion_target.summary}",
                (
                    "- conversion_target_data: "
                    + json.dumps(
                        prompt_safe_conversion_target_data(conversion_target.data),
                        ensure_ascii=True,
                        sort_keys=True,
                    )
                ),
            ]
        )
    else:
        lines.append("- conversion_target_present: false")

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

    if agent_runtime_broker is not None:
        if active_work_items is None:
            active_work_items = agent_runtime_broker.list_active_work_items(session)
        if active_schedules is None:
            active_schedules = agent_runtime_broker.list_active_schedules(session)
        runtime_summaries = agent_runtime_broker.build_prompt_context(
            session,
            work_type=work_type,
            conversation_id=conversation_id,
        )
        for label, payload in runtime_summaries.items():
            compact_payload = _compact_value(payload)
            if compact_payload in ("", [], {}, None):
                continue
            lines.append(
                f"- {label}: "
                + json.dumps(compact_payload, ensure_ascii=True, sort_keys=True)
            )

    if active_work_items is not None:
        lines.append(f"- active_work_item_count: {len(active_work_items)}")
        if active_work_items:
            serialized_work_items = [
                {
                    "work_item_id": work_item.work_item_id,
                    "owner_role": work_item.owner_role,
                    "work_type": work_item.work_type,
                    "reasoning_surface": reasoning_surface_for_work_type(work_item.work_type),
                    "goal": work_item.goal,
                    "status": work_item.status.value,
                    "priority": work_item.priority.value,
                    "trigger_source": work_item.trigger_source,
                    "refresh_reason": work_item.refresh_reason,
                    "context_refs": work_item.context_refs,
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
                    "reasoning_surface": reasoning_surface_for_work_type(schedule.work_type),
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

    if observation_context:
        lines.append(
            "- observation_context: "
            + json.dumps(_compact_dict(observation_context), ensure_ascii=True, sort_keys=True)
        )

    return "\n".join(lines)


def _compact_dict(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if value not in ("", [], {}, None)
    }


def _compact_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _compact_value(item)
            for key, item in value.items()
            if _compact_value(item) not in ("", [], {}, None)
        }
    if isinstance(value, list):
        return [
            _compact_value(item)
            for item in value
            if _compact_value(item) not in ("", [], {}, None)
        ]
    return value


def _prompt_safe_campaign_brief_data(payload: dict[str, Any]) -> dict[str, Any]:
    compact_payload = _compact_dict(payload)
    return {
        key: value
        for key, value in compact_payload.items()
        if key not in PROMPT_OMITTED_CAMPAIGN_BRIEF_KEYS
    }
