import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from agents.account_manager.agent import AccountManagerAgent, _prompt_safe_artifact_data as account_prompt_safe_artifact_data
from agents.discovery.agent import DiscoveryAgent
from agents.strategy.agent import StrategyAgent, _prompt_safe_artifact_data as strategy_prompt_safe_artifact_data
from telegram_app.app_service import TelegramAppService
from telegram_app.campaigns import CampaignManager
from telegram_app.scheduling import ScheduleManager, ScheduledWorkDispatcher
from telegram_app.capabilities import (
    StubAccountCapability,
    StubCommunityCapability,
    StubMembershipCapability,
    StubMessagingCapability,
)
from telegram_app.discovery import DISCOVERY_JSON_MARKER, persist_discovery_shortlist
from telegram_app.intake import StructuredIntakeCoordinator, get_campaign_brief_artifact
from telegram_app.json_store import load_json_file, write_json_file
from telegram_app.monitoring import JsonlRuntimeEventLogger
from telegram_app.approvals import ApprovalManager, JsonApprovalStore
from telegram_app.orchestrator import PurposeBuiltOrchestrator
from telegram_app.orchestrator.context_builder import build_runtime_context
from telegram_app.orchestrator.orchestrator import (
    SCHEDULE_ACTION_JSON_MARKER,
    _build_messages,
    _classify_approval_response,
)
from telegram_app.models import (
    ApprovalStatus,
    ScheduleStatus,
    WorkItemStatus,
    WorkflowArtifactKind,
    WorkflowSnapshot,
    WorkflowStage,
)
from telegram_app.sessions import JsonSessionStore, SessionManager
from telegram_app.transport import TelegramUpdate
from telegram_app.work_items import WorkItemManager


class FakeDiscoveryCommunityCapability:
    def search(self, query: str, *, mode: str = "exact", limit: int = 10):  # noqa: ANN001
        return MagicMock(
            success=True,
            data={
                "query": query,
                "mode": mode,
                "limit": limit,
                "results": [
                    {
                        "community_id": "111",
                        "name": "EU AI Founders",
                        "username": "eu_ai_founders",
                    }
                ],
                "source": "fake",
            },
            error="",
        )

    def get_profile(self, community_id: str):  # noqa: ANN001
        return MagicMock(
            success=True,
            data={
                "community": {
                    "community_id": community_id,
                    "member_count": 3200,
                    "verified": True,
                    "restricted": False,
                    "scam": False,
                }
            },
            error="",
        )


class UsernameFirstDiscoveryCommunityCapability:
    def __init__(self) -> None:
        self.profile_lookups: list[str] = []

    def search(self, query: str, *, mode: str = "exact", limit: int = 10):  # noqa: ANN001
        return MagicMock(
            success=True,
            data={
                "query": query,
                "mode": mode,
                "limit": limit,
                "results": [
                    {
                        "community_id": "2258115941",
                        "name": "EU AI Founders",
                        "username": "eu_ai_founders",
                    }
                ],
                "source": "fake",
            },
            error="",
        )

    def get_profile(self, community_id: str):  # noqa: ANN001
        self.profile_lookups.append(community_id)
        if community_id == "2258115941":
            return MagicMock(
                success=False,
                data={"community_id": community_id},
                error='Cannot find any entity corresponding to "2258115941"',
            )
        return MagicMock(
            success=True,
            data={
                "community": {
                    "community_id": "2258115941",
                    "member_count": 3200,
                    "verified": True,
                    "restricted": False,
                    "scam": False,
                }
            },
            error="",
        )


class HandleFallbackDiscoveryCommunityCapability:
    def __init__(self) -> None:
        self.search_queries: list[str] = []
        self.profile_lookups: list[str] = []

    def search(self, query: str, *, mode: str = "exact", limit: int = 10):  # noqa: ANN001
        self.search_queries.append(query)
        if query == "@eu_ai_founders":
            return MagicMock(
                success=False,
                data={"query": query, "mode": mode, "limit": limit, "results": [], "source": "fake"},
                error='No user has "eu_ai_founders" as username',
            )
        if query == "AI Founders":
            return MagicMock(
                success=True,
                data={
                    "query": query,
                    "mode": mode,
                    "limit": limit,
                    "results": [
                        {
                            "community_id": "3868459786",
                            "name": "AI Founders",
                            "username": "ai_founders_club",
                        }
                    ],
                    "source": "fake",
                },
                error="",
            )
        return MagicMock(success=True, data={"query": query, "mode": mode, "limit": limit, "results": [], "source": "fake"}, error="")

    def get_profile(self, community_id: str):  # noqa: ANN001
        self.profile_lookups.append(community_id)
        return MagicMock(
            success=True,
            data={
                "community": {
                    "community_id": "3868459786",
                    "member_count": 682,
                    "verified": False,
                    "restricted": False,
                    "scam": False,
                }
            },
            error="",
        )


class FakeDiscoveryMessagingCapability:
    def read_messages(self, chat_id: str, limit: int = 20):  # noqa: ANN001
        return MagicMock(
            success=True,
            data={
                "messages": [
                    {"text": "Founder intros and operator advice.", "date": "2026-05-11T10:00:00+00:00"},
                    {"text": "Sharing traction lessons from this week.", "date": "2026-05-11T09:00:00+00:00"},
                ]
            },
            error="",
        )


class QueryAwareDiscoveryCommunityCapability:
    def __init__(self) -> None:
        self.search_queries: list[str] = []
        self.search_calls: list[tuple[str, str, int]] = []

    def search(self, query: str, *, mode: str = "exact", limit: int = 10):  # noqa: ANN001
        self.search_queries.append(query)
        self.search_calls.append((query, mode, limit))
        query_map = {
            "AI founders Europe": [],
            "AI founders": [
                {
                    "community_id": "111",
                    "name": "EU AI Founders",
                    "username": "eu_ai_founders",
                    "member_count": 3200,
                    "verified": True,
                },
                {
                    "community_id": "222",
                    "name": "AI Builders Europe",
                    "username": "ai_builders_eu",
                    "member_count": 1800,
                },
            ],
            "AI startup founders Europe": [
                {
                    "community_id": "222",
                    "name": "AI Builders Europe",
                    "username": "ai_builders_eu",
                    "member_count": 1800,
                }
            ],
            "AI startup founders": [],
            "AI builders Europe": [
                {
                    "community_id": "333",
                    "name": "Berlin AI Builders",
                    "username": "berlin_ai_builders",
                    "member_count": 950,
                }
            ],
            "AI builders": [],
            "Berlin AI founders": [
                {
                    "community_id": "444",
                    "name": "Berlin AI Founders",
                    "username": "berlin_ai_founders",
                    "member_count": 640,
                }
            ],
            "London AI founders": [],
        }
        return MagicMock(
            success=True,
            data={"query": query, "mode": mode, "limit": limit, "results": query_map.get(query, []), "source": "telethon"},
            error="",
        )

    def get_profile(self, community_id: str):  # noqa: ANN001
        return MagicMock(
            success=True,
            data={
                "community": {
                    "community_id": community_id,
                    "member_count": 3200,
                    "verified": True,
                    "restricted": False,
                    "scam": False,
                }
            },
            error="",
        )


class HarvestFirstDiscoveryCommunityCapability:
    def __init__(self) -> None:
        self.search_calls: list[tuple[str, str, int]] = []
        self.profile_lookups: list[str] = []

    def search(self, query: str, *, mode: str = "exact", limit: int = 10):  # noqa: ANN001
        self.search_calls.append((query, mode, limit))
        if mode == "harvest" and query == "AI founders":
            return MagicMock(
                success=True,
                data={
                    "query": query,
                    "mode": mode,
                    "limit": limit,
                    "results": [
                        {
                            "community_id": "555",
                            "name": "AI Founders Club",
                            "username": "ai_founders_club",
                            "member_count": 2100,
                        }
                    ],
                    "source": "fake_harvest",
                },
                error="",
            )
        return MagicMock(
            success=True,
            data={"query": query, "mode": mode, "limit": limit, "results": [], "source": "fake_exact"},
            error="",
        )

    def get_profile(self, community_id: str):  # noqa: ANN001
        self.profile_lookups.append(community_id)
        return MagicMock(
            success=True,
            data={
                "community": {
                    "community_id": "555",
                    "member_count": 2100,
                    "verified": False,
                    "restricted": False,
                    "scam": False,
                }
            },
            error="",
        )


class RefinementAwareDiscoveryCommunityCapability:
    def __init__(self) -> None:
        self.search_calls: list[tuple[str, str, int]] = []
        self.profile_lookups: list[str] = []

    def search(self, query: str, *, mode: str = "exact", limit: int = 10):  # noqa: ANN001
        self.search_calls.append((query, mode, limit))
        query_map = {
            "AI founders": [
                {
                    "community_id": "555",
                    "name": "AI Founders Club",
                    "username": "ai_founders_club",
                    "member_count": 2100,
                }
            ],
            "Paris AI founders": [
                {
                    "community_id": "777",
                    "name": "Paris AI Founders",
                    "username": "paris_ai_founders",
                    "member_count": 980,
                }
            ],
        }
        return MagicMock(
            success=True,
            data={"query": query, "mode": mode, "limit": limit, "results": query_map.get(query, []), "source": "fake_refinement"},
            error="",
        )

    def get_profile(self, community_id: str):  # noqa: ANN001
        self.profile_lookups.append(community_id)
        return MagicMock(
            success=True,
            data={
                "community": {
                    "community_id": community_id,
                    "member_count": 2100 if community_id == "@ai_founders_club" else 980,
                    "verified": False,
                    "restricted": False,
                    "scam": False,
                }
            },
            error="",
        )


class MixedEvidenceDiscoveryCommunityCapability:
    def __init__(self) -> None:
        self.search_calls: list[tuple[str, str, int]] = []

    def search(self, query: str, *, mode: str = "exact", limit: int = 10):  # noqa: ANN001
        self.search_calls.append((query, mode, limit))
        if mode == "exact" and query in {"@eu_ai_founders", "EU AI Founders"}:
            return MagicMock(
                success=True,
                data={
                    "query": query,
                    "mode": mode,
                    "limit": limit,
                    "results": [
                        {
                            "community_id": "111",
                            "name": "EU AI Founders",
                            "username": "eu_ai_founders",
                            "member_count": 3200,
                            "search_mode": "exact",
                        }
                    ],
                    "source": "fake_exact",
                },
                error="",
            )
        return MagicMock(
            success=True,
            data={"query": query, "mode": mode, "limit": limit, "results": [], "source": "fake_exact"},
            error="",
        )

    def get_profile(self, community_id: str):  # noqa: ANN001
        member_count = 3200 if community_id == "@eu_ai_founders" else 2100
        verified = community_id == "@eu_ai_founders"
        return MagicMock(
            success=True,
            data={
                "community": {
                    "community_id": community_id,
                    "member_count": member_count,
                    "verified": verified,
                    "restricted": False,
                    "scam": False,
                }
            },
            error="",
        )


class RecordingMembershipCapability:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def get_membership(self, account_id: str, community_id: str):  # noqa: ANN001
        return MagicMock(
            success=True,
            data={"account_id": account_id, "community_id": community_id, "state": "not_member"},
            audit={"implementation": "recording_membership_capability"},
            error="",
        )

    def join(self, account_id: str, community_id: str):  # noqa: ANN001
        self.calls.append((account_id, community_id))
        return MagicMock(
            success=True,
            data={"account_id": account_id, "community_id": community_id, "raw_updates_type": "Updates"},
            audit={"implementation": "recording_membership_capability"},
            error="",
        )


class RecordingMessagingCapability:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, dict[str, object] | None]] = []

    def read_messages(self, chat_id: str, limit: int = 20):  # noqa: ANN001
        return MagicMock(
            success=True,
            data={"chat_id": chat_id, "messages": [], "limit": limit},
            audit={"implementation": "recording_messaging_capability"},
            error="",
        )

    def send_message(
        self,
        account_id: str,
        chat_id: str,
        text: str,
        *,
        approval_context: dict[str, object] | None = None,
    ):
        self.calls.append((account_id, chat_id, text, approval_context))
        return MagicMock(
            success=True,
            data={"account_id": account_id, "chat_id": chat_id, "text": text, "message_id": 777},
            audit={"implementation": "recording_messaging_capability"},
            error="",
        )


class EchoOrchestrator:
    def handle_turn(self, session, update, pending_approval=None, trace_context=None):  # noqa: ANN001
        return MagicMock(
            chat_id=update.chat_id,
            messages=[MagicMock(text=update.text, reply_markup=None)],
            metadata={"trace_id": getattr(trace_context, "trace_id", "")},
        )


class FailingStrategyCommunityCapability:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_profile(self, community_id: str):  # noqa: ANN001
        self.calls.append(community_id)
        raise AssertionError("StrategyAgent should reuse persisted discovery profile data before live re-reads.")


def test_json_session_store_persists_active_session_state(tmp_path) -> None:
    store = JsonSessionStore(tmp_path / "sessions.json")
    manager = SessionManager(store)

    session = manager.start_session("operator-1")
    manager.record_operator_message(session, "Find Telegram groups for AI founders.")

    reloaded_store = JsonSessionStore(tmp_path / "sessions.json")
    loaded_session = reloaded_store.get_active_for_operator("operator-1")
    index_payload = json.loads((tmp_path / "sessions.json").read_text(encoding="utf-8"))
    session_payload = json.loads(
        (tmp_path / "sessions" / f"{session.session_id}.json").read_text(encoding="utf-8")
    )

    assert loaded_session is not None
    assert loaded_session.session_id == session.session_id
    assert loaded_session.latest_operator_message == "Find Telegram groups for AI founders."
    assert loaded_session.workflow_state["message_history"][-1]["role"] == "operator"
    assert index_payload["active_session_ids"]["operator-1"] == session.session_id
    assert "sessions" not in index_payload
    assert session_payload["session_id"] == session.session_id


def test_json_session_store_migrates_legacy_monolith_to_per_session_files(tmp_path) -> None:
    legacy_session_id = "session-legacy-1"
    (tmp_path / "sessions.json").write_text(
        json.dumps(
            {
                "active_session_ids": {"operator-legacy": legacy_session_id},
                "sessions": {
                    legacy_session_id: {
                        "session_id": legacy_session_id,
                        "operator_id": "operator-legacy",
                        "status": "active",
                        "latest_operator_message": "legacy message",
                        "workflow_state": {"message_history": [{"role": "operator", "text": "legacy message"}]},
                        "linked_entity_ids": {},
                        "pending_approval_id": None,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    store = JsonSessionStore(tmp_path / "sessions.json")
    loaded_session = store.get_active_for_operator("operator-legacy")
    migrated_index = json.loads((tmp_path / "sessions.json").read_text(encoding="utf-8"))
    migrated_session = json.loads(
        (tmp_path / "sessions" / f"{legacy_session_id}.json").read_text(encoding="utf-8")
    )

    assert loaded_session is not None
    assert loaded_session.session_id == legacy_session_id
    assert migrated_index["active_session_ids"]["operator-legacy"] == legacy_session_id
    assert "sessions" not in migrated_index
    assert migrated_session["latest_operator_message"] == "legacy message"


def test_load_json_file_returns_default_for_invalid_payload(tmp_path) -> None:
    invalid_file = tmp_path / "invalid.json"
    invalid_file.write_text("not valid json", encoding="utf-8")

    payload = load_json_file(invalid_file, default={"fallback": True})

    assert payload == {"fallback": True}


def test_write_json_file_falls_back_to_direct_overwrite_after_replace_lock(tmp_path) -> None:
    target_file = tmp_path / "state.json"
    target_file.write_text('{"old": true}', encoding="utf-8")

    original_replace = os.replace

    def flaky_replace(src, dst):  # noqa: ANN001
        if Path(src).suffix == ".tmp" and Path(dst) == target_file:
            raise PermissionError("locked")
        return original_replace(src, dst)

    with patch("telegram_app.json_store.os.replace", side_effect=flaky_replace):
        write_json_file(target_file, {"new": True})

    assert json.loads(target_file.read_text(encoding="utf-8")) == {"new": True}


def test_write_json_file_retries_direct_overwrite_after_replace_lock(tmp_path) -> None:
    target_file = tmp_path / "state.json"
    target_file.write_text('{"old": true}', encoding="utf-8")

    original_write_text = Path.write_text

    def flaky_replace(_src, dst):  # noqa: ANN001
        if Path(dst) == target_file:
            raise PermissionError("locked")
        return None

    write_attempts = {"count": 0}

    def flaky_write_text(self, data, *args, **kwargs):  # noqa: ANN001
        if self == target_file:
            write_attempts["count"] += 1
            if write_attempts["count"] < 3:
                raise PermissionError("locked")
        return original_write_text(self, data, *args, **kwargs)

    with patch("telegram_app.json_store.os.replace", side_effect=flaky_replace):
        with patch("pathlib.Path.write_text", autospec=True, side_effect=flaky_write_text):
            write_json_file(target_file, {"new": True})

    assert write_attempts["count"] == 3
    assert json.loads(target_file.read_text(encoding="utf-8")) == {"new": True}


def test_json_approval_store_persists_pending_and_resolved_state(tmp_path) -> None:
    approval_manager = ApprovalManager(JsonApprovalStore(tmp_path / "approvals.json"))
    approval = approval_manager.create_pending(
        session_id="session-123",
        category="community_shortlist",
        prompt="Approve these communities?",
        context={"count": 3},
    )

    reloaded_pending_store = JsonApprovalStore(tmp_path / "approvals.json")
    pending_approval = reloaded_pending_store.get_pending_for_session("session-123")

    assert pending_approval is not None
    assert pending_approval.approval_id == approval.approval_id

    reloaded_manager = ApprovalManager(reloaded_pending_store)
    reloaded_manager.resolve(pending_approval, ApprovalStatus.APPROVED, note="Looks good.")

    resolved_store = JsonApprovalStore(tmp_path / "approvals.json")
    resolved_approval = resolved_store.get(approval.approval_id)

    assert resolved_store.get_pending_for_session("session-123") is None
    assert resolved_approval is not None
    assert resolved_approval.status is ApprovalStatus.APPROVED
    assert resolved_approval.resolution_note == "Looks good."


def test_session_manager_persists_workflow_snapshot_and_artifacts(tmp_path) -> None:
    store = JsonSessionStore(tmp_path / "sessions.json")
    manager = SessionManager(store)
    session = manager.start_session("operator-2")
    manager.attach_campaign(session, "cmp-001", str((tmp_path / "campaigns" / "cmp-001").resolve()))

    snapshot = WorkflowSnapshot(
        stage=WorkflowStage.DISCOVERY,
        summary="Researching candidate communities.",
        data={"campaign_id": "cmp-001"},
    )
    manager.replace_workflow_snapshot(session, snapshot)
    artifact = manager.create_workflow_artifact(
        session=session,
        kind=WorkflowArtifactKind.CAMPAIGN_BRIEF,
        title="Campaign brief",
        summary="Seed round launch in Europe.",
        data={"objective": "Drive founder conversations"},
    )

    reloaded_store = JsonSessionStore(tmp_path / "sessions.json")
    reloaded_session = reloaded_store.get(session.session_id)

    assert reloaded_session is not None
    reloaded_manager = SessionManager(reloaded_store)
    loaded_snapshot = reloaded_manager.get_workflow_snapshot(reloaded_session)
    loaded_artifacts = reloaded_manager.list_workflow_artifacts(reloaded_session)

    assert loaded_snapshot.stage is WorkflowStage.DISCOVERY
    assert loaded_snapshot.data["campaign_id"] == "cmp-001"
    assert reloaded_session.campaign_id == "cmp-001"
    assert reloaded_session.campaign_workspace_path == str((tmp_path / "campaigns" / "cmp-001").resolve())
    assert len(loaded_artifacts) == 1
    assert loaded_artifacts[0].artifact_id == artifact.artifact_id
    assert loaded_artifacts[0].kind is WorkflowArtifactKind.CAMPAIGN_BRIEF
    assert loaded_artifacts[0].data["objective"] == "Drive founder conversations"


def test_campaign_manager_creates_workspace_and_persists_metadata(tmp_path) -> None:
    manager = CampaignManager(tmp_path / "campaigns")

    campaign = manager.ensure_campaign(
        "operator-campaign",
        campaign_id="cmp-123",
        primary_goal="Drive founder conversations",
    )

    workspace = Path(campaign.workspace_path)

    assert campaign.campaign_id == "cmp-123"
    assert workspace.exists()
    assert (workspace / "campaign.json").exists()
    assert (workspace / "overview.md").exists()
    assert (workspace / "operator-intent.md").exists()
    assert (workspace / "strategy.md").exists()
    assert (workspace / "research-log.md").exists()
    assert (workspace / "personas.md").exists()
    assert (workspace / "experiments.md").exists()
    assert (workspace / "next-actions.md").exists()
    assert (workspace / "execution-log.md").exists()
    assert (workspace / "communities").is_dir()
    assert (workspace / "agents").is_dir()
    assert (workspace / "agents" / "discovery.md").exists()
    assert (workspace / "agents" / "strategy.md").exists()
    assert (workspace / "agents" / "account_manager.md").exists()
    assert "strategy.md" in campaign.canonical_files
    assert "agents/discovery.md" in campaign.agent_memory_files

    reloaded = manager.get("cmp-123")
    assert reloaded is not None
    assert reloaded.primary_goal == "Drive founder conversations"


def test_work_item_manager_persists_and_selects_primary_open_item(tmp_path) -> None:
    manager = WorkItemManager(tmp_path / "campaigns")

    discovery_item = manager.ensure_work_item(
        "cmp-work-items",
        owner_role="discovery",
        work_type="discovery",
        goal="Refresh discovery coverage.",
    )
    strategy_item = manager.ensure_work_item(
        "cmp-work-items",
        owner_role="strategy",
        work_type="strategy",
        goal="Review positioning changes.",
    )
    manager.update_status(
        "cmp-work-items",
        strategy_item.work_item_id,
        status=WorkItemStatus.REVIEW_PENDING,
        result_summary="Strategy draft ready for review.",
    )

    reloaded = WorkItemManager(tmp_path / "campaigns")
    items = reloaded.list_for_campaign("cmp-work-items")
    primary = reloaded.get_primary_open_item("cmp-work-items")

    assert len(items) == 2
    assert discovery_item.work_item_id in {item.work_item_id for item in items}
    assert primary is not None
    assert primary.work_item_id == strategy_item.work_item_id
    assert primary.status is WorkItemStatus.REVIEW_PENDING


def test_structured_intake_creates_campaign_brief_and_advances_snapshot(tmp_path) -> None:
    store = JsonSessionStore(tmp_path / "sessions.json")
    manager = SessionManager(store)
    intake = StructuredIntakeCoordinator(manager)
    session = manager.start_session("operator-3")

    intake.ingest_operator_turn(
        session,
        "Goal: Find Telegram communities for AI founders\nAudience: AI founders\nGeography: Europe",
    )

    reloaded_session = JsonSessionStore(tmp_path / "sessions.json").get(session.session_id)
    assert reloaded_session is not None

    campaign_brief = get_campaign_brief_artifact(reloaded_session)
    snapshot = manager.get_workflow_snapshot(reloaded_session)

    assert campaign_brief is not None
    assert campaign_brief.data["objective"] == "Find Telegram communities for AI founders"
    assert campaign_brief.data["target_audience"] == "AI founders"
    assert campaign_brief.data["geography"] == "Europe"
    assert snapshot.stage is WorkflowStage.DISCOVERY
    assert snapshot.data["campaign_brief_artifact_id"] == campaign_brief.artifact_id


def test_structured_intake_merges_follow_up_constraints_without_overwriting_goal(tmp_path) -> None:
    store = JsonSessionStore(tmp_path / "sessions.json")
    manager = SessionManager(store)
    intake = StructuredIntakeCoordinator(manager)
    session = manager.start_session("operator-4")

    intake.ingest_operator_turn(session, "Find Telegram communities for fintech founders in MENA")
    intake.ingest_operator_turn(
        session,
        "Constraints: avoid communities that ban promotion; prioritize English-speaking groups",
    )

    reloaded_session = JsonSessionStore(tmp_path / "sessions.json").get(session.session_id)
    assert reloaded_session is not None

    campaign_brief = get_campaign_brief_artifact(reloaded_session)
    snapshot = manager.get_workflow_snapshot(reloaded_session)

    assert campaign_brief is not None
    assert campaign_brief.data["objective"] == "Find Telegram communities for fintech founders in MENA"
    assert campaign_brief.data["target_audience"] == "fintech founders"
    assert "avoid communities that ban promotion" in campaign_brief.data["constraints"]
    assert "prioritize English-speaking groups" in campaign_brief.data["constraints"]
    assert snapshot.stage is WorkflowStage.DISCOVERY


def test_runtime_context_omits_campaign_brief_source_messages(tmp_path) -> None:
    store = JsonSessionStore(tmp_path / "sessions.json")
    manager = SessionManager(store)
    intake = StructuredIntakeCoordinator(manager)
    session = manager.start_session("operator-4b")
    manager.attach_campaign(session, "cmp-context", str((tmp_path / "campaigns" / "cmp-context").resolve()))
    work_item_manager = WorkItemManager(tmp_path / "campaigns")
    schedule_manager = ScheduleManager(tmp_path / "campaigns")

    intake.ingest_operator_turn(session, "Find Telegram communities for fintech founders in MENA")
    intake.ingest_operator_turn(
        session,
        "Constraints: avoid communities that ban promotion; prioritize English-speaking groups",
    )

    active_work_item = work_item_manager.ensure_work_item(
        "cmp-context",
        owner_role="discovery",
        work_type="discovery",
        goal="Refresh the shortlist.",
    )
    active_schedule = schedule_manager.create_interval_schedule(
        "cmp-context",
        owner_role="strategy",
        work_type="strategy",
        goal="Run a weekly strategy review.",
        interval_minutes=60,
        next_run_at=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
    )

    context = build_runtime_context(
        session,
        pending_approval=None,
        active_work_items=[active_work_item],
        active_schedules=[active_schedule],
        discovery_mode=True,
    )

    assert "campaign_brief_data" in context
    assert "source_messages" not in context
    assert "constraints" in context
    assert "campaign_attached: true" in context
    assert "campaign_id: cmp-context" in context
    assert "active_work_item_count: 1" in context
    assert "active_schedule_count: 1" in context


def test_campaign_sync_preserves_specialist_working_memory_files(tmp_path) -> None:
    session_store = JsonSessionStore(tmp_path / "sessions.json")
    session_manager = SessionManager(session_store)
    campaign_manager = CampaignManager(tmp_path / "campaigns")
    session = session_manager.start_session("operator-memory-preserve")
    campaign = campaign_manager.ensure_campaign("operator-memory-preserve", campaign_id="cmp-memory-preserve")
    session_manager.attach_campaign(
        session,
        campaign.campaign_id,
        campaign.workspace_path,
        canonical_memory_files=campaign.canonical_files,
        agent_memory_files=campaign.agent_memory_files,
    )
    session_manager.create_workflow_artifact(
        session=session,
        kind=WorkflowArtifactKind.CAMPAIGN_BRIEF,
        title="Campaign brief",
        data={"objective": "Reach AI founders", "target_audience": "AI founders"},
    )

    strategy_notes_path = Path(campaign.workspace_path) / "agents" / "strategy.md"
    strategy_notes_path.write_text("# Strategy Notes\n\nCustom tactical note.\n", encoding="utf-8")

    campaign_manager.sync_session_memory(session)

    assert strategy_notes_path.read_text(encoding="utf-8") == "# Strategy Notes\n\nCustom tactical note.\n"
    assert (Path(campaign.workspace_path) / "overview.md").read_text(encoding="utf-8")


def test_telegram_app_service_attaches_campaign_and_syncs_primary_goal(tmp_path) -> None:
    session_store = JsonSessionStore(tmp_path / "sessions.json")
    approval_store = JsonApprovalStore(tmp_path / "approvals.json")
    session_manager = SessionManager(session_store)
    approval_manager = ApprovalManager(approval_store)
    campaign_manager = CampaignManager(tmp_path / "campaigns")
    service = TelegramAppService(
        session_manager=session_manager,
        approval_manager=approval_manager,
        orchestrator=EchoOrchestrator(),
        intake_coordinator=StructuredIntakeCoordinator(session_manager),
        campaign_manager=campaign_manager,
    )

    service.handle_update(
        TelegramUpdate(
            chat_id="chat-campaign",
            user_id="operator-campaign",
            text="/new Goal: Find Telegram communities for AI founders",
            command="/new",
        )
    )

    active_session = session_manager.get_active_session("operator-campaign")
    assert active_session is not None
    assert active_session.campaign_id is not None
    assert active_session.campaign_workspace_path is not None

    campaign = campaign_manager.get(active_session.campaign_id)
    assert campaign is not None
    assert campaign.primary_goal == "Find Telegram communities for AI founders"


def test_scheduled_work_dispatch_creates_work_item_without_session(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    campaign_manager = CampaignManager(campaigns_root)
    work_item_manager = WorkItemManager(campaigns_root)
    schedule_manager = ScheduleManager(campaigns_root)
    campaign_manager.ensure_campaign("operator-scheduled", campaign_id="cmp-scheduled")

    due_time = datetime(2026, 5, 13, 9, 0, tzinfo=UTC)
    schedule = schedule_manager.create_interval_schedule(
        "cmp-scheduled",
        owner_role="discovery",
        work_type="discovery",
        goal="Refresh discovery coverage and revalidate communities.",
        interval_minutes=120,
        next_run_at=due_time,
    )

    discovery_output = f"""I refreshed the shortlist with current campaign memory.

Please review the updated shortlist before moving on.

{DISCOVERY_JSON_MARKER}
```json
{{
  "summary": "Refreshed the shortlist with one validated founder community.",
  "recommended_next_step": "Review the shortlist and continue to strategy if it still fits.",
  "communities": [
    {{
      "name": "EU AI Founders",
      "handle": "@eu_ai_founders",
      "type": "group",
      "topic": "AI startups",
      "language": "English",
      "geography": "Europe",
      "relevance_score": 92,
      "promo_tolerance": "medium",
      "moderation_risk": "low",
      "reason": "Still aligned with founder outreach in Europe.",
      "verification_state": "live_confirmed",
      "source_notes": ["Recurring discovery refresh"]
    }}
  ]
}}
```"""

    fake_content_block = MagicMock()
    fake_content_block.text = discovery_output
    fake_api_response = MagicMock()
    fake_api_response.content = [fake_content_block]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = fake_api_response

    with patch("anthropic.Anthropic", return_value=mock_client):
        orchestrator = PurposeBuiltOrchestrator(
            community_capability=StubCommunityCapability(),
            work_item_manager=work_item_manager,
            schedule_manager=schedule_manager,
            campaign_manager=campaign_manager,
        )
        dispatcher = ScheduledWorkDispatcher(schedule_manager, orchestrator)
        dispatched_items = dispatcher.dispatch_due_work(now=due_time)

    assert len(dispatched_items) == 1
    dispatched_item = dispatched_items[0]
    assert dispatched_item.campaign_id == "cmp-scheduled"
    assert dispatched_item.schedule_id == schedule.schedule_id
    assert dispatched_item.status is WorkItemStatus.REVIEW_PENDING
    assert "validated communities" in dispatched_item.result_summary
    assert dispatched_item.escalation_reason == ""

    campaign = campaign_manager.get("cmp-scheduled")
    assert campaign is not None
    background_session = campaign_manager.build_background_session(
        "cmp-scheduled",
        stage=WorkflowStage.DISCOVERY,
        summary="Reload campaign-native context.",
    )
    assert background_session is not None
    shortlist = next(
        artifact
        for artifact in background_session.workflow_state["workflow_artifacts"]
        if artifact["kind"] == WorkflowArtifactKind.COMMUNITY_SHORTLIST.value
    )
    assert shortlist["data"]["communities"][0]["name"] == "EU AI Founders"
    assert (campaigns_root / "cmp-scheduled" / "research-log.md").read_text(encoding="utf-8")
    assert (campaigns_root / "cmp-scheduled" / "communities" / "eu-ai-founders.md").exists()

    reloaded_schedule = schedule_manager.get("cmp-scheduled", schedule.schedule_id)
    assert reloaded_schedule is not None
    assert reloaded_schedule.last_run_at == due_time
    assert reloaded_schedule.next_run_at == due_time + timedelta(minutes=120)
    assert reloaded_schedule.consecutive_miss_count == 0


def test_orchestrator_turn_can_create_recurring_schedule_from_operator_request(tmp_path) -> None:
    session_store = JsonSessionStore(tmp_path / "sessions.json")
    approval_store = JsonApprovalStore(tmp_path / "approvals.json")
    session_manager = SessionManager(session_store)
    approval_manager = ApprovalManager(approval_store)
    campaign_manager = CampaignManager(tmp_path / "campaigns")
    schedule_manager = ScheduleManager(tmp_path / "campaigns")
    work_item_manager = WorkItemManager(tmp_path / "campaigns")
    session = session_manager.start_session("operator-schedule-create")
    campaign = campaign_manager.ensure_campaign("operator-schedule-create", campaign_id="cmp-schedule-create")
    session_manager.attach_campaign(
        session,
        campaign.campaign_id,
        campaign.workspace_path,
        canonical_memory_files=campaign.canonical_files,
        agent_memory_files=campaign.agent_memory_files,
    )
    work_item_manager.ensure_work_item(
        campaign.campaign_id,
        owner_role="discovery",
        work_type="discovery",
        goal="Refresh the discovery shortlist.",
        status=WorkItemStatus.IN_PROGRESS,
    )

    orchestrator_output = """I'll keep discovery coverage fresh with a weekly recurring refresh.

SCHEDULE_ACTION_JSON
```json
{
  "action": "create",
  "schedule": {
    "owner_role": "discovery",
    "work_type": "discovery",
    "goal": "Refresh the discovery shortlist for AI founder communities.",
    "interval_minutes": 10080,
    "constraints": ["Keep the shortlist focused on Europe."],
    "priority": "high",
    "evaluation_metric": "validated_community_count",
    "minimum_value": 1,
    "pause_after_consecutive_misses": 2
  }
}
```"""

    fake_content_block = MagicMock()
    fake_content_block.text = orchestrator_output
    fake_api_response = MagicMock()
    fake_api_response.content = [fake_content_block]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = fake_api_response

    with patch("anthropic.Anthropic", return_value=mock_client):
        orchestrator = PurposeBuiltOrchestrator(
            session_manager=session_manager,
            approval_manager=approval_manager,
            work_item_manager=work_item_manager,
            schedule_manager=schedule_manager,
            campaign_manager=campaign_manager,
        )
        response = orchestrator.handle_turn(
            session=session,
            update=TelegramUpdate(
                chat_id="chat-schedule-create",
                user_id="operator-schedule-create",
                text="Set up a weekly discovery refresh for this campaign.",
            ),
        )

    schedules = schedule_manager.list_for_campaign(campaign.campaign_id)
    assert len(schedules) == 1
    created_schedule = schedules[0]
    assert created_schedule.owner_role == "discovery"
    assert created_schedule.work_type == "discovery"
    assert created_schedule.interval_minutes == 10080
    assert created_schedule.priority.value == "high"
    assert created_schedule.evaluation_metric == "validated_community_count"
    assert created_schedule.minimum_value == 1
    assert created_schedule.pause_after_consecutive_misses == 2
    assert SCHEDULE_ACTION_JSON_MARKER not in response.messages[0].text
    assert "saved a recurring `discovery` schedule" in response.messages[0].text.lower()


def test_orchestrator_turn_can_pause_and_resume_recurring_schedule(tmp_path) -> None:
    session_store = JsonSessionStore(tmp_path / "sessions.json")
    approval_store = JsonApprovalStore(tmp_path / "approvals.json")
    session_manager = SessionManager(session_store)
    approval_manager = ApprovalManager(approval_store)
    campaign_manager = CampaignManager(tmp_path / "campaigns")
    schedule_manager = ScheduleManager(tmp_path / "campaigns")
    session = session_manager.start_session("operator-schedule-manage")
    campaign = campaign_manager.ensure_campaign("operator-schedule-manage", campaign_id="cmp-schedule-manage")
    session_manager.attach_campaign(
        session,
        campaign.campaign_id,
        campaign.workspace_path,
        canonical_memory_files=campaign.canonical_files,
        agent_memory_files=campaign.agent_memory_files,
    )
    schedule = schedule_manager.create_interval_schedule(
        campaign.campaign_id,
        owner_role="strategy",
        work_type="strategy",
        goal="Run a weekly strategy review.",
        interval_minutes=10080,
    )

    pause_output = """I'll pause that recurring strategy review for now.

SCHEDULE_ACTION_JSON
```json
{
  "action": "pause",
  "schedule": {
    "schedule_id": "%s"
  }
}
```""" % schedule.schedule_id

    resume_output = """I'll resume that recurring strategy review.

SCHEDULE_ACTION_JSON
```json
{
  "action": "resume",
  "schedule": {
    "work_type": "strategy"
  }
}
```"""

    def _fake_response(text: str) -> MagicMock:
        block = MagicMock()
        block.text = text
        response = MagicMock()
        response.content = [block]
        return response

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [
        _fake_response(pause_output),
        _fake_response(resume_output),
    ]

    with patch("anthropic.Anthropic", return_value=mock_client):
        orchestrator = PurposeBuiltOrchestrator(
            session_manager=session_manager,
            approval_manager=approval_manager,
            schedule_manager=schedule_manager,
            campaign_manager=campaign_manager,
        )
        pause_response = orchestrator.handle_turn(
            session=session,
            update=TelegramUpdate(
                chat_id="chat-schedule-manage",
                user_id="operator-schedule-manage",
                text="Pause the weekly strategy review.",
            ),
        )
        paused_schedule = schedule_manager.get(campaign.campaign_id, schedule.schedule_id)
        assert paused_schedule is not None
        assert paused_schedule.status is ScheduleStatus.PAUSED
        assert "paused the recurring `strategy` schedule" in pause_response.messages[0].text.lower()

        resume_response = orchestrator.handle_turn(
            session=session,
            update=TelegramUpdate(
                chat_id="chat-schedule-manage",
                user_id="operator-schedule-manage",
                text="Resume the weekly strategy review.",
            ),
        )

    resumed_schedule = schedule_manager.get(campaign.campaign_id, schedule.schedule_id)
    assert resumed_schedule is not None
    assert resumed_schedule.status is ScheduleStatus.ACTIVE
    assert "resumed the recurring `strategy` schedule" in resume_response.messages[0].text.lower()
    assert resumed_schedule.next_run_at > datetime.now(UTC)


def test_handle_turn_prefers_work_item_status_over_artifact_presence(tmp_path) -> None:
    session_store = JsonSessionStore(tmp_path / "sessions.json")
    approval_store = JsonApprovalStore(tmp_path / "approvals.json")
    session_manager = SessionManager(session_store)
    approval_manager = ApprovalManager(approval_store)
    campaign_manager = CampaignManager(tmp_path / "campaigns")
    work_item_manager = WorkItemManager(tmp_path / "campaigns")

    campaign = campaign_manager.ensure_campaign("operator-work-item", campaign_id="cmp-work-item")
    session = session_manager.start_session("operator-work-item")
    session_manager.attach_campaign(
        session,
        campaign.campaign_id,
        campaign.workspace_path,
        canonical_memory_files=campaign.canonical_files,
        agent_memory_files=campaign.agent_memory_files,
    )
    session_manager.create_workflow_artifact(
        session=session,
        kind=WorkflowArtifactKind.CAMPAIGN_BRIEF,
        title="Campaign brief",
        data={
            "objective": "Find Telegram communities for AI founders",
            "target_audience": "AI founders",
            "geography": "Europe",
        },
    )
    session_manager.create_workflow_artifact(
        session=session,
        kind=WorkflowArtifactKind.COMMUNITY_SHORTLIST,
        title="Community shortlist",
        data={"communities": [{"name": "Old shortlist", "handle": "@old_shortlist"}]},
    )
    session_manager.replace_workflow_snapshot(
        session,
        WorkflowSnapshot(stage=WorkflowStage.DISCOVERY, summary="Discovery is in progress."),
    )
    work_item_manager.ensure_work_item(
        campaign.campaign_id,
        owner_role="discovery",
        work_type="discovery",
        goal="Refresh the shortlist.",
        status=WorkItemStatus.IN_PROGRESS,
    )

    discovery_output = f"""I refreshed the shortlist instead of routing straight to review.

Please approve this shortlist or tell me what to change before I move to strategy.

{DISCOVERY_JSON_MARKER}
```json
{{
  "summary": "Refreshed the discovery shortlist.",
  "recommended_next_step": "Review the shortlist.",
  "communities": [
    {{
      "name": "EU AI Founders",
      "handle": "@eu_ai_founders",
      "type": "group",
      "topic": "AI startups",
      "language": "English",
      "geography": "Europe",
      "relevance_score": 92,
      "promo_tolerance": "medium",
      "moderation_risk": "low",
      "reason": "Highly aligned with AI founders in Europe."
    }}
  ]
}}
```"""

    fake_content_block = MagicMock()
    fake_content_block.text = discovery_output
    fake_api_response = MagicMock()
    fake_api_response.content = [fake_content_block]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = fake_api_response

    with patch("anthropic.Anthropic", return_value=mock_client):
        orchestrator = PurposeBuiltOrchestrator(
            session_manager=session_manager,
            approval_manager=approval_manager,
            community_capability=StubCommunityCapability(),
            work_item_manager=work_item_manager,
            campaign_manager=campaign_manager,
        )
        response = orchestrator.handle_turn(
            session,
            TelegramUpdate(
                chat_id="chat-work-item",
                user_id="operator-work-item",
                text="Refresh the shortlist with the latest context.",
            ),
        )

    assert "approve this shortlist" in response.messages[0].text.lower()
    assert "move to strategy" in response.messages[0].text.lower()
    assert mock_client.messages.create.call_count == 1


def test_legacy_planning_approval_is_cancelled_when_released(tmp_path) -> None:
    session_store = JsonSessionStore(tmp_path / "sessions.json")
    approval_store = JsonApprovalStore(tmp_path / "approvals.json")
    session_manager = SessionManager(session_store)
    approval_manager = ApprovalManager(approval_store)
    session = session_manager.start_session("operator-legacy-approval")
    session_manager.create_workflow_artifact(
        session=session,
        kind=WorkflowArtifactKind.COMMUNITY_SHORTLIST,
        title="Community shortlist",
        data={"communities": [{"name": "EU AI Founders", "handle": "@eu_ai_founders"}]},
    )
    approval = approval_manager.create_pending(
        session.session_id,
        "community_shortlist",
        "Approve the shortlist before moving to strategy.",
    )
    session_manager.mark_pending_approval(session, approval.approval_id)

    with patch("anthropic.Anthropic", return_value=MagicMock()):
        orchestrator = PurposeBuiltOrchestrator(
            session_manager=session_manager,
            approval_manager=approval_manager,
        )
        orchestrator.handle_turn(
            session=session,
            update=TelegramUpdate(
                chat_id="chat-legacy",
                user_id="operator-legacy-approval",
                text="continue",
            ),
            pending_approval=approval,
        )

    resolved_approval = approval_manager.get(approval.approval_id)
    assert resolved_approval is not None
    assert resolved_approval.status is ApprovalStatus.CANCELLED
    assert "conversational review" in resolved_approval.resolution_note.lower()



def test_telegram_app_service_normalizes_escaped_newlines_in_new_command(tmp_path) -> None:
    session_store = JsonSessionStore(tmp_path / "sessions.json")
    approval_store = JsonApprovalStore(tmp_path / "approvals.json")
    session_manager = SessionManager(session_store)
    approval_manager = ApprovalManager(approval_store)
    service = TelegramAppService(
        session_manager=session_manager,
        approval_manager=approval_manager,
        orchestrator=EchoOrchestrator(),
        intake_coordinator=StructuredIntakeCoordinator(session_manager),
    )

    response = service.handle_update(
        TelegramUpdate(
            chat_id="chat-escaped",
            user_id="operator-escaped",
            text="/new Goal: Find Telegram communities for AI founders\\nAudience: AI founders\\nGeography: Europe",
            command="/new",
        )
    )

    active_session = session_manager.get_active_session("operator-escaped")
    assert active_session is not None
    campaign_brief = get_campaign_brief_artifact(active_session)
    snapshot = session_manager.get_workflow_snapshot(active_session)

    assert response.messages[0].text.count("\n") >= 2
    assert campaign_brief is not None
    assert campaign_brief.data["objective"] == "Find Telegram communities for AI founders"
    assert campaign_brief.data["target_audience"] == "AI founders"
    assert campaign_brief.data["geography"] == "Europe"
    assert snapshot.stage is WorkflowStage.DISCOVERY


def test_structured_intake_parses_multiple_inline_labels_on_one_line(tmp_path) -> None:
    session_store = JsonSessionStore(tmp_path / "sessions.json")
    approval_store = JsonApprovalStore(tmp_path / "approvals.json")
    session_manager = SessionManager(session_store)
    approval_manager = ApprovalManager(approval_store)
    service = TelegramAppService(
        session_manager=session_manager,
        approval_manager=approval_manager,
        orchestrator=EchoOrchestrator(),
        intake_coordinator=StructuredIntakeCoordinator(session_manager),
    )

    service.handle_update(
        TelegramUpdate(
            chat_id="chat-inline",
            user_id="operator-inline",
            text="/new Goal: Find Telegram communities for AI founders Audience: AI founders Geography: Europe",
            command="/new",
        )
    )

    active_session = session_manager.get_active_session("operator-inline")
    assert active_session is not None

    campaign_brief = get_campaign_brief_artifact(active_session)
    snapshot = session_manager.get_workflow_snapshot(active_session)

    assert campaign_brief is not None
    assert campaign_brief.data["objective"] == "Find Telegram communities for AI founders"
    assert campaign_brief.data["target_audience"] == "AI founders"
    assert campaign_brief.data["geography"] == "Europe"
    assert snapshot.stage is WorkflowStage.DISCOVERY


def test_structured_intake_does_not_overwrite_existing_brief_with_follow_up_ack(tmp_path) -> None:
    session_store = JsonSessionStore(tmp_path / "sessions.json")
    session_manager = SessionManager(session_store)
    intake = StructuredIntakeCoordinator(session_manager)
    session = session_manager.start_session("operator-follow-up")

    intake.ingest_operator_turn(
        session,
        "Goal: Find Telegram communities for AI founders Audience: AI founders Geography: Europe",
    )
    intake.ingest_operator_turn(session, "sure, let's kick off discovery")

    campaign_brief = get_campaign_brief_artifact(session)
    snapshot = session_manager.get_workflow_snapshot(session)

    assert campaign_brief is not None
    assert campaign_brief.data["objective"] == "Find Telegram communities for AI founders"
    assert campaign_brief.data["target_audience"] == "AI founders"
    assert campaign_brief.data["geography"] == "Europe"
    assert campaign_brief.data["notes"] == []
    assert snapshot.stage is WorkflowStage.DISCOVERY


def test_build_messages_deduplicates_and_trims_history() -> None:
    message_history = []
    for index in range(9):
        message_history.append({"role": "operator", "text": f"operator-{index}"})
        assistant_text = f"assistant-{index}"
        message_history.append({"role": "assistant", "text": assistant_text})
        message_history.append({"role": "assistant", "text": assistant_text})
    message_history.append({"role": "operator", "text": "operator-9"})

    built_messages = _build_messages(message_history)

    assert len(built_messages) == 13
    assert built_messages[-1] == {"role": "user", "content": "operator-9"}
    assert built_messages[0] == {"role": "user", "content": "operator-3"}
    assert built_messages.count({"role": "assistant", "content": "assistant-8"}) == 1


def test_discovery_agent_builds_multiple_search_queries_from_campaign_brief(tmp_path) -> None:
    session_store = JsonSessionStore(tmp_path / "sessions.json")
    session_manager = SessionManager(session_store)
    session = session_manager.start_session("operator-discovery-searches")
    session_manager.create_workflow_artifact(
        session=session,
        kind=WorkflowArtifactKind.CAMPAIGN_BRIEF,
        title="Campaign brief",
        data={
            "objective": "Find Telegram communities for AI founders",
            "target_audience": "AI founders",
            "geography": "Europe",
        },
    )

    agent = DiscoveryAgent(session_manager=session_manager)
    queries = agent._build_search_queries(session)

    assert queries[:2] == ["AI founders Europe", "AI founders"]
    assert "Berlin AI founders" in queries
    assert "AI startup founders Europe" in queries
    assert len(queries) == 8


def test_discovery_stage_persists_shortlist_and_keeps_review_in_discovery(tmp_path) -> None:
    session_store = JsonSessionStore(tmp_path / "sessions.json")
    approval_store = JsonApprovalStore(tmp_path / "approvals.json")
    session_manager = SessionManager(session_store)
    approval_manager = ApprovalManager(approval_store)
    intake = StructuredIntakeCoordinator(session_manager)
    session = session_manager.start_session("operator-5")
    intake.ingest_operator_turn(
        session,
        "Goal: Find Telegram communities for AI founders\nAudience: AI founders\nGeography: Europe",
    )

    discovery_output = f"""I found a strong initial shortlist for AI founder outreach in Europe.

Please approve this shortlist or tell me what to change before I move to strategy.

{DISCOVERY_JSON_MARKER}
```json
{{
  "summary": "Ranked three relevant AI founder communities.",
  "recommended_next_step": "Approve the shortlist to begin strategy work.",
  "communities": [
    {{
      "name": "EU AI Founders",
      "handle": "@eu_ai_founders",
      "type": "group",
      "topic": "AI startups",
      "language": "English",
      "geography": "Europe",
      "relevance_score": 92,
      "promo_tolerance": "medium",
      "moderation_risk": "low",
      "reason": "Highly aligned with early-stage AI founders in Europe.",
      "source_notes": ["Public founder-focused Telegram listing"]
    }}
  ]
}}
```"""

    # Build a fake Anthropic API response content block
    fake_content_block = MagicMock()
    fake_content_block.text = discovery_output

    fake_api_response = MagicMock()
    fake_api_response.content = [fake_content_block]

    # Seed message_history so the orchestrator has a current message to work with
    session.workflow_state.setdefault("message_history", [])
    session.workflow_state["message_history"].append(
        {"role": "operator", "content": "continue"}
    )

    mock_client = MagicMock()
    mock_client.messages.create.return_value = fake_api_response

    with patch("anthropic.Anthropic", return_value=mock_client):
        orchestrator = PurposeBuiltOrchestrator(
            session_manager=session_manager,
            approval_manager=approval_manager,
            community_capability=FakeDiscoveryCommunityCapability(),
            messaging_capability=FakeDiscoveryMessagingCapability(),
        )
        response = orchestrator.handle_turn(
            session=session,
            update=TelegramUpdate(chat_id="chat-1", user_id="operator-5", text="continue"),
        )

    assert DISCOVERY_JSON_MARKER not in response.messages[0].text
    assert "approve this shortlist" in response.messages[0].text.lower()
    assert "live telegram validation" in response.messages[0].text.lower()

    reloaded_session = JsonSessionStore(tmp_path / "sessions.json").get(session.session_id)
    assert reloaded_session is not None
    shortlist_artifacts = [
        artifact
        for artifact in session_manager.list_workflow_artifacts(reloaded_session)
        if artifact.kind is WorkflowArtifactKind.COMMUNITY_SHORTLIST
    ]
    assert len(shortlist_artifacts) == 1
    assert shortlist_artifacts[0].data["communities"][0]["name"] == "EU AI Founders"
    assert shortlist_artifacts[0].data["communities"][0]["community_id"] == "111"
    assert shortlist_artifacts[0].data["communities"][0]["member_count"] == 3200
    assert shortlist_artifacts[0].data["communities"][0]["verification_state"] == "live_confirmed"
    assert shortlist_artifacts[0].data["communities"][0]["recent_message_samples"]
    assert shortlist_artifacts[0].data["verification_counts"]["live_confirmed"] == 1
    assert "verification status:" in shortlist_artifacts[0].data["verification_summary"].lower()
    assert shortlist_artifacts[0].data["search_diagnostics"]["overview"]["accepted_shortlist_count"] == 1
    assert shortlist_artifacts[0].data["search_diagnostics"]["overview"]["queries_attempted"] >= 2

    pending_approval = approval_manager.get_pending_for_session(session.session_id)
    assert pending_approval is None

    snapshot = session_manager.get_workflow_snapshot(reloaded_session)
    assert snapshot.stage is WorkflowStage.DISCOVERY
    assert snapshot.data["community_shortlist_artifact_id"] == shortlist_artifacts[0].artifact_id


def test_discovery_enrichment_prefers_matched_username_for_profile_lookup(tmp_path) -> None:
    session_store = JsonSessionStore(tmp_path / "sessions.json")
    approval_store = JsonApprovalStore(tmp_path / "approvals.json")
    session_manager = SessionManager(session_store)
    approval_manager = ApprovalManager(approval_store)
    intake = StructuredIntakeCoordinator(session_manager)
    session = session_manager.start_session("operator-discovery-lookup")
    intake.ingest_operator_turn(
        session,
        "Goal: Find Telegram communities for AI founders\nAudience: AI founders\nGeography: Europe",
    )

    discovery_output = f"""I found a shortlist worth validating further.

Please approve this shortlist or tell me what to change before I move to strategy.

{DISCOVERY_JSON_MARKER}
```json
{{
  "summary": "Ranked one relevant AI founder community.",
  "recommended_next_step": "Approve the shortlist to begin strategy work.",
  "communities": [
    {{
      "name": "EU AI Founders",
      "handle": "@eu_ai_founders",
      "type": "group",
      "topic": "AI startups",
      "language": "English",
      "geography": "Europe",
      "relevance_score": 92,
      "promo_tolerance": "medium",
      "moderation_risk": "low",
      "reason": "Highly aligned with early-stage AI founders in Europe.",
      "source_notes": ["Based on training knowledge."]
    }}
  ]
}}
```"""

    fake_content_block = MagicMock()
    fake_content_block.text = discovery_output
    fake_api_response = MagicMock()
    fake_api_response.content = [fake_content_block]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = fake_api_response
    community_capability = UsernameFirstDiscoveryCommunityCapability()

    with patch("anthropic.Anthropic", return_value=mock_client):
        orchestrator = PurposeBuiltOrchestrator(
            session_manager=session_manager,
            approval_manager=approval_manager,
            community_capability=community_capability,
            messaging_capability=FakeDiscoveryMessagingCapability(),
        )
        orchestrator.handle_turn(
            session=session,
            update=TelegramUpdate(
                chat_id="chat-discovery",
                user_id="operator-discovery-lookup",
                text="continue",
            ),
        )

    shortlist = session_manager.get_latest_artifact_of_kind(session, WorkflowArtifactKind.COMMUNITY_SHORTLIST)
    assert shortlist is not None
    community = shortlist.data["communities"][0]
    assert community_capability.profile_lookups == ["@eu_ai_founders"]
    assert community["live_profile"]["community_id"] == "2258115941"
    assert community["verification_state"] == "live_confirmed"
    assert all("profile read failed" not in note.lower() for note in community["source_notes"])


def test_discovery_shortlist_retries_name_lookup_after_handle_miss(tmp_path) -> None:
    session_store = JsonSessionStore(tmp_path / "sessions.json")
    approval_store = JsonApprovalStore(tmp_path / "approvals.json")
    session_manager = SessionManager(session_store)
    approval_manager = ApprovalManager(approval_store)
    session = session_manager.start_session("operator-discovery-name-fallback")
    session_manager.create_workflow_artifact(
        session=session,
        kind=WorkflowArtifactKind.CAMPAIGN_BRIEF,
        title="Campaign brief",
        data={"objective": "Reach AI founders", "target_audience": "AI founders", "geography": "Europe"},
    )
    session_manager.replace_workflow_snapshot(
        session,
        WorkflowSnapshot(stage=WorkflowStage.DISCOVERY, summary="Ready for discovery."),
    )

    discovery_output = f"""I found a strong initial shortlist for AI founder outreach in Europe.

Please approve this shortlist or tell me what to change before I move to strategy.

{DISCOVERY_JSON_MARKER}
```json
{{
  "summary": "Ranked one relevant AI founder community.",
  "recommended_next_step": "Approve the shortlist to begin strategy work.",
  "communities": [
    {{
      "name": "EU AI Founders",
      "handle": "@eu_ai_founders",
      "type": "group",
      "topic": "AI startups",
      "language": "English",
      "geography": "Europe",
      "relevance_score": 92,
      "promo_tolerance": "medium",
      "moderation_risk": "low",
      "reason": "Highly aligned with early-stage AI founders in Europe.",
      "source_notes": ["Based on training knowledge."]
    }}
  ]
}}
```"""

    fake_content_block = MagicMock()
    fake_content_block.text = discovery_output
    fake_api_response = MagicMock()
    fake_api_response.content = [fake_content_block]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = fake_api_response
    community_capability = HandleFallbackDiscoveryCommunityCapability()

    with patch("anthropic.Anthropic", return_value=mock_client):
        orchestrator = PurposeBuiltOrchestrator(
            session_manager=session_manager,
            approval_manager=approval_manager,
            community_capability=community_capability,
            messaging_capability=FakeDiscoveryMessagingCapability(),
        )
        orchestrator.handle_turn(
            session=session,
            update=TelegramUpdate(
                chat_id="chat-discovery",
                user_id="operator-discovery-name-fallback",
                text="continue",
            ),
        )

    shortlist = session_manager.get_latest_artifact_of_kind(session, WorkflowArtifactKind.COMMUNITY_SHORTLIST)
    assert shortlist is not None
    community = shortlist.data["communities"][0]
    assert community_capability.search_queries[:2] == ["AI founders Europe", "AI founders"]
    assert "@eu_ai_founders" in community_capability.search_queries
    assert "AI Founders" in community_capability.search_queries
    assert community_capability.profile_lookups == ["@ai_founders_club"]
    assert community["handle"] == "@ai_founders_club"
    assert community["verification_state"] == "live_confirmed"
    assert any("matching community entity" in note.lower() for note in community["source_notes"])


def test_discovery_shortlist_defaults_to_training_knowledge_fallback_without_live_capabilities(tmp_path) -> None:
    session_store = JsonSessionStore(tmp_path / "sessions.json")
    approval_store = JsonApprovalStore(tmp_path / "approvals.json")
    session_manager = SessionManager(session_store)
    approval_manager = ApprovalManager(approval_store)
    session = session_manager.start_session("operator-discovery-fallback")

    artifact, _approval = persist_discovery_shortlist(
        session_manager=session_manager,
        approval_manager=approval_manager,
        session=session,
        shortlist_payload={
            "summary": "Ranked one relevant community.",
            "recommended_next_step": "Approve the shortlist to begin strategy work.",
            "verification_summary": "Verification status: 0 live-confirmed, 0 search-confirmed only, 1 training-knowledge fallback. Sampled recent messages for 0 communities.",
            "verification_counts": {
                "live_confirmed": 0,
                "search_confirmed": 0,
                "training_knowledge_fallback": 1,
            },
            "communities": [
                {
                    "name": "EU AI Founders",
                    "handle": "@eu_ai_founders",
                    "verification_state": "training_knowledge_fallback",
                    "source_notes": ["Based on training knowledge."],
                }
            ],
        },
    )

    assert artifact.data["communities"][0]["verification_state"] == "training_knowledge_fallback"
    assert artifact.data["verification_counts"]["training_knowledge_fallback"] == 1


def test_strategy_stage_persists_playbook_and_keeps_review_in_strategy(tmp_path) -> None:
    session_store = JsonSessionStore(tmp_path / "sessions.json")
    approval_store = JsonApprovalStore(tmp_path / "approvals.json")
    session_manager = SessionManager(session_store)
    approval_manager = ApprovalManager(approval_store)
    session = session_manager.start_session("operator-strategy-gate")
    session_manager.create_workflow_artifact(
        session=session,
        kind=WorkflowArtifactKind.CAMPAIGN_BRIEF,
        title="Campaign brief",
        data={"objective": "Reach AI founders", "target_audience": "AI founders", "geography": "Europe"},
    )
    session_manager.create_workflow_artifact(
        session=session,
        kind=WorkflowArtifactKind.COMMUNITY_SHORTLIST,
        title="Community shortlist",
        data={
            "summary": "Ranked one community.",
            "communities": [
                {"name": "EU AI Founders", "handle": "@eu_ai_founders", "relevance_score": 92},
            ],
        },
    )
    session_manager.replace_workflow_snapshot(
        session,
        WorkflowSnapshot(stage=WorkflowStage.STRATEGY, summary="Ready for strategy."),
    )

    strategy_output = """Lead with operator insight, keep the CTA soft, and save direct asks for later.

STRATEGY_PLAYBOOK_JSON
```json
{
  "campaign_strategy_summary": "Start with value-first founder messaging.",
  "communities": [
    {
      "name": "EU AI Founders",
      "handle": "@eu_ai_founders",
      "messaging_angle": "Peer-to-peer founder insight",
      "message_format": "text",
      "frequency": "once",
      "timing": "weekday mornings",
      "risk_notes": "Keep the tone educational."
    }
  ]
}
```"""

    fake_content_block = MagicMock()
    fake_content_block.text = strategy_output
    fake_api_response = MagicMock()
    fake_api_response.content = [fake_content_block]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = fake_api_response

    with patch("anthropic.Anthropic", return_value=mock_client):
        orchestrator = PurposeBuiltOrchestrator(
            session_manager=session_manager,
            approval_manager=approval_manager,
            community_capability=StubCommunityCapability(),
            account_capability=StubAccountCapability(),
        )
        response = orchestrator.handle_turn(
            session=session,
            update=TelegramUpdate(chat_id="chat-strategy", user_id="operator-strategy-gate", text="continue"),
        )

    assert "operator insight" in response.messages[0].text.lower()
    pending_approval = approval_manager.get_pending_for_session(session.session_id)
    assert pending_approval is None
    snapshot = session_manager.get_workflow_snapshot(session)
    assert snapshot.stage is WorkflowStage.STRATEGY
    assert "strategy_playbook_artifact_id" in snapshot.data
    assert (
        session_manager.get_latest_artifact_of_kind(session, WorkflowArtifactKind.ACCOUNT_ASSIGNMENT_PLAN) is None
    )


def test_strategy_agent_reads_campaign_memory_and_updates_working_memory(tmp_path) -> None:
    session_store = JsonSessionStore(tmp_path / "sessions.json")
    session_manager = SessionManager(session_store)
    campaign_manager = CampaignManager(tmp_path / "campaigns")
    session = session_manager.start_session("operator-strategy-memory")
    campaign = campaign_manager.ensure_campaign("operator-strategy-memory", campaign_id="cmp-strategy-memory")
    session_manager.attach_campaign(
        session,
        campaign.campaign_id,
        campaign.workspace_path,
        canonical_memory_files=campaign.canonical_files,
        agent_memory_files=campaign.agent_memory_files,
    )
    session_manager.create_workflow_artifact(
        session=session,
        kind=WorkflowArtifactKind.CAMPAIGN_BRIEF,
        title="Campaign brief",
        data={"objective": "Reach AI founders", "target_audience": "AI founders", "geography": "Europe"},
    )
    session_manager.create_workflow_artifact(
        session=session,
        kind=WorkflowArtifactKind.COMMUNITY_SHORTLIST,
        title="Community shortlist",
        data={
            "summary": "Ranked one community.",
            "communities": [{"name": "EU AI Founders", "handle": "@eu_ai_founders", "relevance_score": 92}],
        },
    )
    workspace = Path(campaign.workspace_path)
    (workspace / "strategy.md").write_text("# Strategy\n\nCanonical campaign direction.\n", encoding="utf-8")
    (workspace / "agents" / "strategy.md").write_text("# Strategy Notes\n\nLocal strategist note.\n", encoding="utf-8")

    strategy_output = """Lead with operator insight, keep the CTA soft, and save direct asks for later.

STRATEGY_PLAYBOOK_JSON
```json
{
  "campaign_strategy_summary": "Start with value-first founder messaging.",
  "communities": [
    {
      "name": "EU AI Founders",
      "handle": "@eu_ai_founders",
      "messaging_angle": "Peer-to-peer founder insight",
      "message_format": "text",
      "frequency": "once",
      "timing": "weekday mornings",
      "risk_notes": "Keep the tone educational."
    }
  ]
}
```"""

    fake_content_block = MagicMock()
    fake_content_block.text = strategy_output
    fake_api_response = MagicMock()
    fake_api_response.content = [fake_content_block]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = fake_api_response

    with patch("anthropic.Anthropic", return_value=mock_client):
        agent = StrategyAgent(session_manager=session_manager, community_capability=StubCommunityCapability())
        operator_text, artifact = agent.run(session, operator_message="Tighten the founder angle.")

    assert "operator insight" in operator_text.lower()
    assert artifact is not None
    system_blocks = mock_client.messages.create.call_args.kwargs["system"]
    assert any("campaign_memory_snapshot" in block["text"] for block in system_blocks)
    assert any("Local strategist note." in block["text"] for block in system_blocks)
    updated_notes = (workspace / "agents" / "strategy.md").read_text(encoding="utf-8")
    assert "Current Direction" in updated_notes
    assert "Tighten the founder angle." in updated_notes


def test_strategy_review_turn_handles_ambiguous_follow_up_without_llm_call(tmp_path) -> None:
    session_store = JsonSessionStore(tmp_path / "sessions.json")
    approval_store = JsonApprovalStore(tmp_path / "approvals.json")
    session_manager = SessionManager(session_store)
    approval_manager = ApprovalManager(approval_store)
    work_item_manager = WorkItemManager(tmp_path / "campaigns")
    session = session_manager.start_session("operator-strategy-ambiguous")
    session_manager.attach_campaign(
        session,
        "cmp-strategy-ambiguous",
        str((tmp_path / "campaigns" / "cmp-strategy-ambiguous").resolve()),
    )
    session_manager.create_workflow_artifact(
        session=session,
        kind=WorkflowArtifactKind.STRATEGY_PLAYBOOK,
        title="Strategy playbook",
        data={
            "campaign_strategy_summary": "Start with value-first founder messaging.",
            "communities": [{"name": "EU AI Founders", "handle": "@eu_ai_founders"}],
        },
    )
    session_manager.replace_workflow_snapshot(
        session,
        WorkflowSnapshot(
            stage=WorkflowStage.STRATEGY,
            summary="Strategy playbook ready for operator review.",
        ),
    )

    mock_client = MagicMock()

    with patch("anthropic.Anthropic", return_value=mock_client):
        orchestrator = PurposeBuiltOrchestrator(
            session_manager=session_manager,
            approval_manager=approval_manager,
            work_item_manager=work_item_manager,
        )
        response = orchestrator.handle_turn(
            session=session,
            update=TelegramUpdate(
                chat_id="chat-strategy",
                user_id="operator-strategy-ambiguous",
                text="what's next?",
            ),
        )

    assert "strategy draft ready" in response.messages[0].text.lower()
    assert mock_client.messages.create.call_count == 0
    assert approval_manager.get_pending_for_session(session.session_id) is None
    primary_work_item = work_item_manager.get_primary_open_item("cmp-strategy-ambiguous")
    assert primary_work_item is not None
    assert primary_work_item.work_type == "strategy"
    assert primary_work_item.status is WorkItemStatus.REVIEW_PENDING


def test_account_manager_agent_reads_campaign_memory_and_updates_working_memory(tmp_path) -> None:
    session_store = JsonSessionStore(tmp_path / "sessions.json")
    session_manager = SessionManager(session_store)
    campaign_manager = CampaignManager(tmp_path / "campaigns")
    session = session_manager.start_session("operator-account-memory")
    campaign = campaign_manager.ensure_campaign("operator-account-memory", campaign_id="cmp-account-memory")
    session_manager.attach_campaign(
        session,
        campaign.campaign_id,
        campaign.workspace_path,
        canonical_memory_files=campaign.canonical_files,
        agent_memory_files=campaign.agent_memory_files,
    )
    session_manager.create_workflow_artifact(
        session=session,
        kind=WorkflowArtifactKind.CAMPAIGN_BRIEF,
        title="Campaign brief",
        data={"objective": "Reach AI founders", "target_audience": "AI founders", "geography": "Europe"},
    )
    session_manager.create_workflow_artifact(
        session=session,
        kind=WorkflowArtifactKind.COMMUNITY_SHORTLIST,
        title="Community shortlist",
        data={
            "summary": "Ranked one community.",
            "communities": [{"name": "EU AI Founders", "handle": "@eu_ai_founders", "relevance_score": 92}],
        },
    )
    session_manager.create_workflow_artifact(
        session=session,
        kind=WorkflowArtifactKind.STRATEGY_PLAYBOOK,
        title="Strategy playbook",
        data={
            "campaign_strategy_summary": "Start with value-first founder messaging.",
            "communities": [
                {
                    "name": "EU AI Founders",
                    "handle": "@eu_ai_founders",
                    "messaging_angle": "Peer-to-peer founder insight",
                    "message_format": "text",
                    "frequency": "once",
                    "timing": "weekday mornings",
                    "risk_notes": "Keep the tone educational.",
                }
            ],
        },
    )
    workspace = Path(campaign.workspace_path)
    (workspace / "strategy.md").write_text("# Strategy\n\nCanonical campaign direction.\n", encoding="utf-8")
    (workspace / "agents" / "account_manager.md").write_text(
        "# Account Manager Notes\n\nLocal assignment note.\n",
        encoding="utf-8",
    )

    account_plan_output = """Use one senior account for the first wave and keep spacing conservative.

ACCOUNT_ASSIGNMENT_PLAN_JSON
```json
{
  "plan_summary": "Use one senior account for the first founder-facing wave.",
  "assignments": [
    {
      "community_name": "EU AI Founders",
      "community_handle": "@eu_ai_founders",
      "assigned_account": "account_senior_1",
      "scheduled_posts": [
        {
          "day_offset": 0,
          "time_window": "09:00-11:00",
          "message_angle": "Founder insight",
          "message_text": "Sharing one practical founder insight for discussion."
        }
      ],
      "risk_level": "low",
      "notes": "Lead with value."
    }
  ]
}
```"""

    fake_content_block = MagicMock()
    fake_content_block.text = account_plan_output
    fake_api_response = MagicMock()
    fake_api_response.content = [fake_content_block]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = fake_api_response

    with patch("anthropic.Anthropic", return_value=mock_client):
        agent = AccountManagerAgent(session_manager=session_manager, account_capability=StubAccountCapability())
        operator_text, artifact, approval = agent.run(session, operator_message="Be conservative on pacing.")

    assert "senior account" in operator_text.lower()
    assert artifact is not None
    assert approval is None
    system_blocks = mock_client.messages.create.call_args.kwargs["system"]
    assert any("campaign_memory_snapshot" in block["text"] for block in system_blocks)
    assert any("Local assignment note." in block["text"] for block in system_blocks)
    updated_notes = (workspace / "agents" / "account_manager.md").read_text(encoding="utf-8")
    assert "Current Plan" in updated_notes
    assert "Be conservative on pacing." in updated_notes


def test_orchestrator_routes_from_primary_work_item_before_snapshot_stage(tmp_path) -> None:
    session_store = JsonSessionStore(tmp_path / "sessions.json")
    approval_store = JsonApprovalStore(tmp_path / "approvals.json")
    session_manager = SessionManager(session_store)
    approval_manager = ApprovalManager(approval_store)
    work_item_manager = WorkItemManager(tmp_path / "campaigns")
    campaign_manager = CampaignManager(tmp_path / "campaigns")
    session = session_manager.start_session("operator-work-route")
    campaign = campaign_manager.ensure_campaign("operator-work-route", campaign_id="cmp-work-route")
    session_manager.attach_campaign(
        session,
        campaign.campaign_id,
        campaign.workspace_path,
        canonical_memory_files=campaign.canonical_files,
        agent_memory_files=campaign.agent_memory_files,
    )
    session_manager.create_workflow_artifact(
        session=session,
        kind=WorkflowArtifactKind.CAMPAIGN_BRIEF,
        title="Campaign brief",
        data={"objective": "Reach AI founders", "target_audience": "AI founders", "geography": "Europe"},
    )
    session_manager.create_workflow_artifact(
        session=session,
        kind=WorkflowArtifactKind.COMMUNITY_SHORTLIST,
        title="Community shortlist",
        data={
            "summary": "Ranked one community.",
            "communities": [{"name": "EU AI Founders", "handle": "@eu_ai_founders", "relevance_score": 92}],
        },
    )
    session_manager.replace_workflow_snapshot(
        session,
        WorkflowSnapshot(stage=WorkflowStage.INTAKE, summary="Still in compatibility intake mode."),
    )
    work_item_manager.ensure_work_item(
        campaign.campaign_id,
        owner_role="strategy",
        work_type="strategy",
        goal="Turn the approved shortlist into a founder-first messaging playbook.",
        status=WorkItemStatus.IN_PROGRESS,
    )

    strategy_output = """Lead with operator insight, keep the CTA soft, and save direct asks for later.

STRATEGY_PLAYBOOK_JSON
```json
{
  "campaign_strategy_summary": "Start with value-first founder messaging.",
  "communities": [
    {
      "name": "EU AI Founders",
      "handle": "@eu_ai_founders",
      "messaging_angle": "Peer-to-peer founder insight",
      "message_format": "text",
      "frequency": "once",
      "timing": "weekday mornings",
      "risk_notes": "Keep the tone educational."
    }
  ]
}
```"""

    fake_content_block = MagicMock()
    fake_content_block.text = strategy_output
    fake_api_response = MagicMock()
    fake_api_response.content = [fake_content_block]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = fake_api_response

    with patch("anthropic.Anthropic", return_value=mock_client):
        orchestrator = PurposeBuiltOrchestrator(
            session_manager=session_manager,
            approval_manager=approval_manager,
            community_capability=StubCommunityCapability(),
            work_item_manager=work_item_manager,
            campaign_manager=campaign_manager,
        )
        response = orchestrator.handle_turn(
            session=session,
            update=TelegramUpdate(chat_id="chat-work-route", user_id="operator-work-route", text="continue"),
        )

    assert "operator insight" in response.messages[0].text.lower()
    snapshot = session_manager.get_workflow_snapshot(session)
    assert snapshot.stage is WorkflowStage.STRATEGY
    primary_work_item = work_item_manager.get_primary_open_item(campaign.campaign_id)
    assert primary_work_item is not None
    assert primary_work_item.work_type == "strategy"
    assert primary_work_item.status is WorkItemStatus.REVIEW_PENDING

    llm_messages = mock_client.messages.create.call_args.kwargs["messages"]
    assert len(llm_messages) == 1
    assert "Primary work item goal: Turn the approved shortlist into a founder-first messaging playbook." in llm_messages[0]["content"]


def test_discovery_checkpoint_revision_request_is_not_treated_as_approval(tmp_path) -> None:
    session_store = JsonSessionStore(tmp_path / "sessions.json")
    approval_store = JsonApprovalStore(tmp_path / "approvals.json")
    session_manager = SessionManager(session_store)
    approval_manager = ApprovalManager(approval_store)
    intake = StructuredIntakeCoordinator(session_manager)
    session = session_manager.start_session("operator-discovery-revision")
    intake.ingest_operator_turn(
        session,
        "Goal: Find Telegram communities for AI founders\nAudience: AI founders\nGeography: Europe",
    )
    persist_discovery_shortlist(
        session_manager,
        approval_manager,
        session,
        shortlist_payload={
            "summary": "Ranked one relevant AI founder community.",
            "recommended_next_step": "Approve the shortlist to begin strategy work.",
            "communities": [
                {
                    "name": "EU AI Founders",
                    "handle": "@eu_ai_founders",
                    "type": "group",
                    "topic": "AI startups",
                    "language": "English",
                    "geography": "Europe",
                    "relevance_score": 92,
                    "promo_tolerance": "medium",
                    "moderation_risk": "low",
                    "reason": "Highly aligned with early-stage AI founders in Europe.",
                    "source_notes": ["Based on training knowledge."],
                }
            ],
        },
    )
    assert approval_manager.get_pending_for_session(session.session_id) is None

    revised_discovery_output = f"""I expanded the search and tightened the founder fit.

Please approve this shortlist or tell me what to change before I move to strategy.

{DISCOVERY_JSON_MARKER}
```json
{{
  "summary": "Ranked one revised AI founder community.",
  "recommended_next_step": "Approve the shortlist to begin strategy work.",
  "communities": [
    {{
      "name": "European Startup Network",
      "handle": "@european_startup_network",
      "type": "group",
      "topic": "Startups",
      "language": "English",
      "geography": "Europe",
      "relevance_score": 90,
      "promo_tolerance": "medium",
      "moderation_risk": "low",
      "reason": "Broader founder coverage with a strong European footprint.",
      "source_notes": ["Based on training knowledge."]
    }}
  ]
}}
```"""

    fake_content_block = MagicMock()
    fake_content_block.text = revised_discovery_output
    fake_api_response = MagicMock()
    fake_api_response.content = [fake_content_block]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = fake_api_response

    with patch("anthropic.Anthropic", return_value=mock_client):
        orchestrator = PurposeBuiltOrchestrator(
            session_manager=session_manager,
            approval_manager=approval_manager,
            community_capability=StubCommunityCapability(),
            account_capability=StubAccountCapability(),
        )
        response = orchestrator.handle_turn(
            session=session,
            update=TelegramUpdate(
                chat_id="chat-discovery",
                user_id="operator-discovery-revision",
                text="okay, should we search a little more?",
            ),
        )

    assert "expanded the search" in response.messages[0].text.lower()
    assert mock_client.messages.create.call_count == 1
    assert approval_manager.get_pending_for_session(session.session_id) is None
    assert session_manager.get_latest_artifact_of_kind(session, WorkflowArtifactKind.STRATEGY_PLAYBOOK) is None


def test_approval_classifier_treats_search_more_request_as_rejection() -> None:
    assert _classify_approval_response("okay, should we search a little more?") is False


def test_strategy_agent_invalid_playbook_does_not_persist_artifact(tmp_path) -> None:
    session_store = JsonSessionStore(tmp_path / "sessions.json")
    session_manager = SessionManager(session_store)
    session = session_manager.start_session("operator-invalid-strategy")
    session_manager.create_workflow_artifact(
        session=session,
        kind=WorkflowArtifactKind.CAMPAIGN_BRIEF,
        title="Campaign brief",
        data={"objective": "Reach AI founders"},
    )
    session_manager.create_workflow_artifact(
        session=session,
        kind=WorkflowArtifactKind.COMMUNITY_SHORTLIST,
        title="Community shortlist",
        data={"communities": [{"name": "EU AI Founders", "handle": "@eu_ai_founders"}]},
    )

    invalid_output = """This is directionally right, but the JSON is incomplete.

STRATEGY_PLAYBOOK_JSON
```json
{
  "campaign_strategy_summary": "Start with value-first founder messaging.",
  "communities": [
    {
      "name": "EU AI Founders",
      "handle": "@eu_ai_founders",
      "message_format": "text"
    }
  ]
}
```"""

    fake_content_block = MagicMock()
    fake_content_block.text = invalid_output
    fake_api_response = MagicMock()
    fake_api_response.content = [fake_content_block]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = fake_api_response

    with patch("anthropic.Anthropic", return_value=mock_client):
        agent = StrategyAgent(
            session_manager=session_manager,
            community_capability=StubCommunityCapability(),
        )
        operator_text, artifact = agent.run(session)

    assert "did not save or advance this strategy" in operator_text.lower()
    assert artifact is None
    assert session_manager.get_latest_artifact_of_kind(session, WorkflowArtifactKind.STRATEGY_PLAYBOOK) is None


def test_strategy_agent_reuses_persisted_discovery_profiles_in_capability_context(tmp_path) -> None:
    session_store = JsonSessionStore(tmp_path / "sessions.json")
    session_manager = SessionManager(session_store)
    session = session_manager.start_session("operator-strategy-reuse")
    session_manager.create_workflow_artifact(
        session=session,
        kind=WorkflowArtifactKind.COMMUNITY_SHORTLIST,
        title="Community shortlist",
        data={
            "communities": [
                {
                    "name": "EU AI Founders",
                    "handle": "@eu_ai_founders",
                    "community_id": "2258115941",
                    "live_profile": {
                        "community_id": "2258115941",
                        "member_count": 3200,
                        "verified": True,
                        "restricted": False,
                        "scam": False,
                        "description": "Peer-to-peer AI founder discussion.",
                    },
                }
            ]
        },
    )

    capability = FailingStrategyCommunityCapability()
    agent = StrategyAgent(session_manager=session_manager, community_capability=capability)

    context_lines = agent._build_capability_context(session)

    assert capability.calls == []
    assert context_lines[0] == "Community capability context:"
    assert "persisted_discovery_profile" in context_lines[1]
    assert "Peer-to-peer AI founder discussion." in context_lines[1]
    assert "3200" in context_lines[1]


def test_shortlist_prompt_safe_payload_keeps_verification_fields() -> None:
    shortlist_payload = {
        "summary": "Ranked one relevant community.",
        "recommended_next_step": "Approve the shortlist to begin strategy work.",
        "verification_summary": "Verification status: 1 live-confirmed, 0 search-confirmed only, 0 training-knowledge fallback. Sampled recent messages for 1 communities.",
        "coverage_summary": "Coverage notes: top-ranked communities skew toward direct live confirmation.",
        "verification_counts": {
            "live_confirmed": 1,
            "search_confirmed": 0,
            "training_knowledge_fallback": 0,
        },
        "communities": [
            {
                "name": "EU AI Founders",
                "handle": "@eu_ai_founders",
                "verification_state": "live_confirmed",
                "search_mode": "exact",
                "match_kind": "exact_handle",
                "evidence_summary": "Exact live match; profile attached; recent messages sampled.",
                "source_notes": ["Live Telegram search found a matching community entity."],
            }
        ],
    }

    strategy_payload = strategy_prompt_safe_artifact_data(WorkflowArtifactKind.COMMUNITY_SHORTLIST, shortlist_payload)
    account_payload = account_prompt_safe_artifact_data(WorkflowArtifactKind.COMMUNITY_SHORTLIST, shortlist_payload)

    assert strategy_payload["verification_counts"]["live_confirmed"] == 1
    assert strategy_payload["coverage_summary"].startswith("Coverage notes:")
    assert strategy_payload["communities"][0]["verification_state"] == "live_confirmed"
    assert strategy_payload["communities"][0]["evidence_summary"].startswith("Exact live match")
    assert account_payload["verification_summary"].startswith("Verification status:")
    assert account_payload["coverage_summary"].startswith("Coverage notes:")
    assert account_payload["communities"][0]["verification_state"] == "live_confirmed"
    assert account_payload["communities"][0]["match_kind"] == "exact_handle"
    assert "search_diagnostics" not in strategy_payload
    assert "search_diagnostics" not in account_payload


def test_discovery_agent_uses_compact_search_summary_and_persists_diagnostics(tmp_path) -> None:
    session_store = JsonSessionStore(tmp_path / "sessions.json")
    approval_store = JsonApprovalStore(tmp_path / "approvals.json")
    session_manager = SessionManager(session_store)
    approval_manager = ApprovalManager(approval_store)
    session = session_manager.start_session("operator-search-summary")
    session_manager.create_workflow_artifact(
        session=session,
        kind=WorkflowArtifactKind.CAMPAIGN_BRIEF,
        title="Campaign brief",
        data={
            "objective": "Find Telegram communities for AI founders",
            "target_audience": "AI founders",
            "geography": "Europe",
        },
    )

    discovery_output = f"""I found a strong shortlist for AI founder outreach in Europe.

Please approve this shortlist or tell me what to change before I move to strategy.

{DISCOVERY_JSON_MARKER}
```json
{{
  "summary": "Ranked one relevant AI founder community.",
  "recommended_next_step": "Approve the shortlist to begin strategy work.",
  "communities": [
    {{
      "name": "EU AI Founders",
      "handle": "@eu_ai_founders",
      "type": "group",
      "topic": "AI startups",
      "language": "English",
      "geography": "Europe",
      "relevance_score": 92,
      "promo_tolerance": "medium",
      "moderation_risk": "low",
      "reason": "Highly aligned with early-stage AI founders in Europe.",
      "source_notes": ["Based on training knowledge."]
    }}
  ]
}}
```"""

    fake_content_block = MagicMock()
    fake_content_block.text = discovery_output
    fake_api_response = MagicMock()
    fake_api_response.content = [fake_content_block]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = fake_api_response

    with patch("anthropic.Anthropic", return_value=mock_client):
        agent = DiscoveryAgent(
            session_manager=session_manager,
            approval_manager=approval_manager,
            community_capability=QueryAwareDiscoveryCommunityCapability(),
            messaging_capability=FakeDiscoveryMessagingCapability(),
        )
        _operator_text, artifact, _approval = agent.run(session, "continue")

    assert artifact is not None
    prompt_message = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "community_search_summary" in prompt_message
    assert "community_searches" not in prompt_message
    assert '"top_candidates"' in prompt_message

    diagnostics = artifact.data["search_diagnostics"]
    assert diagnostics["overview"]["queries_attempted"] == 8
    assert diagnostics["overview"]["unique_candidates"] >= 3
    assert diagnostics["overview"]["accepted_shortlist_count"] == 1
    assert diagnostics["overview"]["refinement_triggered"] is False
    assert diagnostics["overview"]["refinement_queries_attempted"] == 0
    assert diagnostics["harvest"]["first_pass_queries"] == 8
    assert diagnostics["validation"]["accepted_shortlist_count"] == 1
    assert diagnostics["queries"][1]["query"] == "AI founders"
    assert diagnostics["queries"][1]["query_family"] == "core"
    assert diagnostics["queries"][1]["search_mode"] == "harvest"
    assert diagnostics["queries"][1]["search_pass"] == "first_pass"
    assert diagnostics["queries"][1]["result_limit"] == 15
    assert diagnostics["queries"][1]["unique_candidates_added"] == 2
    assert diagnostics["top_candidates"][0]["name"] == "EU AI Founders"


def test_discovery_enrichment_uses_harvested_pool_before_exact_requeries(tmp_path) -> None:
    session_store = JsonSessionStore(tmp_path / "sessions.json")
    approval_store = JsonApprovalStore(tmp_path / "approvals.json")
    session_manager = SessionManager(session_store)
    approval_manager = ApprovalManager(approval_store)
    session = session_manager.start_session("operator-harvest-first")
    session_manager.create_workflow_artifact(
        session=session,
        kind=WorkflowArtifactKind.CAMPAIGN_BRIEF,
        title="Campaign brief",
        data={
            "objective": "Find Telegram communities for AI founders",
            "target_audience": "AI founders",
            "geography": "Europe",
        },
    )

    discovery_output = f"""I found a strong shortlist for AI founder outreach in Europe.

Please approve this shortlist or tell me what to change before I move to strategy.

{DISCOVERY_JSON_MARKER}
```json
{{
  "summary": "Ranked one relevant AI founder community.",
  "recommended_next_step": "Approve the shortlist to begin strategy work.",
  "communities": [
    {{
      "name": "AI Founders Club",
      "handle": "@ai_founders_club",
      "type": "group",
      "topic": "AI startups",
      "language": "English",
      "geography": "Europe",
      "relevance_score": 92,
      "promo_tolerance": "medium",
      "moderation_risk": "low",
      "reason": "Highly aligned with early-stage AI founders in Europe.",
      "source_notes": ["Based on training knowledge."]
    }}
  ]
}}
```"""

    fake_content_block = MagicMock()
    fake_content_block.text = discovery_output
    fake_api_response = MagicMock()
    fake_api_response.content = [fake_content_block]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = fake_api_response
    capability = HarvestFirstDiscoveryCommunityCapability()

    with patch("anthropic.Anthropic", return_value=mock_client):
        agent = DiscoveryAgent(
            session_manager=session_manager,
            approval_manager=approval_manager,
            community_capability=capability,
            messaging_capability=FakeDiscoveryMessagingCapability(),
        )
        _operator_text, artifact, _approval = agent.run(session, "continue")

    assert artifact is not None
    community = artifact.data["communities"][0]
    harvest_queries = [call for call in capability.search_calls if call[1] == "harvest"]
    exact_queries = [call for call in capability.search_calls if call[1] == "exact"]

    assert harvest_queries
    assert ("AI founders", "harvest", 15) in harvest_queries
    assert exact_queries == []
    assert capability.profile_lookups == ["@ai_founders_club"]
    assert community["verification_state"] == "live_confirmed"
    assert community["matched_query"] == "AI founders"
    assert community["search_source"] == "fake_harvest"
    assert community["search_mode"] == "harvest"
    assert community["lookup_ref"] == "@ai_founders_club"


def test_discovery_agent_runs_one_bounded_refinement_pass_for_sparse_first_pass(tmp_path) -> None:
    session_store = JsonSessionStore(tmp_path / "sessions.json")
    approval_store = JsonApprovalStore(tmp_path / "approvals.json")
    session_manager = SessionManager(session_store)
    approval_manager = ApprovalManager(approval_store)
    session = session_manager.start_session("operator-refinement-pass")
    session_manager.create_workflow_artifact(
        session=session,
        kind=WorkflowArtifactKind.CAMPAIGN_BRIEF,
        title="Campaign brief",
        data={
            "objective": "Find Telegram communities for AI founders",
            "target_audience": "AI founders",
            "geography": "Europe",
        },
    )

    discovery_output = f"""I found a strong shortlist for AI founder outreach in Europe.

Please approve this shortlist or tell me what to change before I move to strategy.

{DISCOVERY_JSON_MARKER}
```json
{{
  "summary": "Ranked one relevant AI founder community.",
  "recommended_next_step": "Approve the shortlist to begin strategy work.",
  "communities": [
    {{
      "name": "AI Founders Club",
      "handle": "@ai_founders_club",
      "type": "group",
      "topic": "AI startups",
      "language": "English",
      "geography": "Europe",
      "relevance_score": 92,
      "promo_tolerance": "medium",
      "moderation_risk": "low",
      "reason": "Highly aligned with early-stage AI founders in Europe.",
      "source_notes": ["Based on training knowledge."]
    }}
  ]
}}
```"""

    fake_content_block = MagicMock()
    fake_content_block.text = discovery_output
    fake_api_response = MagicMock()
    fake_api_response.content = [fake_content_block]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = fake_api_response
    capability = RefinementAwareDiscoveryCommunityCapability()

    with patch("anthropic.Anthropic", return_value=mock_client):
        agent = DiscoveryAgent(
            session_manager=session_manager,
            approval_manager=approval_manager,
            community_capability=capability,
            messaging_capability=FakeDiscoveryMessagingCapability(),
        )
        _operator_text, artifact, _approval = agent.run(session, "continue")

    assert artifact is not None
    diagnostics = artifact.data["search_diagnostics"]
    refinement_queries = [entry for entry in diagnostics["queries"] if entry["search_pass"] == "refinement"]

    assert ("Paris AI founders", "harvest", 15) in capability.search_calls
    assert diagnostics["overview"]["refinement_triggered"] is True
    assert diagnostics["overview"]["refinement_queries_attempted"] == len(refinement_queries)
    assert diagnostics["refinement"]["triggered"] is True
    assert diagnostics["refinement"]["reason"] == "sparse_first_pass"
    assert diagnostics["refinement"]["productive_query_families"] == ["core"]
    assert diagnostics["refinement"]["added_unique_candidates"] >= 1
    assert diagnostics["refinement"]["unique_candidates_before"] == 1
    assert diagnostics["refinement"]["unique_candidates_after"] >= 2
    assert diagnostics["refinement"]["attempted_queries"][0] == "Paris AI founders"
    assert diagnostics["harvest"]["refinement_queries"] == len(refinement_queries)


def test_discovery_enrichment_summarizes_coverage_and_ranks_exact_matches_above_broader_live_matches() -> None:
    agent = DiscoveryAgent(
        community_capability=MixedEvidenceDiscoveryCommunityCapability(),
        messaging_capability=FakeDiscoveryMessagingCapability(),
    )
    shortlist_payload = {
        "summary": "Ranked three relevant founder communities.",
        "recommended_next_step": "Approve the shortlist to begin strategy work.",
        "communities": [
            {
                "name": "AI Founders Club",
                "handle": "@ai_founders_club",
                "type": "group",
                "topic": "AI startups",
                "language": "English",
                "geography": "Europe",
                "relevance_score": 92,
                "promo_tolerance": "medium",
                "moderation_risk": "low",
                "reason": "Broad founder fit.",
                "source_notes": ["Based on training knowledge."],
            },
            {
                "name": "EU AI Founders",
                "handle": "@eu_ai_founders",
                "type": "group",
                "topic": "AI startups",
                "language": "English",
                "geography": "Europe",
                "relevance_score": 92,
                "promo_tolerance": "medium",
                "moderation_risk": "low",
                "reason": "Exact Europe founder fit.",
                "source_notes": ["Based on training knowledge."],
            },
            {
                "name": "Hidden Founder Guild",
                "handle": "@hidden_founder_guild",
                "type": "group",
                "topic": "Founders",
                "language": "English",
                "geography": "Europe",
                "relevance_score": 92,
                "promo_tolerance": "low",
                "moderation_risk": "medium",
                "reason": "Possible fit if it exists.",
                "source_notes": ["Based on training knowledge."],
            },
        ],
    }
    brief_search_diagnostics = {
        "overview": {
            "queries_attempted": 2,
            "successful_queries": 1,
            "total_results": 1,
            "unique_candidates": 1,
            "refinement_triggered": False,
            "refinement_queries_attempted": 0,
        },
        "queries": [
            {
                "query": "AI founders",
                "query_family": "core",
                "search_pass": "first_pass",
                "success": True,
                "search_source": "fake_harvest",
                "search_mode": "harvest",
                "result_limit": 15,
                "fallback_used": False,
                "raw_result_count": 1,
                "unique_candidates_added": 1,
                "duplicate_or_unusable_results": 0,
                "error": "",
            }
        ],
        "top_candidates": [
            {
                "community_id": "555",
                "name": "AI Founders Club",
                "username": "ai_founders_club",
                "matched_queries": ["AI founders"],
            }
        ],
        "harvested_candidates": [
            {
                "community_id": "555",
                "name": "AI Founders Club",
                "username": "ai_founders_club",
                "matched_queries": ["AI founders"],
                "query_families": ["core"],
                "matched_query": "AI founders",
                "search_source": "fake_harvest",
                "search_mode": "harvest",
            }
        ],
        "refinement": {
            "triggered": False,
            "reason": "",
            "productive_query_families": ["core"],
            "attempted_queries": [],
            "unique_candidates_before": 1,
            "unique_candidates_after": 1,
            "added_unique_candidates": 0,
        },
    }

    enriched_payload, live_summary = agent._enrich_shortlist(
        shortlist_payload,
        brief_search_diagnostics=brief_search_diagnostics,
    )

    communities = enriched_payload["communities"]
    assert [community["name"] for community in communities] == [
        "EU AI Founders",
        "AI Founders Club",
        "Hidden Founder Guild",
    ]
    assert communities[0]["search_mode"] == "exact"
    assert communities[0]["match_kind"] == "exact_handle"
    assert communities[0]["evidence_summary"].startswith("Exact live match")
    assert communities[1]["search_mode"] == "harvest"
    assert communities[1]["validation_path"] == "harvested_pool_reuse"
    assert communities[1]["evidence_summary"].startswith("Broader harvested live match")
    assert communities[2]["verification_state"] == "training_knowledge_fallback"
    assert communities[2]["evidence_summary"] == "No live Telegram match yet; training-knowledge fallback only."
    assert enriched_payload["coverage_summary"].startswith("Coverage notes:")
    assert "broader harvest matching" in enriched_payload["coverage_summary"]
    assert "training-knowledge fallback" in enriched_payload["coverage_summary"]
    assert "Coverage notes:" in live_summary
    assert enriched_payload["search_diagnostics"]["validation"]["exact_validation_matches"] == 1
    assert enriched_payload["search_diagnostics"]["validation"]["harvest_pool_matches"] == 1


def test_account_manager_invalid_plan_does_not_persist_artifact_or_create_approval(tmp_path) -> None:
    session_store = JsonSessionStore(tmp_path / "sessions.json")
    approval_store = JsonApprovalStore(tmp_path / "approvals.json")
    session_manager = SessionManager(session_store)
    approval_manager = ApprovalManager(approval_store)
    session = session_manager.start_session("operator-invalid-plan")
    session_manager.create_workflow_artifact(
        session=session,
        kind=WorkflowArtifactKind.CAMPAIGN_BRIEF,
        title="Campaign brief",
        data={"objective": "Reach AI founders"},
    )
    session_manager.create_workflow_artifact(
        session=session,
        kind=WorkflowArtifactKind.COMMUNITY_SHORTLIST,
        title="Community shortlist",
        data={"communities": [{"name": "EU AI Founders", "handle": "@eu_ai_founders"}]},
    )
    session_manager.create_workflow_artifact(
        session=session,
        kind=WorkflowArtifactKind.STRATEGY_PLAYBOOK,
        title="Strategy playbook",
        data={
            "campaign_strategy_summary": "Start with value-first founder messaging.",
            "communities": [
                {
                    "name": "EU AI Founders",
                    "handle": "@eu_ai_founders",
                    "messaging_angle": "Peer-to-peer founder insight",
                    "message_format": "text",
                    "frequency": "once",
                    "timing": "weekday mornings",
                    "risk_notes": "Keep the tone educational.",
                }
            ],
        },
    )

    invalid_output = """The plan needs another pass before approval.

ACCOUNT_ASSIGNMENT_PLAN_JSON
```json
{
  "plan_summary": "Draft plan that still needs structure.",
  "assignments": []
}
```"""

    fake_content_block = MagicMock()
    fake_content_block.text = invalid_output
    fake_api_response = MagicMock()
    fake_api_response.content = [fake_content_block]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = fake_api_response

    with patch("anthropic.Anthropic", return_value=mock_client):
        agent = AccountManagerAgent(
            session_manager=session_manager,
            approval_manager=approval_manager,
            account_capability=StubAccountCapability(),
        )
        operator_text, artifact, approval = agent.run(session)

    assert "did not save this plan" in operator_text.lower()
    assert artifact is None
    assert approval is None
    assert session_manager.get_latest_artifact_of_kind(session, WorkflowArtifactKind.ACCOUNT_ASSIGNMENT_PLAN) is None
    assert approval_manager.get_pending_for_session(session.session_id) is None


def test_telegram_app_service_runs_full_specialist_workflow(tmp_path) -> None:
    session_store = JsonSessionStore(tmp_path / "sessions.json")
    approval_store = JsonApprovalStore(tmp_path / "approvals.json")
    runtime_monitor = JsonlRuntimeEventLogger(tmp_path / "monitoring" / "runtime_events.jsonl")
    campaigns_root = tmp_path / "campaigns"
    session_manager = SessionManager(session_store)
    approval_manager = ApprovalManager(approval_store)
    campaign_manager = CampaignManager(campaigns_root)
    work_item_manager = WorkItemManager(campaigns_root)
    schedule_manager = ScheduleManager(campaigns_root)

    discovery_output = f"""I found a strong initial shortlist for AI founder outreach in Europe.

Please approve this shortlist or tell me what to change before I move to strategy.

{DISCOVERY_JSON_MARKER}
```json
{{
  "summary": "Ranked three relevant AI founder communities.",
  "recommended_next_step": "Approve the shortlist to begin strategy work.",
  "communities": [
    {{
      "name": "EU AI Founders",
      "handle": "@eu_ai_founders",
      "type": "group",
      "topic": "AI startups",
      "language": "English",
      "geography": "Europe",
      "relevance_score": 92,
      "promo_tolerance": "medium",
      "moderation_risk": "low",
      "reason": "Highly aligned with early-stage AI founders in Europe.",
      "source_notes": ["Based on training knowledge."]
    }}
  ]
}}
```"""
    strategy_output = """Value-first founder positioning is the right first move here. Lead with operator insight, keep the CTA light, and save direct asks for higher-tolerance groups.

STRATEGY_PLAYBOOK_JSON
```json
{
  "campaign_strategy_summary": "Lead with insight-heavy founder messaging before stronger asks.",
  "communities": [
    {
      "name": "EU AI Founders",
      "handle": "@eu_ai_founders",
      "messaging_angle": "Peer-to-peer founder insight",
      "message_format": "text",
      "frequency": "once",
      "timing": "weekday mornings",
      "risk_notes": "Keep the tone educational."
    }
  ]
}
```"""
    account_plan_output = """I mapped the highest-signal community to a senior account first and kept the plan inside the pacing guardrails. The draft leaves room to expand once a live roster is available.

ACCOUNT_ASSIGNMENT_PLAN_JSON
```json
{
  "plan_summary": "Start with one senior account in the highest-fit community.",
  "assignments": [
    {
      "community_name": "EU AI Founders",
      "community_handle": "@eu_ai_founders",
      "assigned_account": "account_senior_1",
      "scheduled_posts": [
        {
          "day_offset": 0,
          "time_window": "09:00-11:00",
          "message_angle": "Peer-to-peer founder insight",
          "message_text": "Sharing one operator lesson that helped us find traction with AI founders in Europe this quarter."
        }
      ],
      "risk_level": "low",
      "notes": "Expand after validating community response."
    }
  ]
}
```"""

    def _fake_response(text: str) -> MagicMock:
        fake_content_block = MagicMock()
        fake_content_block.text = text
        fake_api_response = MagicMock()
        fake_api_response.content = [fake_content_block]
        return fake_api_response

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [
        _fake_response(discovery_output),
        _fake_response(strategy_output),
        _fake_response(account_plan_output),
    ]
    membership_capability = RecordingMembershipCapability()
    messaging_capability = RecordingMessagingCapability()

    with patch("anthropic.Anthropic", return_value=mock_client):
        orchestrator = PurposeBuiltOrchestrator(
            session_manager=session_manager,
            approval_manager=approval_manager,
            community_capability=StubCommunityCapability(),
            account_capability=StubAccountCapability(),
            membership_capability=membership_capability,
            messaging_capability=messaging_capability,
            work_item_manager=work_item_manager,
            schedule_manager=schedule_manager,
            monitor=runtime_monitor,
        )
        service = TelegramAppService(
            session_manager=session_manager,
            approval_manager=approval_manager,
            orchestrator=orchestrator,
            intake_coordinator=StructuredIntakeCoordinator(session_manager),
            campaign_manager=campaign_manager,
            monitor=runtime_monitor,
        )

        first_response = service.handle_update(
            TelegramUpdate(
                chat_id="chat-1",
                user_id="operator-6",
                text="Goal: Find Telegram communities for AI founders\nAudience: AI founders\nGeography: Europe",
            )
        )
        second_response = service.handle_update(
            TelegramUpdate(chat_id="chat-1", user_id="operator-6", text="approve")
        )
        third_response = service.handle_update(
            TelegramUpdate(chat_id="chat-1", user_id="operator-6", text="continue")
        )
        fourth_response = service.handle_update(
            TelegramUpdate(chat_id="chat-1", user_id="operator-6", text="approve")
        )

    assert "approve this shortlist" in first_response.messages[0].text.lower()
    assert "value-first founder positioning" in second_response.messages[0].text.lower()
    assert "pacing guardrails" in third_response.messages[0].text.lower()
    assert "approved in chat" in fourth_response.messages[0].text.lower()
    assert mock_client.messages.create.call_count == 3
    assert membership_capability.calls == []
    assert messaging_capability.calls == []

    active_session = session_manager.get_active_session("operator-6")
    assert active_session is not None
    assert active_session.campaign_id is not None

    artifacts = session_manager.list_workflow_artifacts(active_session)
    artifact_kinds = {artifact.kind for artifact in artifacts}
    assert WorkflowArtifactKind.CAMPAIGN_BRIEF in artifact_kinds
    assert WorkflowArtifactKind.COMMUNITY_SHORTLIST in artifact_kinds
    assert WorkflowArtifactKind.STRATEGY_PLAYBOOK in artifact_kinds
    assert WorkflowArtifactKind.ACCOUNT_ASSIGNMENT_PLAN in artifact_kinds
    assert WorkflowArtifactKind.EXECUTION_REPORT not in artifact_kinds

    snapshot = session_manager.get_workflow_snapshot(active_session)
    assert snapshot.stage is WorkflowStage.COMPLETE
    assert approval_manager.get_pending_for_session(active_session.session_id) is None

    work_items = work_item_manager.list_for_campaign(active_session.campaign_id)
    work_item_statuses = {item.work_type: item.status for item in work_items}
    assert work_item_statuses["discovery"] is WorkItemStatus.COMPLETED
    assert work_item_statuses["strategy"] is WorkItemStatus.COMPLETED
    assert work_item_statuses["account_planning"] is WorkItemStatus.COMPLETED

    event_lines = (tmp_path / "monitoring" / "runtime_events.jsonl").read_text(encoding="utf-8").strip().splitlines()
    events = [json.loads(line) for line in event_lines]
    components = {(event["component"], event["event_type"]) for event in events}
    trace_ids = {event["trace"].get("trace_id", "") for event in events}

    assert ("app_service", "turn_received") in components
    assert ("app_service", "workflow_stage_changed") in components
    assert ("discovery_agent", "llm_request") in components
    assert ("strategy_agent", "llm_response") in components
    assert ("account_manager_agent", "llm_response") in components
    assert "" not in trace_ids


def test_account_plan_review_completion_does_not_send_messages(tmp_path) -> None:
    session_store = JsonSessionStore(tmp_path / "sessions.json")
    approval_store = JsonApprovalStore(tmp_path / "approvals.json")
    session_manager = SessionManager(session_store)
    approval_manager = ApprovalManager(approval_store)

    account_plan_output = """The plan is conservative and keeps the first step low-risk.

ACCOUNT_ASSIGNMENT_PLAN_JSON
```json
{
  "plan_summary": "Start with one senior account and wait for a clearer draft before posting.",
  "assignments": [
    {
      "community_name": "EU AI Founders",
      "community_handle": "@eu_ai_founders",
      "assigned_account": "account_senior_1",
      "scheduled_posts": [
        {
          "day_offset": 0,
          "time_window": "09:00-11:00",
          "message_angle": "Peer-to-peer founder insight"
        }
      ],
      "risk_level": "low",
      "notes": "Do not post until copy is approved."
    }
  ]
}
```"""

    def _fake_response(text: str) -> MagicMock:
        fake_content_block = MagicMock()
        fake_content_block.text = text
        fake_api_response = MagicMock()
        fake_api_response.content = [fake_content_block]
        return fake_api_response

    mock_client = MagicMock()
    mock_client.messages.create.return_value = _fake_response(account_plan_output)

    membership_capability = RecordingMembershipCapability()
    messaging_capability = RecordingMessagingCapability()

    with patch("anthropic.Anthropic", return_value=mock_client):
        orchestrator = PurposeBuiltOrchestrator(
            session_manager=session_manager,
            approval_manager=approval_manager,
            account_capability=StubAccountCapability(),
            membership_capability=membership_capability,
            messaging_capability=messaging_capability,
        )
        service = TelegramAppService(
            session_manager=session_manager,
            approval_manager=approval_manager,
            orchestrator=orchestrator,
            intake_coordinator=StructuredIntakeCoordinator(session_manager),
        )

        session = session_manager.start_session("operator-8")
        session_manager.replace_workflow_snapshot(
            session,
            WorkflowSnapshot(
                stage=WorkflowStage.ACCOUNT_PLANNING,
                summary="Ready for account assignment planning.",
            ),
        )
        service.handle_update(
            TelegramUpdate(chat_id="chat-1", user_id="operator-8", text="continue")
        )
        response = service.handle_update(TelegramUpdate(chat_id="chat-1", user_id="operator-8", text="approve"))

    assert "approved in chat" in response.messages[0].text.lower()
    assert membership_capability.calls == []
    assert messaging_capability.calls == []


def test_account_plan_review_completion_does_not_create_execution_artifact(tmp_path) -> None:
    session_store = JsonSessionStore(tmp_path / "sessions.json")
    approval_store = JsonApprovalStore(tmp_path / "approvals.json")
    session_manager = SessionManager(session_store)
    approval_manager = ApprovalManager(approval_store)

    account_plan_output = """The plan is conservative and keeps the first step low-risk.

ACCOUNT_ASSIGNMENT_PLAN_JSON
```json
{
  "plan_summary": "Start with one senior account and save the first draft for later debugging.",
  "assignments": [
    {
      "community_name": "EU AI Founders",
      "community_handle": "@eu_ai_founders",
      "assigned_account": "account_senior_1",
      "scheduled_posts": [
        {
          "day_offset": 0,
          "time_window": "09:00-11:00",
          "message_angle": "Peer-to-peer founder insight",
          "message_text": "Sharing one operator lesson that helped us find traction with AI founders in Europe this quarter."
        }
      ],
      "risk_level": "low",
      "notes": "Do not send until the live-send switch is re-enabled."
    }
  ]
}
```"""

    def _fake_response(text: str) -> MagicMock:
        fake_content_block = MagicMock()
        fake_content_block.text = text
        fake_api_response = MagicMock()
        fake_api_response.content = [fake_content_block]
        return fake_api_response

    mock_client = MagicMock()
    mock_client.messages.create.return_value = _fake_response(account_plan_output)

    membership_capability = RecordingMembershipCapability()
    messaging_capability = RecordingMessagingCapability()

    with patch("anthropic.Anthropic", return_value=mock_client):
        orchestrator = PurposeBuiltOrchestrator(
            session_manager=session_manager,
            approval_manager=approval_manager,
            account_capability=StubAccountCapability(),
            membership_capability=membership_capability,
            messaging_capability=messaging_capability,
            allow_live_sends=False,
        )
        service = TelegramAppService(
            session_manager=session_manager,
            approval_manager=approval_manager,
            orchestrator=orchestrator,
            intake_coordinator=StructuredIntakeCoordinator(session_manager),
        )

        session = session_manager.start_session("operator-9")
        session_manager.replace_workflow_snapshot(
            session,
            WorkflowSnapshot(
                stage=WorkflowStage.ACCOUNT_PLANNING,
                summary="Ready for account assignment planning.",
            ),
        )
        service.handle_update(
            TelegramUpdate(chat_id="chat-1", user_id="operator-9", text="continue")
        )
        response = service.handle_update(
            TelegramUpdate(chat_id="chat-1", user_id="operator-9", text="approve")
        )

    assert "approved in chat" in response.messages[0].text.lower()
    assert membership_capability.calls == []
    assert messaging_capability.calls == []

    active_session = session_manager.get_active_session("operator-9")
    assert active_session is not None

    execution_report = session_manager.get_latest_artifact_of_kind(
        active_session,
        WorkflowArtifactKind.EXECUTION_REPORT,
    )
    assert execution_report is None


def test_telegram_app_service_records_one_assistant_reply_per_turn(tmp_path) -> None:
    session_store = JsonSessionStore(tmp_path / "sessions.json")
    approval_store = JsonApprovalStore(tmp_path / "approvals.json")
    session_manager = SessionManager(session_store)
    approval_manager = ApprovalManager(approval_store)

    discovery_output = f"""I found a strong initial shortlist for AI founder outreach in Europe.

Please approve this shortlist or tell me what to change before I move to strategy.

{DISCOVERY_JSON_MARKER}
```json
{{
  "summary": "Ranked one relevant AI founder community.",
  "recommended_next_step": "Approve the shortlist to begin strategy work.",
  "communities": [
    {{
      "name": "EU AI Founders",
      "handle": "@eu_ai_founders",
      "type": "group",
      "topic": "AI startups",
      "language": "English",
      "geography": "Europe",
      "relevance_score": 92,
      "promo_tolerance": "medium",
      "moderation_risk": "low",
      "reason": "Highly aligned with early-stage AI founders in Europe.",
      "source_notes": ["Based on training knowledge."]
    }}
  ]
}}
```"""

    fake_content_block = MagicMock()
    fake_content_block.text = discovery_output
    fake_api_response = MagicMock()
    fake_api_response.content = [fake_content_block]

    mock_client = MagicMock()
    mock_client.messages.create.return_value = fake_api_response

    with patch("anthropic.Anthropic", return_value=mock_client):
        orchestrator = PurposeBuiltOrchestrator(
            session_manager=session_manager,
            approval_manager=approval_manager,
            community_capability=StubCommunityCapability(),
            account_capability=StubAccountCapability(),
            membership_capability=StubMembershipCapability(),
            messaging_capability=StubMessagingCapability(),
        )
        service = TelegramAppService(
            session_manager=session_manager,
            approval_manager=approval_manager,
            orchestrator=orchestrator,
            intake_coordinator=StructuredIntakeCoordinator(session_manager),
        )
        service.handle_update(
            TelegramUpdate(
                chat_id="chat-1",
                user_id="operator-7",
                text="Goal: Find Telegram communities for AI founders\nAudience: AI founders\nGeography: Europe",
            )
        )

    active_session = session_manager.get_active_session("operator-7")
    assert active_session is not None
    history = active_session.workflow_state["message_history"]

    assert len(history) == 2
    assert history[0]["role"] == "operator"
    assert history[1]["role"] == "assistant"
