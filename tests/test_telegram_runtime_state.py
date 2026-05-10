from unittest.mock import MagicMock, patch

from telegram_app.discovery import DISCOVERY_JSON_MARKER
from telegram_app.intake import StructuredIntakeCoordinator, get_campaign_brief_artifact
from telegram_app.approvals import ApprovalManager, JsonApprovalStore
from telegram_app.orchestrator import PurposeBuiltOrchestrator
from telegram_app.models import (
    ApprovalStatus,
    WorkflowArtifactKind,
    WorkflowSnapshot,
    WorkflowStage,
)
from telegram_app.sessions import JsonSessionStore, SessionManager
from telegram_app.transport import TelegramUpdate


def test_json_session_store_persists_active_session_state(tmp_path) -> None:
    store = JsonSessionStore(tmp_path / "sessions.json")
    manager = SessionManager(store)

    session = manager.start_session("operator-1")
    manager.record_operator_message(session, "Find Telegram groups for AI founders.")

    reloaded_store = JsonSessionStore(tmp_path / "sessions.json")
    loaded_session = reloaded_store.get_active_for_operator("operator-1")

    assert loaded_session is not None
    assert loaded_session.session_id == session.session_id
    assert loaded_session.latest_operator_message == "Find Telegram groups for AI founders."
    assert loaded_session.workflow_state["message_history"][-1]["role"] == "operator"


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
        )
        response = orchestrator.handle_turn(
            session=session,
            update=TelegramUpdate(chat_id="chat-1", user_id="operator-5", text="continue"),
        )

    assert DISCOVERY_JSON_MARKER not in response.messages[0].text
    assert "approve this shortlist" in response.messages[0].text.lower()

    reloaded_session = JsonSessionStore(tmp_path / "sessions.json").get(session.session_id)
    assert reloaded_session is not None
    shortlist_artifacts = [
        artifact
        for artifact in session_manager.list_workflow_artifacts(reloaded_session)
        if artifact.kind is WorkflowArtifactKind.COMMUNITY_SHORTLIST
    ]
    assert len(shortlist_artifacts) == 1
    assert shortlist_artifacts[0].data["communities"][0]["name"] == "EU AI Founders"

    pending_approval = approval_manager.get_pending_for_session(session.session_id)
    assert pending_approval is not None
    assert pending_approval.category == "community_shortlist"

    snapshot = session_manager.get_workflow_snapshot(reloaded_session)
    assert snapshot.stage is WorkflowStage.WAITING_FOR_APPROVAL
    assert snapshot.data["pending_approval_id"] == pending_approval.approval_id
