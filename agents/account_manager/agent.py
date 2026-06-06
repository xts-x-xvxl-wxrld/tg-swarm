"""Account-planning surface agent for assignment planning with pacing rules."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from uuid import uuid4

import anthropic

from telegram_app.agent_runtime import AgentRuntimeBroker
from telegram_app.approvals import ApprovalManager
from telegram_app.campaign_memory import CampaignMemoryManager
from telegram_app.capabilities import (
    AccountCapability,
    CommunityCapability,
    MembershipCapability,
    MessagingCapability,
)
from telegram_app.llm import TelegramCapabilityToolbox, resolve_model
from telegram_app.monitoring import NullRuntimeEventLogger, RuntimeEventLogger, RuntimeTraceContext
from telegram_app.models import (
    ApprovalRecord,
    SessionRecord,
    WorkflowArtifact,
    WorkflowArtifactKind,
)
from telegram_app.orchestrator.context_builder import build_runtime_context
from telegram_app.sessions import SessionManager
from telegram_app.workflow_validation import (
    parse_marked_json_block,
    parse_output_proposal_list,
    strip_marked_block,
    validate_account_assignment_plan,
)

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
    "verification_state",
    "source_notes",
    "member_count",
    "verified",
    "restricted",
    "scam",
    "search_mode",
    "match_kind",
    "evidence_summary",
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
    """Planning-surface agent for account assignment planning with pacing rules."""

    def __init__(
        self,
        session_manager: SessionManager | None = None,
        approval_manager: ApprovalManager | None = None,
        account_capability: AccountCapability | None = None,
        community_capability: CommunityCapability | None = None,
        membership_capability: MembershipCapability | None = None,
        messaging_capability: MessagingCapability | None = None,
        monitor: RuntimeEventLogger | None = None,
        runtime_broker: AgentRuntimeBroker | None = None,
    ) -> None:
        self._session_manager = session_manager
        self._approval_manager = approval_manager
        self._account_capability = account_capability
        self._community_capability = community_capability
        self._membership_capability = membership_capability
        self._messaging_capability = messaging_capability
        self._monitor = monitor or NullRuntimeEventLogger()
        self._runtime_broker = runtime_broker
        self._memory_manager = CampaignMemoryManager()
        self._client = anthropic.Anthropic()
        self._toolbox = TelegramCapabilityToolbox(
            account_capability=account_capability,
            community_capability=community_capability,
            membership_capability=membership_capability,
            messaging_capability=messaging_capability,
        )
        self.last_proposal_payloads: list[dict[str, object]] = []

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
            {
                "type": "text",
                "text": build_runtime_context(
                    session,
                    pending_approval=None,
                    work_type="account_planning",
                    agent_runtime_broker=self._runtime_broker,
                ),
            },
        ]
        specialist_memory = self._memory_manager.load_agent_prompt_memory(session, "account_manager")
        if specialist_memory:
            system.append(
                {
                    "type": "text",
                    "text": "Account manager working memory:\n"
                    + json.dumps(specialist_memory, ensure_ascii=True, sort_keys=True),
                }
            )
        messages = [{"role": "user", "content": user_content}]

        model = resolve_model()
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
            completion = self._toolbox.run_completion(
                client=self._client,
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

        final_output = completion.final_output
        self.last_proposal_payloads = parse_output_proposal_list(final_output) or []

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
        else:
            plan_summary = str(plan_data.get("plan_summary", "Account assignment plan ready."))
            artifact = WorkflowArtifact(
                artifact_id=str(uuid4()),
                kind=WorkflowArtifactKind.ACCOUNT_ASSIGNMENT_PLAN,
                title="Account assignment plan",
                summary=plan_summary,
                data=plan_data,
            )
        if artifact is not None:
            self._write_working_memory(session, artifact, operator_message)

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
                "tool_call_count": completion.tool_call_count,
                "tool_names": completion.tool_names,
            },
        )
        return operator_text, artifact, approval

    def _write_working_memory(
        self,
        session: SessionRecord,
        artifact: WorkflowArtifact,
        operator_message: str,
    ) -> None:
        summary = str(artifact.data.get("plan_summary", "")).strip() or artifact.summary
        assignments = artifact.data.get("assignments", [])
        lines = ["# Account Manager Notes", ""]
        if summary:
            lines.extend(["## Current Plan", "", summary])
        if operator_message.strip():
            lines.extend(["", "## Latest Operator Context", "", operator_message.strip()])
        if isinstance(assignments, list) and assignments:
            lines.extend(["", "## Assignment Focus", ""])
            for assignment in assignments[:5]:
                if not isinstance(assignment, dict):
                    continue
                community_name = str(
                    assignment.get("community_name")
                    or assignment.get("community_handle")
                    or "Community"
                ).strip()
                assigned_account = str(assignment.get("assigned_account", "")).strip()
                risk_level = str(assignment.get("risk_level", "")).strip()
                scheduled_posts = assignment.get("scheduled_posts", [])
                post_count = len(scheduled_posts) if isinstance(scheduled_posts, list) else 0
                details = " | ".join(
                    value
                    for value in [
                        f"account={assigned_account}" if assigned_account else "",
                        f"risk={risk_level}" if risk_level else "",
                        f"posts={post_count}" if post_count else "",
                    ]
                    if value
                )
                lines.append(f"- {community_name}: {details or 'Assignment captured in the latest plan.'}")
        lines.extend(
            [
                "",
                "## Next Account-Planning Move",
                "",
                "Revise this note when pacing, roster availability, or assignment risk changes after operator feedback.",
            ]
        )
        self._memory_manager.write_agent_working_memory(session, "account_manager", "\n".join(lines))

    def _build_account_context(self) -> list[str]:
        if self._runtime_broker is not None:
            roster_summary = self._runtime_broker.build_account_roster_summary()
            if roster_summary:
                return [
                    "Account roster:",
                    json.dumps(roster_summary, ensure_ascii=True, sort_keys=True),
                ]
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
        return strip_marked_block(output, ACCOUNT_ASSIGNMENT_PLAN_JSON_MARKER)

    def _build_invalid_plan_response(self, operator_text: str, validation_error: str) -> str:
        summary = operator_text.strip() or "I generated an account-planning draft, but I could not trust its structured output."
        return (
            f"{summary}\n\n"
            "I did not save this plan because its machine-readable payload was incomplete. "
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
            "verification_summary": data.get("verification_summary"),
            "coverage_summary": data.get("coverage_summary"),
            "verification_counts": data.get("verification_counts"),
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
