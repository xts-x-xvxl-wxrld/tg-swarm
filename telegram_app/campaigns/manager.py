"""Campaign workspace creation and metadata persistence."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from threading import RLock
from uuid import uuid4

from telegram_app.campaign_memory import (
    DEFAULT_AGENT_MEMORY_FILES,
    DEFAULT_CANONICAL_MEMORY_FILES,
    CampaignMemoryManager,
)
from telegram_app.json_store import load_json_file, write_json_file
from telegram_app.models import (
    CampaignRecord,
    CampaignStatus,
    SessionRecord,
    WorkflowArtifact,
    WorkflowStage,
)


class CampaignManager:
    """Own durable campaign metadata and workspace bootstrapping."""

    def __init__(self, campaigns_root: str | Path) -> None:
        self._campaigns_root = Path(campaigns_root).resolve()
        self._lock = RLock()
        self._memory_manager = CampaignMemoryManager()

    def ensure_campaign(
        self,
        operator_id: str,
        *,
        campaign_id: str | None = None,
        workspace_path: str | None = None,
        primary_goal: str = "",
    ) -> CampaignRecord:
        """Return an existing campaign or create a new workspace when missing."""
        with self._lock:
            existing = self.get(campaign_id) if campaign_id else None
            if existing is not None:
                if primary_goal and primary_goal != existing.primary_goal:
                    return self.update_primary_goal(existing.campaign_id, primary_goal) or existing
                return existing

            resolved_campaign_id = campaign_id or str(uuid4())
            resolved_workspace = Path(workspace_path).resolve() if workspace_path else (self._campaigns_root / resolved_campaign_id).resolve()
            campaign = CampaignRecord(
                campaign_id=resolved_campaign_id,
                operator_id=operator_id,
                workspace_path=str(resolved_workspace),
                primary_goal=primary_goal.strip(),
                canonical_files=list(DEFAULT_CANONICAL_MEMORY_FILES),
                agent_memory_files=list(DEFAULT_AGENT_MEMORY_FILES),
            )
            self._initialize_workspace(campaign)
            self._persist(campaign)
            return campaign

    def get(self, campaign_id: str | None) -> CampaignRecord | None:
        """Load persisted campaign metadata by identifier."""
        if not campaign_id:
            return None

        campaign_path = self._campaigns_root / campaign_id / "campaign.json"
        payload = load_json_file(campaign_path, default={})
        if not payload:
            return None

        campaign = CampaignRecord.from_dict(payload)
        if not campaign.campaign_id:
            return None
        original_canonical_files = list(campaign.canonical_files)
        original_agent_files = list(campaign.agent_memory_files)
        self._initialize_workspace(campaign)
        if (
            campaign.canonical_files != original_canonical_files
            or campaign.agent_memory_files != original_agent_files
        ):
            write_json_file(campaign_path, campaign.to_dict())
        return campaign

    def update_primary_goal(self, campaign_id: str, primary_goal: str) -> CampaignRecord | None:
        """Persist a refreshed campaign goal when intake learns more."""
        with self._lock:
            campaign = self.get(campaign_id)
            if campaign is None:
                return None

            normalized_goal = primary_goal.strip()
            if not normalized_goal or normalized_goal == campaign.primary_goal:
                return campaign

            campaign.primary_goal = normalized_goal
            campaign.touch()
            self._persist(campaign)
            return campaign

    def update_status(self, campaign_id: str, status: CampaignStatus) -> CampaignRecord | None:
        """Persist a campaign lifecycle status change."""
        with self._lock:
            campaign = self.get(campaign_id)
            if campaign is None:
                return None
            if campaign.status is status:
                return campaign
            campaign.status = status
            campaign.touch()
            self._persist(campaign)
            return campaign

    def hydrate_session(self, session: SessionRecord) -> SessionRecord:
        """Merge campaign-backed memory metadata and compatibility views into a session."""
        if not session.campaign_id:
            return session

        campaign = self.get(session.campaign_id)
        if campaign is None:
            return session

        if session.campaign_workspace_path != campaign.workspace_path:
            session.campaign_workspace_path = campaign.workspace_path
        session.canonical_memory_files = list(campaign.canonical_files or DEFAULT_CANONICAL_MEMORY_FILES)
        session.agent_memory_files = list(campaign.agent_memory_files or DEFAULT_AGENT_MEMORY_FILES)
        return self._memory_manager.hydrate_session(session)

    def sync_session_memory(self, session: SessionRecord) -> None:
        """Project session state back into the durable campaign workspace."""
        if not session.campaign_id or not session.campaign_workspace_path:
            return
        self._memory_manager.sync_session(session)

    def build_background_session(
        self,
        campaign_id: str,
        *,
        stage: WorkflowStage,
        summary: str,
    ) -> SessionRecord | None:
        """Build an in-memory campaign context for background work."""
        campaign = self.get(campaign_id)
        if campaign is None:
            return None
        return self._memory_manager.build_background_session(
            campaign,
            stage=stage,
            summary=summary,
        )

    def load_compatibility_artifacts(self, campaign_id: str) -> list[WorkflowArtifact]:
        """Load the current campaign-native workflow artifacts for one campaign."""
        campaign = self.get(campaign_id)
        if campaign is None:
            return []
        return self._memory_manager.load_compatibility_artifacts(campaign.workspace_path)

    def persist_generated_artifact(
        self,
        campaign_id: str,
        artifact: WorkflowArtifact,
        *,
        stage: WorkflowStage,
        summary: str,
    ) -> None:
        """Persist one generated artifact directly into campaign memory."""
        campaign = self.get(campaign_id)
        if campaign is None:
            return
        self._memory_manager.persist_generated_artifact(
            campaign,
            artifact,
            stage=stage,
            summary=summary,
        )

    def append_operational_note(
        self,
        campaign_id: str,
        *,
        destination: str,
        line: str,
        category: str = "",
        dedupe_key: str = "",
        recorded_at: datetime | None = None,
    ) -> None:
        """Persist one sparse operational note into campaign memory."""
        campaign = self.get(campaign_id)
        if campaign is None:
            return
        self._memory_manager.append_operational_note(
            campaign,
            destination=destination,
            line=line,
            category=category,
            dedupe_key=dedupe_key,
            recorded_at=recorded_at,
        )
        self._memory_manager.refresh_campaign_workspace(campaign)

    def refresh_workspace(self, campaign_id: str) -> None:
        """Re-render the campaign workspace from its durable state."""
        campaign = self.get(campaign_id)
        if campaign is None:
            return
        self._memory_manager.refresh_campaign_workspace(campaign)

    def _initialize_workspace(self, campaign: CampaignRecord) -> None:
        self._memory_manager.bootstrap_workspace(campaign)

    def _persist(self, campaign: CampaignRecord) -> None:
        campaign.touch()
        campaign_path = Path(campaign.workspace_path) / "campaign.json"
        write_json_file(campaign_path, campaign.to_dict())
