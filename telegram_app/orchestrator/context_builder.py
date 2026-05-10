"""Build the runtime context string injected as a system prompt block each turn."""

from __future__ import annotations

import json
from typing import Any

from telegram_app.intake import get_campaign_brief_artifact, get_workflow_snapshot
from telegram_app.models import ApprovalRecord, SessionRecord
from telegram_app.discovery import build_discovery_runtime_instructions


def build_runtime_context(
    session: SessionRecord,
    pending_approval: ApprovalRecord | None,
    discovery_mode: bool = False,
) -> str:
    """Port of AgencyOrchestratorAdapter._build_runtime_instructions — exact same format."""
    lines = [
        "Telegram runtime context:",
        f"- session_id: {session.session_id}",
        f"- operator_id: {session.operator_id}",
        f"- session_status: {session.status}",
    ]
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
                    + json.dumps(_compact_dict(campaign_brief.data), ensure_ascii=True, sort_keys=True)
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
