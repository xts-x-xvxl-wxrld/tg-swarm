"""Discovery workflow helpers for structured community shortlist generation."""

from __future__ import annotations

import json
from typing import Any

from telegram_app.approvals import ApprovalManager
from telegram_app.intake import get_campaign_brief_artifact, get_workflow_snapshot
from telegram_app.models import (
    ApprovalRecord,
    SessionRecord,
    WorkflowArtifact,
    WorkflowArtifactKind,
    WorkflowSnapshot,
    WorkflowStage,
)
from telegram_app.sessions import SessionManager

DISCOVERY_JSON_MARKER = "DISCOVERY_SHORTLIST_JSON"
COMMUNITY_SHORTLIST_TITLE = "Community shortlist"
APPROVAL_CATEGORY = "community_shortlist"


def should_run_discovery(
    session: SessionRecord,
    pending_approval: ApprovalRecord | None,
) -> bool:
    """Return true when the current session should produce a discovery shortlist."""
    if pending_approval is not None:
        return False
    snapshot = get_workflow_snapshot(session)
    return snapshot.stage is WorkflowStage.DISCOVERY


def build_discovery_runtime_instructions(session: SessionRecord) -> str:
    """Build strict runtime guidance for discovery-stage turns."""
    campaign_brief = get_campaign_brief_artifact(session)
    if campaign_brief is None:
        return ""

    lines = [
        "Discovery workflow instructions:",
        "- This session is in the discovery stage.",
        "- Produce a shortlist of Telegram communities that match the stored campaign brief.",
        "- Prefer live Telegram capability data when it is available.",
        "- Return a concise operator-facing summary first.",
        "- Ask the operator to approve the shortlist or request changes.",
        f"- Then append a line containing exactly `{DISCOVERY_JSON_MARKER}`.",
        "- After that line, include one fenced JSON block with this shape:",
        (
            '  {"summary":"...",'
            '"recommended_next_step":"...",'
            '"communities":[{"name":"...","handle":"...","type":"group|channel",'
            '"topic":"...","language":"...","geography":"...","relevance_score":0,'
            '"promo_tolerance":"low|medium|high","moderation_risk":"low|medium|high",'
            '"reason":"...","verification_state":"live_confirmed|search_confirmed|training_knowledge_fallback",'
            '"source_notes":["..."]}]}'
        ),
        "- Keep the JSON valid and do not include trailing commentary after the JSON block.",
    ]
    return "\n".join(lines)


def parse_discovery_shortlist(final_output: str) -> dict[str, Any] | None:
    """Extract the structured discovery shortlist payload from final output."""
    if DISCOVERY_JSON_MARKER not in final_output:
        return None

    _, _, remainder = final_output.partition(DISCOVERY_JSON_MARKER)
    remainder = remainder.strip()
    if remainder.startswith("```json"):
        remainder = remainder[len("```json") :].strip()
    elif remainder.startswith("```"):
        remainder = remainder[len("```") :].strip()

    if remainder.endswith("```"):
        remainder = remainder[:-3].strip()

    try:
        payload = json.loads(remainder)
    except json.JSONDecodeError:
        return None

    communities = payload.get("communities")
    if not isinstance(payload, dict) or not isinstance(communities, list) or not communities:
        return None
    return payload


def strip_discovery_json_block(final_output: str) -> str:
    """Remove the machine-readable discovery block before sending text to Telegram."""
    if DISCOVERY_JSON_MARKER not in final_output:
        return final_output.strip()
    operator_text, _, _ = final_output.partition(DISCOVERY_JSON_MARKER)
    return operator_text.strip()


def persist_discovery_shortlist(
    session_manager: SessionManager,
    approval_manager: ApprovalManager | None,
    session: SessionRecord,
    shortlist_payload: dict[str, Any],
) -> tuple[WorkflowArtifact, ApprovalRecord | None]:
    """Persist the discovery shortlist and keep discovery open for conversational review."""
    artifact = _find_existing_shortlist(session_manager, session)
    communities = shortlist_payload.get("communities", [])
    summary = str(shortlist_payload.get("summary", "")).strip() or _build_shortlist_summary(communities)
    data = {
        "summary": summary,
        "recommended_next_step": str(shortlist_payload.get("recommended_next_step", "")).strip(),
        "verification_summary": str(shortlist_payload.get("verification_summary", "")).strip(),
        "coverage_summary": str(shortlist_payload.get("coverage_summary", "")).strip(),
        "verification_counts": shortlist_payload.get("verification_counts", {}),
        "search_diagnostics": shortlist_payload.get("search_diagnostics", {}),
        "communities": communities,
    }

    if artifact is None:
        artifact = session_manager.create_workflow_artifact(
            session=session,
            kind=WorkflowArtifactKind.COMMUNITY_SHORTLIST,
            title=COMMUNITY_SHORTLIST_TITLE,
            summary=summary,
            data=data,
        )
    else:
        artifact.summary = summary
        artifact.data = data
        session_manager.save_workflow_artifact(session, artifact)

    session.pending_approval_id = None
    session_manager.replace_workflow_snapshot(
        session,
        WorkflowSnapshot(
            stage=WorkflowStage.DISCOVERY,
            summary="Community shortlist ready for operator review.",
            data={
                "community_shortlist_artifact_id": artifact.artifact_id,
                "community_count": len(communities),
            },
        ),
    )
    return artifact, None


def _find_existing_shortlist(
    session_manager: SessionManager,
    session: SessionRecord,
) -> WorkflowArtifact | None:
    shortlist_artifacts = [
        artifact
        for artifact in session_manager.list_workflow_artifacts(session)
        if artifact.kind is WorkflowArtifactKind.COMMUNITY_SHORTLIST
    ]
    if not shortlist_artifacts:
        return None
    return max(shortlist_artifacts, key=lambda artifact: artifact.updated_at)


def _build_shortlist_summary(communities: list[Any]) -> str:
    return f"Ranked {len(communities)} candidate Telegram communities."
