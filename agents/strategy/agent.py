"""Strategy planning-surface agent for community-aware messaging playbook generation."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

import anthropic

from telegram_app.agent_runtime import AgentRuntimeBroker
from telegram_app.campaign_memory import CampaignMemoryManager
from telegram_app.capabilities import (
    AccountCapability,
    CommunityCapability,
    MembershipCapability,
    MessagingCapability,
)
from telegram_app.llm import TelegramCapabilityToolbox, resolve_model
from telegram_app.monitoring import NullRuntimeEventLogger, RuntimeEventLogger, RuntimeTraceContext
from telegram_app.models import SessionRecord, WorkflowArtifact, WorkflowArtifactKind
from telegram_app.orchestrator.context_builder import build_runtime_context
from telegram_app.sessions import SessionManager
from telegram_app.workflow_validation import (
    parse_marked_json_block,
    parse_output_proposal_list,
    strip_marked_block,
    validate_strategy_playbook,
)

logger = logging.getLogger(__name__)

# agents/strategy/agent.py -> agents/strategy/ -> agents/ -> tg-swarm/ (repo root)
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

STRATEGY_PLAYBOOK_JSON_MARKER = "STRATEGY_PLAYBOOK_JSON"
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
PROMPT_SAFE_PROFILE_KEYS = (
    "community_id",
    "name",
    "username",
    "type",
    "member_count",
    "verified",
    "restricted",
    "scam",
    "description",
    "linked_chat_id",
    "slowmode_seconds",
)


def _build_profile_snapshot_from_shortlist(community: dict[str, Any]) -> dict[str, object] | None:
    live_profile = community.get("live_profile", {})
    if not isinstance(live_profile, dict):
        return None

    snapshot = {
        key: live_profile.get(key)
        for key in PROMPT_SAFE_PROFILE_KEYS
        if live_profile.get(key) not in ("", [], {}, None)
    }
    if not snapshot:
        return None
    return {
        "community_id": str(
            community.get("handle")
            or community.get("community_id")
            or live_profile.get("community_id")
            or community.get("name")
            or ""
        ).strip(),
        "data": snapshot,
        "source": "persisted_discovery_profile",
    }


def _build_live_profile_lookup_id(community: dict[str, Any]) -> str:
    live_search_match = community.get("live_search_match", {})
    if isinstance(live_search_match, dict):
        username = str(live_search_match.get("username", "")).strip()
        if username:
            return f"@{username}"

    handle = str(community.get("handle", "")).strip()
    if handle:
        return handle

    community_id = str(community.get("community_id", "")).strip()
    if community_id:
        return community_id

    return str(community.get("name", "")).strip()


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


class StrategyAgent:
    """Planning-surface agent for community-aware messaging playbook generation."""

    def __init__(
        self,
        session_manager: SessionManager | None = None,
        account_capability: AccountCapability | None = None,
        community_capability: CommunityCapability | None = None,
        membership_capability: MembershipCapability | None = None,
        messaging_capability: MessagingCapability | None = None,
        monitor: RuntimeEventLogger | None = None,
        runtime_broker: AgentRuntimeBroker | None = None,
    ) -> None:
        self._session_manager = session_manager
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
        self.last_proposal_payloads: list[dict[str, Any]] = []

    def run(
        self,
        session: SessionRecord,
        operator_message: str = "",
        trace_context: RuntimeTraceContext | None = None,
    ) -> tuple[str, WorkflowArtifact | None]:
        """Run strategy turn. Returns (operator_text, strategy_artifact)."""
        trace_context = (
            trace_context
            or RuntimeTraceContext(trace_id="", session_id=session.session_id, user_id=session.operator_id)
        ).with_session(session)
        context_lines = ["Strategy context:"]
        if self._session_manager is not None:
            for kind, label in [
                (WorkflowArtifactKind.CAMPAIGN_BRIEF, "Campaign brief"),
                (WorkflowArtifactKind.COMMUNITY_SHORTLIST, "Community shortlist"),
            ]:
                artifact = _get_latest_artifact_of_kind(self._session_manager, session, kind)
                if artifact is not None:
                    context_lines.append(
                        f"{label}: {json.dumps(_prompt_safe_artifact_data(kind, artifact.data), ensure_ascii=True)}"
                    )
        if operator_message.strip():
            context_lines.append(f"Operator revision context: {operator_message.strip()}")

        capability_context = self._build_capability_context(session)
        user_content = "\n".join(context_lines + capability_context) + "\n\nPlease produce the strategy playbook."

        system = [
            {"type": "text", "text": _load_prompt("strategy.md")},
            {"type": "text", "text": _load_prompt("shared_runtime.md")},
            {
                "type": "text",
                "text": build_runtime_context(
                    session,
                    pending_approval=None,
                    work_type="strategy",
                    agent_runtime_broker=self._runtime_broker,
                ),
            },
        ]
        specialist_memory = self._memory_manager.load_agent_prompt_memory(session, "strategy")
        if specialist_memory:
            system.append(
                {
                    "type": "text",
                    "text": "Strategy specialist working memory:\n"
                    + json.dumps(specialist_memory, ensure_ascii=True, sort_keys=True),
                }
            )
        messages = [{"role": "user", "content": user_content}]

        model = resolve_model()
        logger.info("StrategyAgent calling Anthropic API model=%s", model)
        self._monitor.record_event(
            component="strategy_agent",
            event_type="llm_request",
            trace_context=trace_context,
            session=session,
            payload={
                "model": model,
                "prompt_assets": ["strategy.md", "shared_runtime.md"],
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
                component="strategy_agent",
                event_type="llm_failed",
                trace_context=trace_context,
                session=session,
                payload={"model": model, "error": str(exc), "error_type": type(exc).__name__},
            )
            raise

        final_output = completion.final_output
        self.last_proposal_payloads = parse_output_proposal_list(final_output) or []

        playbook_data = self._parse_playbook_json(final_output)
        operator_text = self._strip_json_block(final_output)
        validation_error = validate_strategy_playbook(playbook_data)

        artifact: WorkflowArtifact | None = None
        if validation_error is not None:
            operator_text = self._build_invalid_playbook_response(operator_text, validation_error)
        elif self._session_manager is not None:
            playbook_summary = str(playbook_data.get("campaign_strategy_summary", "Strategy playbook ready."))
            existing = _get_latest_artifact_of_kind(
                self._session_manager, session, WorkflowArtifactKind.STRATEGY_PLAYBOOK
            )
            if existing is not None:
                existing.data = playbook_data
                existing.summary = playbook_summary
                self._session_manager.save_workflow_artifact(session, existing)
                artifact = existing
            else:
                artifact = self._session_manager.create_workflow_artifact(
                    session=session,
                    kind=WorkflowArtifactKind.STRATEGY_PLAYBOOK,
                    title="Strategy playbook",
                    summary=playbook_summary,
                    data=playbook_data,
                )
        else:
            playbook_summary = str(playbook_data.get("campaign_strategy_summary", "Strategy playbook ready."))
            artifact = WorkflowArtifact(
                artifact_id=str(uuid4()),
                kind=WorkflowArtifactKind.STRATEGY_PLAYBOOK,
                title="Strategy playbook",
                summary=playbook_summary,
                data=playbook_data,
            )
        if artifact is not None:
            self._write_working_memory(session, artifact, operator_message)

        self._monitor.record_event(
            component="strategy_agent",
            event_type="llm_response",
            trace_context=trace_context,
            session=session,
            payload={
                "model": model,
                "output_text": final_output,
                "operator_text": operator_text,
                "artifact_id": artifact.artifact_id if artifact is not None else "",
                "validation_error": validation_error or "",
                "tool_call_count": completion.tool_call_count,
                "tool_names": completion.tool_names,
            },
        )
        return operator_text, artifact

    def _write_working_memory(
        self,
        session: SessionRecord,
        artifact: WorkflowArtifact,
        operator_message: str,
    ) -> None:
        summary = str(artifact.data.get("campaign_strategy_summary", "")).strip() or artifact.summary
        communities = artifact.data.get("communities", [])
        lines = ["# Strategy Notes", ""]
        if summary:
            lines.extend(["## Current Direction", "", summary])
        if operator_message.strip():
            lines.extend(["", "## Latest Operator Context", "", operator_message.strip()])
        if isinstance(communities, list) and communities:
            lines.extend(["", "## Community Tactics", ""])
            for community in communities[:5]:
                if not isinstance(community, dict):
                    continue
                name = str(community.get("name") or community.get("handle") or "Community").strip()
                angle = str(community.get("messaging_angle", "")).strip()
                timing = str(community.get("timing", "")).strip()
                risk_notes = str(community.get("risk_notes", "")).strip()
                details = " | ".join(value for value in [angle, timing, risk_notes] if value)
                lines.append(f"- {name}: {details or 'Tactic captured in the latest playbook.'}")
        lines.extend(
            [
                "",
                "## Next Strategy Move",
                "",
                "Revise this note when operator feedback changes positioning, sequencing, or community-specific guidance.",
            ]
        )
        self._memory_manager.write_agent_working_memory(session, "strategy", "\n".join(lines))

    def _build_capability_context(self, session: SessionRecord) -> list[str]:
        if self._session_manager is None or (
            self._community_capability is None and self._runtime_broker is None
        ):
            return ["Community capability context: unavailable"]

        shortlist = _get_latest_artifact_of_kind(
            self._session_manager,
            session,
            WorkflowArtifactKind.COMMUNITY_SHORTLIST,
        )
        if shortlist is None:
            return ["Community capability context: no shortlist available"]

        profile_snapshots: list[dict[str, object]] = []
        for community in shortlist.data.get("communities", []):
            if not isinstance(community, dict):
                continue

            persisted_snapshot = _build_profile_snapshot_from_shortlist(community)
            if persisted_snapshot is not None:
                profile_snapshots.append(persisted_snapshot)
            else:
                community_id = _build_live_profile_lookup_id(community)
                if not community_id:
                    continue

                live_profile = (
                    self._runtime_broker.get_community_profile_snapshot(community_id)
                    if self._runtime_broker is not None
                    else None
                )
                if live_profile is None and self._community_capability is not None:
                    profile_result = self._community_capability.get_profile(community_id)
                    if profile_result.success:
                        live_profile = _prompt_safe_profile_data(profile_result.data)
                if live_profile is None:
                    continue

                profile_snapshots.append(
                    {
                        "community_id": community_id,
                        "data": live_profile,
                        "source": "live_profile_read",
                    }
                )
            if len(profile_snapshots) >= 5:
                break

        if not profile_snapshots:
            return ["Community capability context: no live profiles available yet"]

        return [
            "Community capability context:",
            json.dumps(profile_snapshots, ensure_ascii=True),
        ]

    def _parse_playbook_json(self, output: str) -> dict:
        return parse_marked_json_block(output, STRATEGY_PLAYBOOK_JSON_MARKER) or {}

    def _strip_json_block(self, output: str) -> str:
        return strip_marked_block(output, STRATEGY_PLAYBOOK_JSON_MARKER)

    def _build_invalid_playbook_response(self, operator_text: str, validation_error: str) -> str:
        summary = operator_text.strip() or "I generated a strategy draft, but I could not trust its structured output."
        return (
            f"{summary}\n\n"
            "I did not save or advance this strategy because its machine-readable playbook was incomplete. "
            f"{validation_error} Please ask me to retry the strategy step."
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

    return data


def _prompt_safe_profile_data(data: dict) -> dict:
    community = data.get("community", {}) if isinstance(data, dict) else {}
    if not isinstance(community, dict):
        return {}
    return {
        key: community.get(key)
        for key in PROMPT_SAFE_PROFILE_KEYS
        if community.get(key) not in ("", [], {}, None)
    }
