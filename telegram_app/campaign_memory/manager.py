"""File-backed campaign memory helpers."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from telegram_app.campaign_intent import (
    AMBIGUITIES_KEY as INTENT_AMBIGUITIES_KEY,
    BUSINESS_CONTEXT_KEY,
    CAMPAIGN_CONSTRAINTS_KEY,
    OFFER_SUMMARY_KEY,
    TARGET_AUDIENCE_SUMMARY_KEY,
)
from telegram_app.campaign_context import (
    EXECUTION_CONSTRAINTS_KEY,
    OPEN_AMBIGUITIES_KEY,
    OPERATOR_PREFERENCES_KEY,
    PERSISTENT_DECISIONS_KEY,
    REVISION_STATUS_ACCEPTED,
    REVISION_STATUS_ACTIVE,
    REVISION_THREADS_KEY,
    SCOPE_KEY,
    STATUS_KEY,
    SUMMARY_KEY,
    VOICE_AVOID_TRAITS_KEY,
    VOICE_CTA_PREFERENCES_KEY,
    VOICE_PREFERRED_TRAITS_KEY,
    VOICE_PROFILE_KEY,
    VOICE_STYLE_NOTES_KEY,
)
from telegram_app.conversion_target import (
    DESTINATION_KIND_KEY as CONVERSION_DESTINATION_KIND_KEY,
    NORMALIZED_VALUE_KEY as CONVERSION_NORMALIZED_VALUE_KEY,
    RAW_VALUE_KEY as CONVERSION_RAW_VALUE_KEY,
    build_conversion_target_summary,
)
from telegram_app.intake import (
    CONSTRAINTS_KEY,
    GEOGRAPHY_KEY,
    LANGUAGE_KEY,
    NOTES_KEY,
    OBJECTIVE_KEY,
    OFFER_KEY,
    SOURCE_MESSAGES_KEY,
    SUCCESS_CRITERIA_KEY,
    TARGET_AUDIENCE_KEY,
    get_campaign_brief_artifact,
    get_workflow_snapshot,
)
from telegram_app.json_store import load_json_file, write_json_file
from telegram_app.models import (
    CampaignRecord,
    SessionRecord,
    SessionStatus,
    WorkflowArtifact,
    WorkflowArtifactKind,
    WorkflowSnapshot,
    WorkflowStage,
)
from telegram_app.campaign_memory.operational_notes import (
    CampaignOperationalNotesStore,
    EXECUTION_LOG_DESTINATION,
    NEXT_ACTIONS_DESTINATION,
    OperationalNote,
)

MESSAGE_HISTORY_KEY = "message_history"
WORKFLOW_SNAPSHOT_KEY = "workflow_snapshot"
WORKFLOW_ARTIFACTS_KEY = "workflow_artifacts"
COMMUNITIES_INDEX_PATH = "communities/index.md"

DEFAULT_CANONICAL_MEMORY_FILES = (
    "overview.md",
    "operator-intent.md",
    "strategy.md",
    "research-log.md",
    "personas.md",
    "experiments.md",
    "next-actions.md",
    "execution-log.md",
)
DEFAULT_AGENT_MEMORY_FILES = (
    "agents/orchestrator.md",
    "agents/discovery.md",
    "agents/strategy.md",
    "agents/account_manager.md",
)
AGENT_ROLE_TO_MEMORY_FILE = {
    "orchestrator": "agents/orchestrator.md",
    "discovery": "agents/discovery.md",
    "strategy": "agents/strategy.md",
    "account_manager": "agents/account_manager.md",
}
_DEFAULT_WORKSPACE_DIRECTORIES = (
    "communities",
    "agents",
    "assets",
    "snapshots",
    "artifacts",
)
_DEFAULT_FILE_CONTENT = {
    "overview.md": "# Overview\n\nCampaign summary will accumulate here.\n",
    "operator-intent.md": "# Operator Intent\n\nOperator goals and constraints will accumulate here.\n",
    "strategy.md": "# Strategy\n\nCurrent strategy direction will accumulate here.\n",
    "research-log.md": "# Research Log\n\nDiscovery findings and research notes will accumulate here.\n",
    "personas.md": "# Personas\n\nAudience and persona notes will accumulate here.\n",
    "experiments.md": "# Experiments\n\nPlanned and completed experiments will accumulate here.\n",
    "next-actions.md": "# Next Actions\n\nRecommended next actions and blockers will accumulate here.\n",
    "execution-log.md": "# Execution Log\n\nExecution notes and operational outcomes will accumulate here.\n",
    "communities/index.md": "# Communities\n\nCommunity-specific memory files will be listed here.\n",
    "agents/orchestrator.md": "# Orchestrator Notes\n\nCross-functional campaign coordination notes will accumulate here.\n",
    "agents/discovery.md": "# Discovery Notes\n\nDiscovery-specific notes will accumulate here.\n",
    "agents/strategy.md": "# Strategy Notes\n\nStrategy-specific notes will accumulate here.\n",
    "agents/account_manager.md": "# Account Manager Notes\n\nAccount-planning notes will accumulate here.\n",
}
_ARTIFACT_FILE_NAMES = {
    WorkflowArtifactKind.CAMPAIGN_INTENT: "artifacts/campaign_intent.json",
    WorkflowArtifactKind.CAMPAIGN_CONTEXT: "artifacts/campaign_context.json",
    WorkflowArtifactKind.CONVERSION_TARGET: "artifacts/conversion_target.json",
    WorkflowArtifactKind.CAMPAIGN_BRIEF: "artifacts/campaign_brief.json",
    WorkflowArtifactKind.COMMUNITY_SHORTLIST: "artifacts/community_shortlist.json",
    WorkflowArtifactKind.STRATEGY_PLAYBOOK: "artifacts/strategy_playbook.json",
    WorkflowArtifactKind.ACCOUNT_ASSIGNMENT_PLAN: "artifacts/account_assignment_plan.json",
}
_MEMORY_SNIPPET_FILE_LIMIT = 1200
_MEMORY_SNIPPET_TOTAL_LIMIT = 6000


class CampaignMemoryManager:
    """Manage the file-backed campaign memory workspace."""

    def __init__(self) -> None:
        self._operational_notes = CampaignOperationalNotesStore()

    def bootstrap_workspace(self, campaign: CampaignRecord) -> CampaignRecord:
        """Create the default workspace structure and normalize tracked file lists."""
        workspace = Path(campaign.workspace_path)
        workspace.mkdir(parents=True, exist_ok=True)
        for directory_name in _DEFAULT_WORKSPACE_DIRECTORIES:
            (workspace / directory_name).mkdir(parents=True, exist_ok=True)

        canonical_files = self._normalize_file_list(
            campaign.canonical_files,
            DEFAULT_CANONICAL_MEMORY_FILES,
        )
        agent_files = self._normalize_file_list(
            campaign.agent_memory_files,
            DEFAULT_AGENT_MEMORY_FILES,
        )
        for relative_path in [*canonical_files, *agent_files, COMMUNITIES_INDEX_PATH]:
            self._ensure_file(workspace, relative_path)

        campaign.canonical_files = canonical_files
        campaign.agent_memory_files = agent_files
        return campaign

    def load_prompt_memory(
        self,
        session: SessionRecord,
        *,
        max_chars_per_file: int = _MEMORY_SNIPPET_FILE_LIMIT,
        max_total_chars: int = _MEMORY_SNIPPET_TOTAL_LIMIT,
    ) -> dict[str, str]:
        """Load compact canonical campaign memory snippets for prompt context."""
        if not session.campaign_workspace_path:
            return {}

        workspace = Path(session.campaign_workspace_path)
        remaining = max_total_chars
        memory: dict[str, str] = {}
        for relative_path in session.canonical_memory_files or DEFAULT_CANONICAL_MEMORY_FILES:
            if remaining <= 0:
                break
            file_path = workspace / relative_path
            if not file_path.exists() or not file_path.is_file():
                continue
            content = file_path.read_text(encoding="utf-8").strip()
            if not content:
                continue
            truncated = content[: min(max_chars_per_file, remaining)]
            memory[relative_path] = truncated
            remaining -= len(truncated)
        return memory

    def load_agent_prompt_memory(
        self,
        session: SessionRecord,
        owner_role: str,
        *,
        max_chars: int = _MEMORY_SNIPPET_FILE_LIMIT,
    ) -> dict[str, str]:
        """Load one specialist-owned working-memory file for prompt context."""
        if not session.campaign_workspace_path:
            return {}

        relative_path = self._agent_memory_relative_path(session, owner_role)
        if not relative_path:
            return {}

        content = self._read_workspace_text(
            Path(session.campaign_workspace_path),
            relative_path,
            max_chars=max_chars,
        )
        if not content:
            return {}
        return {relative_path: content}

    def write_agent_working_memory(
        self,
        session: SessionRecord,
        owner_role: str,
        content: str,
    ) -> None:
        """Persist deliberate specialist working memory for one role."""
        if not session.campaign_workspace_path:
            return

        relative_path = self._agent_memory_relative_path(session, owner_role)
        if not relative_path:
            return

        workspace = Path(session.campaign_workspace_path)
        self._ensure_file(workspace, relative_path)
        self._write_text_file(workspace / relative_path, content.strip() + "\n")

    def load_compatibility_artifacts(self, workspace_path: str | Path) -> list[WorkflowArtifact]:
        """Load compatibility artifact views persisted under the campaign workspace."""
        workspace = Path(workspace_path)
        artifacts: list[WorkflowArtifact] = []
        for relative_path in _ARTIFACT_FILE_NAMES.values():
            payload = load_json_file(workspace / relative_path, default={})
            if not isinstance(payload, dict):
                continue
            artifact = WorkflowArtifact.from_dict(payload)
            if artifact.artifact_id:
                artifacts.append(artifact)
        return artifacts

    def hydrate_session(self, session: SessionRecord) -> SessionRecord:
        """Merge campaign-backed compatibility views into a session when needed."""
        if not session.campaign_workspace_path:
            return session

        current_artifacts = self._load_session_artifacts(session)
        if current_artifacts:
            return session

        loaded_artifacts = self.load_compatibility_artifacts(session.campaign_workspace_path)
        if not loaded_artifacts:
            return session

        session.workflow_state[WORKFLOW_ARTIFACTS_KEY] = [artifact.to_dict() for artifact in loaded_artifacts]
        current_snapshot = get_workflow_snapshot(session)
        if current_snapshot.stage is WorkflowStage.INTAKE:
            session.workflow_state[WORKFLOW_SNAPSHOT_KEY] = self._snapshot_from_artifacts(
                loaded_artifacts,
                session=session,
            ).to_dict()
        return session

    def build_background_session(
        self,
        campaign: CampaignRecord,
        *,
        stage: WorkflowStage,
        summary: str,
    ) -> SessionRecord:
        """Build an in-memory session-like view from campaign memory for background work."""
        artifacts = self.load_compatibility_artifacts(campaign.workspace_path)
        snapshot = self._snapshot_from_artifacts(artifacts)
        snapshot = replace(
            snapshot,
            stage=stage,
            summary=summary,
            data={
                **snapshot.data,
                "campaign_id": campaign.campaign_id,
                "campaign_workspace_path": campaign.workspace_path,
                "scheduled_background_run": True,
            },
        )
        return SessionRecord(
            session_id=f"scheduled-{campaign.campaign_id}-{uuid4()}",
            operator_id=campaign.operator_id,
            campaign_id=campaign.campaign_id,
            campaign_workspace_path=campaign.workspace_path,
            canonical_memory_files=list(campaign.canonical_files or DEFAULT_CANONICAL_MEMORY_FILES),
            agent_memory_files=list(campaign.agent_memory_files or DEFAULT_AGENT_MEMORY_FILES),
            status=SessionStatus.ACTIVE,
            workflow_state={
                MESSAGE_HISTORY_KEY: [],
                WORKFLOW_SNAPSHOT_KEY: snapshot.to_dict(),
                WORKFLOW_ARTIFACTS_KEY: [artifact.to_dict() for artifact in artifacts],
            },
        )

    def refresh_campaign_workspace(self, campaign: CampaignRecord) -> None:
        """Re-render campaign memory from the current durable artifact and note state."""
        artifacts = self.load_compatibility_artifacts(campaign.workspace_path)
        snapshot = self._snapshot_from_artifacts(artifacts)
        session = SessionRecord(
            session_id=f"memory-refresh-{campaign.campaign_id}-{uuid4()}",
            operator_id=campaign.operator_id,
            campaign_id=campaign.campaign_id,
            campaign_workspace_path=campaign.workspace_path,
            canonical_memory_files=list(campaign.canonical_files or DEFAULT_CANONICAL_MEMORY_FILES),
            agent_memory_files=list(campaign.agent_memory_files or DEFAULT_AGENT_MEMORY_FILES),
            status=SessionStatus.ACTIVE,
            workflow_state={
                MESSAGE_HISTORY_KEY: [],
                WORKFLOW_SNAPSHOT_KEY: snapshot.to_dict(),
                WORKFLOW_ARTIFACTS_KEY: [artifact.to_dict() for artifact in artifacts],
            },
        )
        self.sync_session(session)

    def sync_session(self, session: SessionRecord) -> None:
        """Write campaign memory markdown and compatibility artifacts from session state."""
        if not session.campaign_workspace_path:
            return

        workspace = Path(session.campaign_workspace_path)
        from telegram_app.continuous_ops.storage import load_continuous_ops_state_for_workspace

        workspace.mkdir(parents=True, exist_ok=True)
        for directory_name in _DEFAULT_WORKSPACE_DIRECTORIES:
            (workspace / directory_name).mkdir(parents=True, exist_ok=True)

        artifacts = self._artifact_map(session)
        snapshot = get_workflow_snapshot(session)
        intent = artifacts.get(WorkflowArtifactKind.CAMPAIGN_INTENT)
        campaign_context = artifacts.get(WorkflowArtifactKind.CAMPAIGN_CONTEXT)
        conversion_target = artifacts.get(WorkflowArtifactKind.CONVERSION_TARGET)
        brief = artifacts.get(WorkflowArtifactKind.CAMPAIGN_BRIEF)
        shortlist = artifacts.get(WorkflowArtifactKind.COMMUNITY_SHORTLIST)
        strategy = artifacts.get(WorkflowArtifactKind.STRATEGY_PLAYBOOK)
        account_plan = artifacts.get(WorkflowArtifactKind.ACCOUNT_ASSIGNMENT_PLAN)
        continuous_ops_state = load_continuous_ops_state_for_workspace(workspace)
        operational_notes = self._operational_notes.list_notes(workspace)

        files_to_ensure = [
            *(session.canonical_memory_files or DEFAULT_CANONICAL_MEMORY_FILES),
            *(session.agent_memory_files or DEFAULT_AGENT_MEMORY_FILES),
            COMMUNITIES_INDEX_PATH,
        ]
        for relative_path in files_to_ensure:
            self._ensure_file(workspace, relative_path)

        rendered_files = {
            "overview.md": self._render_overview(
                session,
                snapshot,
                intent,
                campaign_context,
                conversion_target,
                brief,
                shortlist,
                strategy,
                account_plan,
                continuous_ops_state=continuous_ops_state,
            ),
            "operator-intent.md": self._render_operator_intent(
                session,
                intent,
                campaign_context,
                conversion_target,
                brief,
            ),
            "strategy.md": self._render_strategy(session, strategy, shortlist),
            "research-log.md": self._render_research_log(shortlist),
            "personas.md": self._render_personas(brief, strategy, campaign_context),
            "experiments.md": self._render_experiments(strategy),
            "next-actions.md": self._render_next_actions(
                snapshot,
                shortlist,
                strategy,
                account_plan,
                continuous_ops_state=continuous_ops_state,
                operational_notes=self._notes_for_destination(operational_notes, NEXT_ACTIONS_DESTINATION),
            ),
            "execution-log.md": self._render_execution_log(
                account_plan,
                operational_notes=self._notes_for_destination(operational_notes, EXECUTION_LOG_DESTINATION),
            ),
            "agents/orchestrator.md": self._render_orchestrator_notes(snapshot),
        }
        for relative_path, content in rendered_files.items():
            self._write_text_file(workspace / relative_path, content)

        self._sync_community_memory(workspace, shortlist)
        self._sync_artifact_views(workspace, artifacts)

    def append_operational_note(
        self,
        campaign: CampaignRecord,
        *,
        destination: str,
        line: str,
        category: str = "",
        dedupe_key: str = "",
        recorded_at: datetime | None = None,
    ) -> OperationalNote | None:
        """Persist one sparse operational note for later campaign-memory rendering."""
        if not campaign.workspace_path:
            return None
        return self._operational_notes.append_note(
            campaign.workspace_path,
            destination=destination,
            line=line,
            category=category,
            dedupe_key=dedupe_key,
            recorded_at=recorded_at,
        )

    def persist_generated_artifact(
        self,
        campaign: CampaignRecord,
        artifact: WorkflowArtifact,
        *,
        stage: WorkflowStage,
        summary: str,
    ) -> None:
        """Persist a new compatibility artifact by re-rendering campaign memory around it."""
        session = self.build_background_session(campaign, stage=stage, summary=summary)
        artifacts = self._artifact_map(session)
        artifacts[artifact.kind] = artifact
        session.workflow_state[WORKFLOW_ARTIFACTS_KEY] = [
            stored_artifact.to_dict()
            for stored_artifact in artifacts.values()
        ]
        session.workflow_state[WORKFLOW_SNAPSHOT_KEY] = WorkflowSnapshot(
            stage=stage,
            summary=summary,
            data={
                "campaign_id": campaign.campaign_id,
                "campaign_workspace_path": campaign.workspace_path,
                f"{artifact.kind.value}_artifact_id": artifact.artifact_id,
            },
        ).to_dict()
        self.sync_session(session)

    def _artifact_map(self, session: SessionRecord) -> dict[WorkflowArtifactKind, WorkflowArtifact]:
        artifacts: dict[WorkflowArtifactKind, WorkflowArtifact] = {}
        for artifact in self._load_session_artifacts(session):
            existing = artifacts.get(artifact.kind)
            if existing is None or artifact.updated_at >= existing.updated_at:
                artifacts[artifact.kind] = artifact
        return artifacts

    def _load_session_artifacts(self, session: SessionRecord) -> list[WorkflowArtifact]:
        payloads = session.workflow_state.get(WORKFLOW_ARTIFACTS_KEY, [])
        if not isinstance(payloads, list):
            return []
        return [
            WorkflowArtifact.from_dict(payload)
            for payload in payloads
            if isinstance(payload, dict)
        ]

    def _snapshot_from_artifacts(
        self,
        artifacts: list[WorkflowArtifact],
        *,
        session: SessionRecord | None = None,
    ) -> WorkflowSnapshot:
        artifact_map = {
            artifact.kind: artifact
            for artifact in artifacts
        }
        data: dict[str, Any] = {}
        if session is not None:
            if session.campaign_id:
                data["campaign_id"] = session.campaign_id
            if session.campaign_workspace_path:
                data["campaign_workspace_path"] = session.campaign_workspace_path
        self._append_conversion_target_snapshot_data(data, artifact_map)

        if WorkflowArtifactKind.ACCOUNT_ASSIGNMENT_PLAN in artifact_map:
            artifact = artifact_map[WorkflowArtifactKind.ACCOUNT_ASSIGNMENT_PLAN]
            data["account_assignment_plan_artifact_id"] = artifact.artifact_id
            return WorkflowSnapshot(
                stage=WorkflowStage.ACCOUNT_PLANNING,
                summary="Campaign memory has an account assignment plan ready for review.",
                data=data,
            )
        if WorkflowArtifactKind.STRATEGY_PLAYBOOK in artifact_map:
            artifact = artifact_map[WorkflowArtifactKind.STRATEGY_PLAYBOOK]
            data["strategy_playbook_artifact_id"] = artifact.artifact_id
            return WorkflowSnapshot(
                stage=WorkflowStage.STRATEGY,
                summary="Campaign memory has a strategy playbook ready for review.",
                data=data,
            )
        if WorkflowArtifactKind.COMMUNITY_SHORTLIST in artifact_map:
            artifact = artifact_map[WorkflowArtifactKind.COMMUNITY_SHORTLIST]
            data["community_shortlist_artifact_id"] = artifact.artifact_id
            return WorkflowSnapshot(
                stage=WorkflowStage.DISCOVERY,
                summary="Campaign memory has a community shortlist ready for review.",
                data=data,
            )
        if WorkflowArtifactKind.CAMPAIGN_BRIEF in artifact_map:
            artifact = artifact_map[WorkflowArtifactKind.CAMPAIGN_BRIEF]
            brief_data = artifact.data
            data["campaign_brief_artifact_id"] = artifact.artifact_id
            data["objective"] = str(brief_data.get(OBJECTIVE_KEY, "")).strip()
            data["target_audience"] = str(brief_data.get(TARGET_AUDIENCE_KEY, "")).strip()
            return WorkflowSnapshot(
                stage=WorkflowStage.DISCOVERY,
                summary="Campaign memory has a campaign brief ready for discovery work.",
                data=data,
            )
        return WorkflowSnapshot(stage=WorkflowStage.INTAKE, summary="Campaign memory workspace is initialized.", data=data)

    def _sync_artifact_views(
        self,
        workspace: Path,
        artifacts: dict[WorkflowArtifactKind, WorkflowArtifact],
    ) -> None:
        for kind, relative_path in _ARTIFACT_FILE_NAMES.items():
            file_path = workspace / relative_path
            artifact = artifacts.get(kind)
            if artifact is None:
                if file_path.exists():
                    file_path.unlink()
                continue
            write_json_file(file_path, artifact.to_dict())

    def _sync_community_memory(
        self,
        workspace: Path,
        shortlist: WorkflowArtifact | None,
    ) -> None:
        communities_dir = workspace / "communities"
        communities_dir.mkdir(parents=True, exist_ok=True)
        entries: list[tuple[str, str]] = []
        communities = shortlist.data.get("communities", []) if shortlist is not None else []
        if isinstance(communities, list):
            for community in communities:
                if not isinstance(community, dict):
                    continue
                title = str(
                    community.get("name")
                    or community.get("handle")
                    or community.get("community_id")
                    or "Community"
                ).strip()
                slug = self._slugify(title) or "community"
                relative_path = f"communities/{slug}.md"
                entries.append((title, relative_path))
                content_lines = [
                    f"# {title}",
                    "",
                    f"- Handle: {community.get('handle', 'n/a')}",
                    f"- Community ID: {community.get('community_id', 'n/a')}",
                    f"- Type: {community.get('type', 'n/a')}",
                    f"- Geography: {community.get('geography', 'n/a')}",
                    f"- Verification state: {community.get('verification_state', 'unknown')}",
                ]
                reason = str(community.get("reason", "")).strip()
                evidence = str(community.get("evidence_summary", "")).strip()
                if reason:
                    content_lines.extend(["", "## Why It Matters", "", reason])
                if evidence:
                    content_lines.extend(["", "## Evidence", "", evidence])
                self._write_text_file(workspace / relative_path, "\n".join(content_lines).strip() + "\n")

        index_lines = ["# Communities", ""]
        if not entries:
            index_lines.append("Community-specific memory files will appear here after discovery runs.")
        else:
            index_lines.append("## Active Community Memory")
            index_lines.append("")
            for title, relative_path in entries:
                index_lines.append(f"- {title}: `{relative_path}`")
        self._write_text_file(workspace / COMMUNITIES_INDEX_PATH, "\n".join(index_lines).strip() + "\n")

    def _agent_memory_relative_path(self, session: SessionRecord, owner_role: str) -> str | None:
        preferred_path = AGENT_ROLE_TO_MEMORY_FILE.get(owner_role)
        if not preferred_path:
            return None

        tracked_files = session.agent_memory_files or list(DEFAULT_AGENT_MEMORY_FILES)
        if preferred_path in tracked_files:
            return preferred_path
        if preferred_path in DEFAULT_AGENT_MEMORY_FILES:
            return preferred_path
        return None

    def _read_workspace_text(
        self,
        workspace: Path,
        relative_path: str,
        *,
        max_chars: int,
    ) -> str:
        file_path = workspace / relative_path
        if not file_path.exists() or not file_path.is_file():
            return ""

        content = file_path.read_text(encoding="utf-8").strip()
        if not content:
            return ""
        return content[:max_chars]

    def _render_overview(
        self,
        session: SessionRecord,
        snapshot: WorkflowSnapshot,
        intent: WorkflowArtifact | None,
        campaign_context: WorkflowArtifact | None,
        conversion_target: WorkflowArtifact | None,
        brief: WorkflowArtifact | None,
        shortlist: WorkflowArtifact | None,
        strategy: WorkflowArtifact | None,
        account_plan: WorkflowArtifact | None,
        *,
        continuous_ops_state,
    ) -> str:
        objective = self._brief_value(brief, OBJECTIVE_KEY) or self._intent_value(intent, BUSINESS_CONTEXT_KEY) or snapshot.data.get("objective", "")
        audience = self._brief_value(brief, TARGET_AUDIENCE_KEY) or self._intent_value(intent, TARGET_AUDIENCE_SUMMARY_KEY)
        geography = self._brief_value(brief, GEOGRAPHY_KEY)
        conversion_summary = build_conversion_target_summary(conversion_target.data) if conversion_target is not None else ""
        lines = [
            "# Overview",
            "",
            "## Current Campaign Picture",
            "",
            f"- Campaign ID: {session.campaign_id or 'unattached'}",
            f"- Current workflow stage: {snapshot.stage.value}",
            f"- Workflow summary: {snapshot.summary or 'No summary yet.'}",
        ]
        if objective:
            lines.append(f"- Primary objective: {objective}")
        if audience:
            lines.append(f"- Target audience: {audience}")
        if geography:
            lines.append(f"- Geography: {geography}")
        if conversion_summary and conversion_summary != "Conversion target is not set.":
            lines.append(f"- Conversion target: {conversion_summary}")
        lines.extend(
            [
                "",
                "## Memory Status",
                "",
                f"- Campaign intent: {'present' if intent is not None else 'missing'}",
                f"- Campaign context: {'present' if campaign_context is not None else 'missing'}",
                f"- Conversion target: {'present' if conversion_target is not None else 'missing'}",
                f"- Campaign brief: {'present' if brief is not None else 'missing'}",
                f"- Discovery shortlist: {'present' if shortlist is not None else 'missing'}",
                f"- Strategy playbook: {'present' if strategy is not None else 'missing'}",
                f"- Account plan: {'present' if account_plan is not None else 'missing'}",
            ]
        )
        if continuous_ops_state is not None:
            lines.extend(
                [
                    "",
                    "## Continuous Operations",
                    "",
                    f"- Autonomy mode: {continuous_ops_state.autonomy_mode.value}",
                    f"- Loop status: {continuous_ops_state.loop_status.value}",
                f"- Status summary: {continuous_ops_state.status_summary or 'No summary yet.'}",
                f"- Active schedules: {len(continuous_ops_state.active_schedule_ids)}",
                f"- Active work types: {', '.join(continuous_ops_state.active_work_types) or 'none'}",
                f"- Reviewable signals: {continuous_ops_state.reviewable_signal_count}",
                f"- Commercial summary: {continuous_ops_state.commercial_summary or 'No meaningful commercial traction yet.'}",
            ]
        )
            if continuous_ops_state.high_yield_account_labels:
                lines.append(
                    "- High-yield accounts: "
                    + ", ".join(continuous_ops_state.high_yield_account_labels)
                )
            if continuous_ops_state.high_yield_community_labels:
                lines.append(
                    "- High-yield communities: "
                    + ", ".join(continuous_ops_state.high_yield_community_labels)
                )
            if continuous_ops_state.blocked_reasons:
                lines.append(
                    "- Current blockers: "
                    + "; ".join(continuous_ops_state.blocked_reasons)
                )
        return "\n".join(lines).strip() + "\n"

    def _render_operator_intent(
        self,
        session: SessionRecord,
        intent: WorkflowArtifact | None,
        campaign_context: WorkflowArtifact | None,
        conversion_target: WorkflowArtifact | None,
        brief: WorkflowArtifact | None,
    ) -> str:
        lines = ["# Operator Intent", ""]
        if brief is None and intent is None and campaign_context is None and conversion_target is None:
            lines.append("Operator goals and constraints will accumulate here.")
            return "\n".join(lines).strip() + "\n"

        objective = self._brief_value(brief, OBJECTIVE_KEY) or self._intent_value(intent, BUSINESS_CONTEXT_KEY)
        audience = self._brief_value(brief, TARGET_AUDIENCE_KEY) or self._intent_value(intent, TARGET_AUDIENCE_SUMMARY_KEY)
        offer = self._brief_value(brief, OFFER_KEY) or self._intent_value(intent, OFFER_SUMMARY_KEY)
        geography = self._brief_value(brief, GEOGRAPHY_KEY)
        language = self._brief_value(brief, LANGUAGE_KEY)
        lines.extend(
            [
                f"- Objective: {objective or 'n/a'}",
                f"- Target audience: {audience or 'n/a'}",
                f"- Offer: {offer or 'n/a'}",
                f"- Geography: {geography or 'n/a'}",
                f"- Language: {language or 'n/a'}",
            ]
        )
        if conversion_target is not None:
            lines.append(f"- Conversion target: {build_conversion_target_summary(conversion_target.data)}")
        brief_data = brief.data if brief is not None else {}
        constraints = brief_data.get(CONSTRAINTS_KEY, []) or self._intent_list(intent, CAMPAIGN_CONSTRAINTS_KEY)
        self._append_string_list(lines, "Constraints", constraints)
        self._append_string_list(lines, "Success criteria", brief_data.get(SUCCESS_CRITERIA_KEY, []))
        self._append_string_list(lines, "Ambiguities", self._intent_list(intent, INTENT_AMBIGUITIES_KEY))
        self._append_string_list(lines, "Notes", brief_data.get(NOTES_KEY, []))
        self._append_campaign_context_sections(lines, campaign_context)
        self._append_string_list(lines, "Source messages", brief_data.get(SOURCE_MESSAGES_KEY, []))
        if not objective and session.latest_operator_message:
            lines.extend(["", "## Latest Operator Message", "", session.latest_operator_message])
        return "\n".join(lines).strip() + "\n"

    def _render_strategy(
        self,
        session: SessionRecord,
        strategy: WorkflowArtifact | None,
        shortlist: WorkflowArtifact | None,
    ) -> str:
        lines = ["# Strategy", ""]
        if strategy is None:
            objective = self._brief_value(get_campaign_brief_artifact(session), OBJECTIVE_KEY)
            if objective:
                lines.append(f"Current objective: {objective}")
                lines.append("")
            lines.append("Current strategy direction will accumulate here.")
            return "\n".join(lines).strip() + "\n"

        summary = str(strategy.data.get("campaign_strategy_summary", "")).strip() or strategy.summary
        lines.extend(["## Current Direction", "", summary or "Strategy playbook is available."])
        communities = strategy.data.get("communities", [])
        if isinstance(communities, list) and communities:
            lines.extend(["", "## Community Tactics", ""])
            for community in communities:
                if not isinstance(community, dict):
                    continue
                name = str(community.get("name") or community.get("handle") or "Community").strip()
                angle = str(community.get("messaging_angle", "")).strip()
                frequency = str(community.get("frequency", "")).strip()
                timing = str(community.get("timing", "")).strip()
                lines.append(
                    f"- {name}: angle={angle or 'n/a'} | frequency={frequency or 'n/a'} | timing={timing or 'n/a'}"
                )
        elif shortlist is not None:
            lines.extend(["", "Discovery shortlist exists, but the strategy playbook has not expanded it into tactics yet."])
        return "\n".join(lines).strip() + "\n"

    def _render_research_log(self, shortlist: WorkflowArtifact | None) -> str:
        lines = ["# Research Log", ""]
        if shortlist is None:
            lines.append("Discovery findings and research notes will accumulate here.")
            return "\n".join(lines).strip() + "\n"

        summary = str(shortlist.data.get("summary", "")).strip() or shortlist.summary
        verification_summary = str(shortlist.data.get("verification_summary", "")).strip()
        coverage_summary = str(shortlist.data.get("coverage_summary", "")).strip()
        lines.extend(["## Latest Discovery Summary", "", summary or "Discovery shortlist available."])
        if verification_summary:
            lines.extend(["", "## Verification Summary", "", verification_summary])
        if coverage_summary:
            lines.extend(["", "## Coverage Summary", "", coverage_summary])
        communities = shortlist.data.get("communities", [])
        if isinstance(communities, list) and communities:
            lines.extend(["", "## Current Community Notes", ""])
            for community in communities:
                if not isinstance(community, dict):
                    continue
                name = str(community.get("name") or community.get("handle") or "Community").strip()
                verification_state = str(community.get("verification_state", "")).strip() or "unknown"
                evidence = str(community.get("evidence_summary", "")).strip()
                lines.append(f"- {name} [{verification_state}]: {evidence or 'No evidence summary yet.'}")
        return "\n".join(lines).strip() + "\n"

    def _render_personas(
        self,
        brief: WorkflowArtifact | None,
        strategy: WorkflowArtifact | None,
        campaign_context: WorkflowArtifact | None,
    ) -> str:
        lines = ["# Personas", ""]
        audience = self._brief_value(brief, TARGET_AUDIENCE_KEY)
        language = self._brief_value(brief, LANGUAGE_KEY)
        geography = self._brief_value(brief, GEOGRAPHY_KEY)
        voice_profile = campaign_context.data.get(VOICE_PROFILE_KEY, {}) if campaign_context is not None else {}
        preferred_traits = self._context_voice_list(voice_profile, VOICE_PREFERRED_TRAITS_KEY)
        avoid_traits = self._context_voice_list(voice_profile, VOICE_AVOID_TRAITS_KEY)
        style_notes = self._context_voice_list(voice_profile, VOICE_STYLE_NOTES_KEY)
        cta_preferences = self._context_voice_list(voice_profile, VOICE_CTA_PREFERENCES_KEY)
        if not any((audience, language, geography, strategy is not None, preferred_traits, avoid_traits, style_notes, cta_preferences)):
            lines.append("Audience and persona notes will accumulate here.")
            return "\n".join(lines).strip() + "\n"

        lines.extend(
            [
                f"- Primary audience: {audience or 'n/a'}",
                f"- Language expectations: {language or 'n/a'}",
                f"- Geography focus: {geography or 'n/a'}",
            ]
        )
        if strategy is not None:
            lines.extend(["", "Use the current strategy playbook to refine tone and persona assumptions."])
        self._append_string_list(lines, "Preferred voice traits", preferred_traits)
        self._append_string_list(lines, "Voice traits to avoid", avoid_traits)
        self._append_string_list(lines, "Voice style notes", style_notes)
        self._append_string_list(lines, "CTA preferences", cta_preferences)
        return "\n".join(lines).strip() + "\n"

    def _render_experiments(self, strategy: WorkflowArtifact | None) -> str:
        lines = ["# Experiments", ""]
        if strategy is None:
            lines.append("Planned and completed experiments will accumulate here.")
            return "\n".join(lines).strip() + "\n"

        lines.extend(["## Candidate Experiments", ""])
        communities = strategy.data.get("communities", [])
        if isinstance(communities, list) and communities:
            for community in communities:
                if not isinstance(community, dict):
                    continue
                name = str(community.get("name") or community.get("handle") or "Community").strip()
                angle = str(community.get("messaging_angle", "")).strip()
                message_format = str(community.get("message_format", "")).strip()
                lines.append(
                    f"- Test `{angle or 'current messaging angle'}` in {name} using {message_format or 'the recommended message format'}."
                )
        else:
            lines.append("Strategy exists, but no community-specific experiments are spelled out yet.")
        return "\n".join(lines).strip() + "\n"

    def _render_next_actions(
        self,
        snapshot: WorkflowSnapshot,
        shortlist: WorkflowArtifact | None,
        strategy: WorkflowArtifact | None,
        account_plan: WorkflowArtifact | None,
        *,
        continuous_ops_state,
        operational_notes: list[OperationalNote],
    ) -> str:
        lines = ["# Next Actions", ""]
        lines.append(f"- Current stage: {snapshot.stage.value}")
        lines.append(f"- Current summary: {snapshot.summary or 'No summary yet.'}")
        if continuous_ops_state is not None:
            lines.append(
                f"- Continuous ops status: {continuous_ops_state.loop_status.value} - "
                f"{continuous_ops_state.status_summary or 'No summary yet.'}"
            )
            if continuous_ops_state.commercial_summary:
                lines.append(f"- Commercial traction: {continuous_ops_state.commercial_summary}")
            if continuous_ops_state.blocked_reasons:
                lines.append(f"- Current blocker: {continuous_ops_state.blocked_reasons[0]}")
        if snapshot.stage is WorkflowStage.DISCOVERY:
            recommended = str(shortlist.data.get("recommended_next_step", "")).strip() if shortlist is not None else ""
            lines.append(f"- Recommended next step: {recommended or 'Refresh or review the discovery shortlist.'}")
        elif snapshot.stage is WorkflowStage.STRATEGY:
            lines.append("- Recommended next step: Review or refine the strategy playbook.")
        elif snapshot.stage is WorkflowStage.ACCOUNT_PLANNING:
            if "approved" in snapshot.summary.lower():
                lines.append(
                    "- Recommended next step: Prepare execution or refresh the account assignment plan when campaign conditions change."
                )
            else:
                lines.append("- Recommended next step: Review or refine the account assignment plan.")
        elif snapshot.stage is WorkflowStage.COMPLETE:
            lines.append("- Recommended next step: Prepare execution or schedule follow-up reviews.")
        else:
            lines.append("- Recommended next step: Complete the campaign brief so discovery can start.")

        if strategy is not None and snapshot.stage is not WorkflowStage.ACCOUNT_PLANNING:
            lines.append("- Strategy playbook exists and can be used for downstream planning.")
        if account_plan is not None:
            lines.append("- Account assignment plan exists and is ready for operator review.")
        if operational_notes:
            lines.extend(["", "## Live Engagement Follow-Ups", ""])
            for note in sorted(operational_notes, key=lambda item: item.recorded_at, reverse=True):
                lines.append(f"- {note.recorded_at.isoformat()}: {note.line}")
        return "\n".join(lines).strip() + "\n"

    def _render_execution_log(
        self,
        account_plan: WorkflowArtifact | None,
        *,
        operational_notes: list[OperationalNote],
    ) -> str:
        lines = ["# Execution Log", ""]
        if account_plan is None:
            lines.append("Execution notes and operational outcomes will accumulate here.")
        else:
            lines.extend(
                [
                    "## Latest Planning Output",
                    "",
                    account_plan.summary or "Account assignment plan is available for execution follow-up.",
                ]
            )
        if operational_notes:
            lines.extend(["", "## Live Engagement Incidents", ""])
            for note in sorted(operational_notes, key=lambda item: item.recorded_at, reverse=True):
                lines.append(f"- {note.recorded_at.isoformat()}: {note.line}")
        return "\n".join(lines).strip() + "\n"

    def _render_orchestrator_notes(self, snapshot: WorkflowSnapshot) -> str:
        return (
            "# Orchestrator Notes\n\n"
            f"- Current stage: {snapshot.stage.value}\n"
            f"- Summary: {snapshot.summary or 'No summary yet.'}\n"
        )

    def _render_discovery_notes(self, shortlist: WorkflowArtifact | None) -> str:
        if shortlist is None:
            return _DEFAULT_FILE_CONTENT["agents/discovery.md"]
        summary = str(shortlist.data.get("summary", "")).strip() or shortlist.summary
        return f"# Discovery Notes\n\n{summary or 'Discovery shortlist is available.'}\n"

    def _render_strategy_notes(self, strategy: WorkflowArtifact | None) -> str:
        if strategy is None:
            return _DEFAULT_FILE_CONTENT["agents/strategy.md"]
        summary = str(strategy.data.get("campaign_strategy_summary", "")).strip() or strategy.summary
        return f"# Strategy Notes\n\n{summary or 'Strategy playbook is available.'}\n"

    def _render_account_manager_notes(self, account_plan: WorkflowArtifact | None) -> str:
        if account_plan is None:
            return _DEFAULT_FILE_CONTENT["agents/account_manager.md"]
        summary = account_plan.summary or "Account assignment plan is available."
        return f"# Account Manager Notes\n\n{summary}\n"

    def _brief_value(self, brief: WorkflowArtifact | None, key: str) -> str:
        if brief is None:
            return ""
        return str(brief.data.get(key, "")).strip()

    def _intent_value(self, intent: WorkflowArtifact | None, key: str) -> str:
        if intent is None:
            return ""
        return str(intent.data.get(key, "")).strip()

    def _intent_list(self, intent: WorkflowArtifact | None, key: str) -> list[str]:
        values = intent.data.get(key, []) if intent is not None else []
        if not isinstance(values, list):
            return []
        return [str(value).strip() for value in values if str(value).strip()]

    def _append_string_list(self, lines: list[str], label: str, values: Any) -> None:
        normalized_values = [
            str(value).strip()
            for value in values
            if str(value).strip()
        ] if isinstance(values, list) else []
        if not normalized_values:
            return
        lines.extend(["", f"## {label}", ""])
        for value in normalized_values:
            lines.append(f"- {value}")

    def _append_campaign_context_sections(
        self,
        lines: list[str],
        campaign_context: WorkflowArtifact | None,
    ) -> None:
        if campaign_context is None:
            return
        context_data = campaign_context.data if isinstance(campaign_context.data, dict) else {}
        voice_profile = context_data.get(VOICE_PROFILE_KEY, {})
        self._append_string_list(lines, "Operator preferences", context_data.get(OPERATOR_PREFERENCES_KEY, []))
        self._append_string_list(lines, "Execution constraints", context_data.get(EXECUTION_CONSTRAINTS_KEY, []))
        self._append_string_list(lines, "Persistent decisions", context_data.get(PERSISTENT_DECISIONS_KEY, []))
        self._append_string_list(lines, "Open ambiguities", context_data.get(OPEN_AMBIGUITIES_KEY, []))
        self._append_string_list(lines, "Preferred voice traits", self._context_voice_list(voice_profile, VOICE_PREFERRED_TRAITS_KEY))
        self._append_string_list(lines, "Voice traits to avoid", self._context_voice_list(voice_profile, VOICE_AVOID_TRAITS_KEY))
        self._append_string_list(lines, "Voice style notes", self._context_voice_list(voice_profile, VOICE_STYLE_NOTES_KEY))
        self._append_string_list(lines, "CTA preferences", self._context_voice_list(voice_profile, VOICE_CTA_PREFERENCES_KEY))
        self._append_revision_sections(lines, context_data.get(REVISION_THREADS_KEY, []))

    def _append_revision_sections(self, lines: list[str], revisions: Any) -> None:
        if not isinstance(revisions, list):
            return
        active_lines: list[str] = []
        accepted_lines: list[str] = []
        for revision in revisions:
            if not isinstance(revision, dict):
                continue
            scope = str(revision.get(SCOPE_KEY, "")).strip()
            summary = str(revision.get(SUMMARY_KEY, "")).strip()
            status = str(revision.get(STATUS_KEY, "")).strip()
            if not scope or not summary:
                continue
            rendered = f"{scope}: {summary}"
            if status == REVISION_STATUS_ACTIVE:
                active_lines.append(rendered)
            elif status == REVISION_STATUS_ACCEPTED:
                accepted_lines.append(rendered)
        self._append_string_list(lines, "Active revisions", active_lines[-4:])
        self._append_string_list(lines, "Accepted revisions", accepted_lines[-4:])

    def _context_voice_list(self, voice_profile: Any, key: str) -> list[str]:
        if not isinstance(voice_profile, dict):
            return []
        values = voice_profile.get(key, [])
        if not isinstance(values, list):
            return []
        return [str(value).strip() for value in values if str(value).strip()]

    def _ensure_file(self, workspace: Path, relative_path: str) -> None:
        file_path = workspace / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        if not file_path.exists():
            self._write_text_file(file_path, _DEFAULT_FILE_CONTENT.get(relative_path, ""))

    def _write_text_file(self, file_path: Path, content: str) -> None:
        file_path.write_text(content, encoding="utf-8")

    def _normalize_file_list(
        self,
        existing_files: list[str],
        default_files: tuple[str, ...],
    ) -> list[str]:
        normalized: list[str] = []
        for relative_path in [*default_files, *existing_files]:
            if relative_path and relative_path not in normalized:
                normalized.append(relative_path)
        return normalized

    def _slugify(self, value: str) -> str:
        cleaned = "".join(character.lower() if character.isalnum() else "-" for character in value.strip())
        while "--" in cleaned:
            cleaned = cleaned.replace("--", "-")
        return cleaned.strip("-")

    def _append_conversion_target_snapshot_data(
        self,
        data: dict[str, Any],
        artifact_map: dict[WorkflowArtifactKind, WorkflowArtifact],
    ) -> None:
        artifact = artifact_map.get(WorkflowArtifactKind.CONVERSION_TARGET)
        if artifact is None:
            return
        payload = artifact.data if isinstance(artifact.data, dict) else {}
        data["conversion_target_artifact_id"] = artifact.artifact_id
        data["conversion_target_summary"] = artifact.summary or build_conversion_target_summary(payload)
        data["conversion_target_kind"] = str(payload.get(CONVERSION_DESTINATION_KIND_KEY, "")).strip()
        data["conversion_target_normalized_value"] = str(payload.get(CONVERSION_NORMALIZED_VALUE_KEY, "")).strip()
        data["conversion_target_signal"] = str(payload.get(CONVERSION_RAW_VALUE_KEY, "")).strip()

    def _notes_for_destination(
        self,
        notes: list[OperationalNote],
        destination: str,
    ) -> list[OperationalNote]:
        return [note for note in notes if note.destination == destination]
