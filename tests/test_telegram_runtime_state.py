import json
from unittest.mock import MagicMock, patch

from agents.account_manager.agent import AccountManagerAgent
from agents.strategy.agent import StrategyAgent
from telegram_app.app_service import TelegramAppService
from telegram_app.capabilities import (
    StubAccountCapability,
    StubCommunityCapability,
    StubMembershipCapability,
    StubMessagingCapability,
)
from telegram_app.discovery import DISCOVERY_JSON_MARKER
from telegram_app.intake import StructuredIntakeCoordinator, get_campaign_brief_artifact
from telegram_app.monitoring import JsonlRuntimeEventLogger
from telegram_app.approvals import ApprovalManager, JsonApprovalStore
from telegram_app.orchestrator import PurposeBuiltOrchestrator
from telegram_app.orchestrator.context_builder import build_runtime_context
from telegram_app.orchestrator.orchestrator import _build_messages
from telegram_app.models import (
    ApprovalStatus,
    WorkflowArtifactKind,
    WorkflowSnapshot,
    WorkflowStage,
)
from telegram_app.sessions import JsonSessionStore, SessionManager
from telegram_app.transport import TelegramUpdate


class FakeDiscoveryCommunityCapability:
    def search(self, query: str):  # noqa: ANN001
        return MagicMock(
            success=True,
            data={
                "results": [
                    {
                        "community_id": "111",
                        "name": "EU AI Founders",
                        "username": "eu_ai_founders",
                    }
                ]
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
    assert len(loaded_artifacts) == 1
    assert loaded_artifacts[0].artifact_id == artifact.artifact_id
    assert loaded_artifacts[0].kind is WorkflowArtifactKind.CAMPAIGN_BRIEF
    assert loaded_artifacts[0].data["objective"] == "Drive founder conversations"


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

    intake.ingest_operator_turn(session, "Find Telegram communities for fintech founders in MENA")
    intake.ingest_operator_turn(
        session,
        "Constraints: avoid communities that ban promotion; prioritize English-speaking groups",
    )

    context = build_runtime_context(session, pending_approval=None, discovery_mode=True)

    assert "campaign_brief_data" in context
    assert "source_messages" not in context
    assert "constraints" in context


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


def test_discovery_stage_persists_shortlist_and_marks_pending_approval(tmp_path) -> None:
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
    assert shortlist_artifacts[0].data["communities"][0]["recent_message_samples"]

    pending_approval = approval_manager.get_pending_for_session(session.session_id)
    assert pending_approval is not None
    assert pending_approval.category == "community_shortlist"

    snapshot = session_manager.get_workflow_snapshot(reloaded_session)
    assert snapshot.stage is WorkflowStage.WAITING_FOR_APPROVAL
    assert snapshot.data["pending_approval_id"] == pending_approval.approval_id


def test_strategy_stage_requires_explicit_approval_before_account_planning(tmp_path) -> None:
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

    assert "approve this strategy" in response.messages[0].text.lower()
    pending_approval = approval_manager.get_pending_for_session(session.session_id)
    assert pending_approval is not None
    assert pending_approval.category == "strategy_playbook"
    snapshot = session_manager.get_workflow_snapshot(session)
    assert snapshot.stage is WorkflowStage.WAITING_FOR_APPROVAL
    assert (
        session_manager.get_latest_artifact_of_kind(session, WorkflowArtifactKind.ACCOUNT_ASSIGNMENT_PLAN) is None
    )


def test_strategy_checkpoint_blocks_ambiguous_follow_up(tmp_path) -> None:
    session_store = JsonSessionStore(tmp_path / "sessions.json")
    approval_store = JsonApprovalStore(tmp_path / "approvals.json")
    session_manager = SessionManager(session_store)
    approval_manager = ApprovalManager(approval_store)
    session = session_manager.start_session("operator-strategy-ambiguous")
    session_manager.replace_workflow_snapshot(
        session,
        WorkflowSnapshot(
            stage=WorkflowStage.WAITING_FOR_APPROVAL,
            summary="Waiting at the strategy checkpoint.",
            data={"pending_approval_id": "ap-1"},
        ),
    )
    pending_approval = approval_manager.create_pending(
        session_id=session.session_id,
        category="strategy_playbook",
        prompt="Approve this strategy to generate the account plan, or tell me what to change.",
        context={"artifact_id": "strategy-1"},
    )
    session.pending_approval_id = pending_approval.approval_id

    mock_client = MagicMock()

    with patch("anthropic.Anthropic", return_value=mock_client):
        orchestrator = PurposeBuiltOrchestrator(
            session_manager=session_manager,
            approval_manager=approval_manager,
        )
        response = orchestrator.handle_turn(
            session=session,
            update=TelegramUpdate(
                chat_id="chat-strategy",
                user_id="operator-strategy-ambiguous",
                text="what's next?",
            ),
            pending_approval=pending_approval,
        )

    assert "holding at the strategy checkpoint" in response.messages[0].text.lower()
    assert mock_client.messages.create.call_count == 0
    assert approval_manager.get_pending_for_session(session.session_id) is not None


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

    assert "did not save or request approval" in operator_text.lower()
    assert artifact is None
    assert approval is None
    assert session_manager.get_latest_artifact_of_kind(session, WorkflowArtifactKind.ACCOUNT_ASSIGNMENT_PLAN) is None
    assert approval_manager.get_pending_for_session(session.session_id) is None


def test_telegram_app_service_runs_full_specialist_workflow(tmp_path) -> None:
    session_store = JsonSessionStore(tmp_path / "sessions.json")
    approval_store = JsonApprovalStore(tmp_path / "approvals.json")
    runtime_monitor = JsonlRuntimeEventLogger(tmp_path / "monitoring" / "runtime_events.jsonl")
    session_manager = SessionManager(session_store)
    approval_manager = ApprovalManager(approval_store)

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
            monitor=runtime_monitor,
        )
        service = TelegramAppService(
            session_manager=session_manager,
            approval_manager=approval_manager,
            orchestrator=orchestrator,
            intake_coordinator=StructuredIntakeCoordinator(session_manager),
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
    assert "execution finished for the approved account plan" in fourth_response.messages[0].text.lower()
    assert mock_client.messages.create.call_count == 3
    assert membership_capability.calls == [("account_senior_1", "@eu_ai_founders")]
    assert len(messaging_capability.calls) == 1
    assert messaging_capability.calls[0][0] == "account_senior_1"
    assert messaging_capability.calls[0][1] == "@eu_ai_founders"
    assert "traction with ai founders" in messaging_capability.calls[0][2].lower()

    active_session = session_manager.get_active_session("operator-6")
    assert active_session is not None

    artifacts = session_manager.list_workflow_artifacts(active_session)
    artifact_kinds = {artifact.kind for artifact in artifacts}
    assert WorkflowArtifactKind.CAMPAIGN_BRIEF in artifact_kinds
    assert WorkflowArtifactKind.COMMUNITY_SHORTLIST in artifact_kinds
    assert WorkflowArtifactKind.STRATEGY_PLAYBOOK in artifact_kinds
    assert WorkflowArtifactKind.ACCOUNT_ASSIGNMENT_PLAN in artifact_kinds
    assert WorkflowArtifactKind.EXECUTION_REPORT in artifact_kinds

    snapshot = session_manager.get_workflow_snapshot(active_session)
    assert snapshot.stage is WorkflowStage.COMPLETE
    assert approval_manager.get_pending_for_session(active_session.session_id) is None

    event_lines = (tmp_path / "monitoring" / "runtime_events.jsonl").read_text(encoding="utf-8").strip().splitlines()
    events = [json.loads(line) for line in event_lines]
    components = {(event["component"], event["event_type"]) for event in events}
    trace_ids = {event["trace"].get("trace_id", "") for event in events}

    assert ("app_service", "turn_received") in components
    assert ("app_service", "workflow_stage_changed") in components
    assert ("orchestrator", "route_selected") in components
    assert ("discovery_agent", "llm_request") in components
    assert ("strategy_agent", "llm_response") in components
    assert ("account_manager_agent", "llm_response") in components
    assert ("execution_service", "execution_completed") in components
    assert ("execution_service", "assignment_executed") in components
    assert "" not in trace_ids


def test_account_plan_approval_skips_send_when_message_text_is_missing(tmp_path) -> None:
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
        response = service.handle_update(
            TelegramUpdate(chat_id="chat-1", user_id="operator-8", text="approve")
        )

    assert "send skips: 1" in response.messages[0].text.lower()
    assert membership_capability.calls == [("account_senior_1", "@eu_ai_founders")]
    assert messaging_capability.calls == []


def test_account_plan_approval_saves_drafts_when_live_sends_are_disabled(tmp_path) -> None:
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

    assert "drafts saved for debugging instead of sending: 1" in response.messages[0].text.lower()
    assert membership_capability.calls == [("account_senior_1", "@eu_ai_founders")]
    assert messaging_capability.calls == []

    active_session = session_manager.get_active_session("operator-9")
    assert active_session is not None

    execution_report = session_manager.get_latest_artifact_of_kind(
        active_session,
        WorkflowArtifactKind.EXECUTION_REPORT,
    )
    assert execution_report is not None
    assert execution_report.data["delivery_mode"] == "draft_only"
    assert execution_report.data["totals"]["send_saved_for_debugging"] == 1
    saved_send = execution_report.data["assignments"][0]["sends"][0]
    assert saved_send["status"] == "saved_for_debugging"
    assert "traction with ai founders" in saved_send["message_text"].lower()


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
