"""Account manager specialist agent for assignment planning with pacing rules."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import anthropic

from telegram_app.approvals import ApprovalManager
from telegram_app.models import (
    ApprovalRecord,
    SessionRecord,
    WorkflowArtifact,
    WorkflowArtifactKind,
)
from telegram_app.sessions import SessionManager

logger = logging.getLogger(__name__)

# agents/account_manager/agent.py -> agents/account_manager/ -> agents/ -> tg-swarm/ (repo root)
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

ACCOUNT_ASSIGNMENT_PLAN_JSON_MARKER = "ACCOUNT_ASSIGNMENT_PLAN_JSON"
APPROVAL_CATEGORY = "account_assignment_plan"


def _load_prompt(name: str) -> str:
    return (REPO_ROOT / "prompts" / name).read_text(encoding="utf-8")


def _resolve_model() -> str:
    model = os.getenv("DEFAULT_MODEL", "claude-sonnet-4-6").strip()
    if "/" in model:
        model = model.split("/", 1)[1]
    if not model.startswith("claude-"):
        model = "claude-sonnet-4-6"
    return model


def _get_latest_artifact_of_kind(
    session_manager: SessionManager,
    session: SessionRecord,
    kind: WorkflowArtifactKind,
) -> WorkflowArtifact | None:
    artifacts = [a for a in session_manager.list_workflow_artifacts(session) if a.kind is kind]
    if not artifacts:
        return None
    return max(artifacts, key=lambda a: a.updated_at)


class AccountManagerAgent:
    """Specialist agent for account assignment planning with pacing rules."""

    def __init__(
        self,
        session_manager: SessionManager | None = None,
        approval_manager: ApprovalManager | None = None,
    ) -> None:
        self._session_manager = session_manager
        self._approval_manager = approval_manager
        self._client = anthropic.Anthropic()

    def run(
        self,
        session: SessionRecord,
    ) -> tuple[str, WorkflowArtifact | None, ApprovalRecord | None]:
        """Run account planning turn. Returns (operator_text, plan_artifact, approval)."""
        context_lines = ["Account planning context:"]
        if self._session_manager is not None:
            for kind, label in [
                (WorkflowArtifactKind.CAMPAIGN_BRIEF, "Campaign brief"),
                (WorkflowArtifactKind.COMMUNITY_SHORTLIST, "Community shortlist"),
                (WorkflowArtifactKind.STRATEGY_PLAYBOOK, "Strategy playbook"),
            ]:
                artifact = _get_latest_artifact_of_kind(self._session_manager, session, kind)
                if artifact is not None:
                    context_lines.append(
                        f"{label}: {json.dumps(artifact.data, ensure_ascii=True)}"
                    )

        user_content = "\n".join(context_lines) + "\n\nPlease produce the account assignment plan."

        system = [
            {"type": "text", "text": _load_prompt("account_manager.md")},
            {"type": "text", "text": _load_prompt("shared_runtime.md")},
        ]
        messages = [{"role": "user", "content": user_content}]

        model = _resolve_model()
        logger.info("AccountManagerAgent calling Anthropic API model=%s", model)

        api_response = self._client.messages.create(
            model=model,
            max_tokens=4096,
            system=system,
            messages=messages,
        )

        final_output = "".join(
            block.text for block in api_response.content if hasattr(block, "text")
        ).strip()

        plan_data = self._parse_plan_json(final_output)
        operator_text = self._strip_json_block(final_output)

        artifact: WorkflowArtifact | None = None
        approval: ApprovalRecord | None = None

        if self._session_manager is not None:
            plan_summary = str(plan_data.get("plan_summary", "Account assignment plan ready."))
            existing = _get_latest_artifact_of_kind(
                self._session_manager, session, WorkflowArtifactKind.ACCOUNT_ASSIGNMENT_PLAN
            )
            if existing is not None:
                existing.data = plan_data
                existing.summary = plan_summary
                self._session_manager.save_workflow_artifact(session, existing)
                artifact = existing
            else:
                artifact = self._session_manager.create_workflow_artifact(
                    session=session,
                    kind=WorkflowArtifactKind.ACCOUNT_ASSIGNMENT_PLAN,
                    title="Account assignment plan",
                    summary=plan_summary,
                    data=plan_data,
                )

            if self._approval_manager is not None and artifact is not None:
                assignments = plan_data.get("assignments", [])
                approval = self._approval_manager.create_pending(
                    session_id=session.session_id,
                    category=APPROVAL_CATEGORY,
                    prompt="Approve this account assignment plan to begin execution, or tell me what to change.",
                    context={
                        "artifact_id": artifact.artifact_id,
                        "community_count": len(assignments),
                    },
                )
                self._session_manager.mark_pending_approval(session, approval.approval_id)

        return operator_text, artifact, approval

    def _parse_plan_json(self, output: str) -> dict:
        if ACCOUNT_ASSIGNMENT_PLAN_JSON_MARKER not in output:
            return {"raw_output": output}
        _, _, remainder = output.partition(ACCOUNT_ASSIGNMENT_PLAN_JSON_MARKER)
        remainder = remainder.strip()
        if remainder.startswith("```json"):
            remainder = remainder[len("```json"):].strip()
        elif remainder.startswith("```"):
            remainder = remainder[3:].strip()
        if remainder.endswith("```"):
            remainder = remainder[:-3].strip()
        try:
            return json.loads(remainder)
        except json.JSONDecodeError:
            return {"raw_output": output}

    def _strip_json_block(self, output: str) -> str:
        if ACCOUNT_ASSIGNMENT_PLAN_JSON_MARKER not in output:
            return output.strip()
        operator_text, _, _ = output.partition(ACCOUNT_ASSIGNMENT_PLAN_JSON_MARKER)
        return operator_text.strip()
