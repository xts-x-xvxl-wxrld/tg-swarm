"""Account manager specialist agent for assignment planning with pacing rules."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import anthropic

from telegram_app.approvals import ApprovalManager
from telegram_app.capabilities import AccountCapability
from telegram_app.monitoring import NullRuntimeEventLogger, RuntimeEventLogger, RuntimeTraceContext
from telegram_app.models import (
    ApprovalRecord,
    SessionRecord,
    WorkflowArtifact,
    WorkflowArtifactKind,
)
from telegram_app.sessions import SessionManager
from telegram_app.workflow_validation import parse_marked_json_block, validate_account_assignment_plan

logger = logging.getLogger(__name__)

# agents/account_manager/agent.py -> agents/account_manager/ -> agents/ -> tg-swarm/ (repo root)
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

ACCOUNT_ASSIGNMENT_PLAN_JSON_MARKER = "ACCOUNT_ASSIGNMENT_PLAN_JSON"
APPROVAL_CATEGORY = "account_assignment_plan"
PROMPT_SAFE_CAMPAIGN_BRIEF_KEYS = (
    "objective",
    "target_audience",
    "offer",
    "geography",
    "language",
    "constraints",
    "success_criteria",
    "notes",
)
PROMPT_SAFE_SHORTLIST_KEYS = (
    "name",
    "handle",
    "community_id",
    "type",
    "topic",
    "language",
    "geography",
    "relevance_score",
    "promo_tolerance",
    "moderation_risk",
    "reason",
    "source_notes",
    "member_count",
    "verified",
    "restricted",
    "scam",
    "recent_activity_summary",
    "recent_tone_summary",
)
PROMPT_SAFE_PLAYBOOK_KEYS = (
    "name",
    "handle",
    "messaging_angle",
    "message_format",
    "frequency",
    "timing",
    "risk_notes",
)
PROMPT_SAFE_ACCOUNT_KEYS = (
    "account_id",
    "tier",
    "health",
    "language",
    "geography",
    "join_count_24h",
    "rate_limit_until",
    "last_active",
)


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
        account_capability: AccountCapability | None = None,
        monitor: RuntimeEventLogger | None = None,
    ) -> None:
        self._session_manager = session_manager
        self._approval_manager = approval_manager
        self._account_capability = account_capability
        self._monitor = monitor or NullRuntimeEventLogger()
        self._client = anthropic.Anthropic()

    def run(
        self,
        session: SessionRecord,
        operator_message: str = "",
        trace_context: RuntimeTraceContext | None = None,
    ) -> tuple[str, WorkflowArtifact | None, ApprovalRecord | None]:
        """Run account planning turn. Returns (operator_text, plan_artifact, approval)."""
        trace_context = (
            trace_context
            or RuntimeTraceContext(trace_id="", session_id=session.session_id, user_id=session.operator_id)
        ).with_session(session)
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
                        f"{label}: {json.dumps(_prompt_safe_artifact_data(kind, artifact.data), ensure_ascii=True)}"
                    )
        if operator_message.strip():
            context_lines.append(f"Operator revision context: {operator_message.strip()}")

        context_lines.extend(self._build_account_context())
        user_content = "\n".join(context_lines) + "\n\nPlease produce the account assignment plan."

        system = [
            {"type": "text", "text": _load_prompt("account_manager.md")},
            {"type": "text", "text": _load_prompt("shared_runtime.md")},
        ]
        messages = [{"role": "user", "content": user_content}]

        model = _resolve_model()
        logger.info("AccountManagerAgent calling Anthropic API model=%s", model)
        self._monitor.record_event(
            component="account_manager_agent",
            event_type="llm_request",
            trace_context=trace_context,
            session=session,
            payload={
                "model": model,
                "prompt_assets": ["account_manager.md", "shared_runtime.md"],
                "messages": messages,
            },
        )

        try:
            api_response = self._client.messages.create(
                model=model,
                max_tokens=4096,
                system=system,
                messages=messages,
            )
        except Exception as exc:
            self._monitor.record_event(
                component="account_manager_agent",
                event_type="llm_failed",
                trace_context=trace_context,
                session=session,
                payload={"model": model, "error": str(exc), "error_type": type(exc).__name__},
            )
            raise

        final_output = "".join(
            block.text for block in api_response.content if hasattr(block, "text")
        ).strip()

        plan_data = self._parse_plan_json(final_output)
        operator_text = self._strip_json_block(final_output)
        validation_error = validate_account_assignment_plan(plan_data)

        artifact: WorkflowArtifact | None = None
        approval: ApprovalRecord | None = None

        if validation_error is not None:
            operator_text = self._build_invalid_plan_response(operator_text, validation_error)
        elif self._session_manager is not None:
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

        self._monitor.record_event(
            component="account_manager_agent",
            event_type="llm_response",
            trace_context=trace_context,
            session=session,
            approval=approval,
            payload={
                "model": model,
                "output_text": final_output,
                "operator_text": operator_text,
                "artifact_id": artifact.artifact_id if artifact is not None else "",
                "approval_id": approval.approval_id if approval is not None else "",
                "validation_error": validation_error or "",
            },
        )
        return operator_text, artifact, approval

    def _build_account_context(self) -> list[str]:
        if self._account_capability is None:
            return ["Account roster: unavailable"]

        roster = self._account_capability.list_accounts()
        return [
            "Account roster:",
            json.dumps(
                _prompt_safe_roster(roster.success, roster.data, roster.error),
                ensure_ascii=True,
                sort_keys=True,
            ),
        ]

    def _parse_plan_json(self, output: str) -> dict:
        return parse_marked_json_block(output, ACCOUNT_ASSIGNMENT_PLAN_JSON_MARKER) or {}

    def _strip_json_block(self, output: str) -> str:
        if ACCOUNT_ASSIGNMENT_PLAN_JSON_MARKER not in output:
            return output.strip()
        operator_text, _, _ = output.partition(ACCOUNT_ASSIGNMENT_PLAN_JSON_MARKER)
        return operator_text.strip()

    def _build_invalid_plan_response(self, operator_text: str, validation_error: str) -> str:
        summary = operator_text.strip() or "I generated an account-planning draft, but I could not trust its structured output."
        return (
            f"{summary}\n\n"
            "I did not save or request approval for this plan because its machine-readable payload was incomplete. "
            f"{validation_error} Please ask me to retry account planning."
        )


def _prompt_safe_artifact_data(kind: WorkflowArtifactKind, data: dict) -> dict:
    if kind is WorkflowArtifactKind.CAMPAIGN_BRIEF:
        return {
            key: value
            for key, value in data.items()
            if key in PROMPT_SAFE_CAMPAIGN_BRIEF_KEYS and value not in ("", [], {}, None)
        }

    if kind is WorkflowArtifactKind.COMMUNITY_SHORTLIST:
        communities = data.get("communities", [])
        compact_communities = [
            {
                key: community.get(key)
                for key in PROMPT_SAFE_SHORTLIST_KEYS
                if community.get(key) not in ("", [], {}, None)
            }
            for community in communities
            if isinstance(community, dict)
        ]
        compact_payload = {
            "summary": data.get("summary"),
            "recommended_next_step": data.get("recommended_next_step"),
            "communities": compact_communities,
        }
        return {
            key: value
            for key, value in compact_payload.items()
            if value not in ("", [], {}, None)
        }

    if kind is WorkflowArtifactKind.STRATEGY_PLAYBOOK:
        communities = data.get("communities", [])
        compact_communities = [
            {
                key: community.get(key)
                for key in PROMPT_SAFE_PLAYBOOK_KEYS
                if community.get(key) not in ("", [], {}, None)
            }
            for community in communities
            if isinstance(community, dict)
        ]
        compact_payload = {
            "campaign_strategy_summary": data.get("campaign_strategy_summary"),
            "communities": compact_communities,
        }
        return {
            key: value
            for key, value in compact_payload.items()
            if value not in ("", [], {}, None)
        }

    return data


def _prompt_safe_roster(success: bool, data: dict, error: str | None) -> dict:
    accounts = data.get("accounts", []) if isinstance(data, dict) else []
    compact_accounts = [
        {
            key: account.get(key)
            for key in PROMPT_SAFE_ACCOUNT_KEYS
            if account.get(key) not in ("", [], {}, None)
        }
        for account in accounts
        if isinstance(account, dict)
    ]
    compact_payload = {
        "success": success,
        "data": {"accounts": compact_accounts},
        "error": error,
    }
    return {
        key: value
        for key, value in compact_payload.items()
        if value not in ("", [], {}, None)
    }
