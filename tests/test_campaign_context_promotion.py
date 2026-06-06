from pathlib import Path
from unittest.mock import MagicMock, patch

from telegram_app.campaign_context import get_campaign_context_artifact
from telegram_app.campaigns import CampaignManager
from telegram_app.intake import StructuredIntakeCoordinator
from telegram_app.models import WorkflowArtifactKind, WorkflowSnapshot, WorkflowStage
from telegram_app.orchestrator import PurposeBuiltOrchestrator
from telegram_app.orchestrator.context_builder import build_runtime_context
from telegram_app.sessions import JsonSessionStore, SessionManager
from telegram_app.transport import TelegramUpdate
from telegram_app.work_items import WorkItemManager


def _fake_response(text: str) -> MagicMock:
    fake_content_block = MagicMock()
    fake_content_block.text = text
    fake_api_response = MagicMock()
    fake_api_response.content = [fake_content_block]
    return fake_api_response


def test_intake_promotes_campaign_context_into_structured_state_and_memory(tmp_path) -> None:
    session_manager = SessionManager(JsonSessionStore(tmp_path / "sessions.json"))
    campaign_manager = CampaignManager(tmp_path / "campaigns")
    intake = StructuredIntakeCoordinator(session_manager)

    session = session_manager.start_session("operator-context")
    campaign = campaign_manager.ensure_campaign("operator-context")
    session_manager.attach_campaign(
        session,
        campaign_id=campaign.campaign_id,
        campaign_workspace_path=campaign.workspace_path,
        canonical_memory_files=campaign.canonical_files,
        agent_memory_files=campaign.agent_memory_files,
    )

    intake.ingest_operator_turn(
        session,
        (
            "Goal: Find Telegram communities for AI founders\n"
            "Audience: AI founders\n"
            "Tone: educational, founder-to-founder, not hypey\n"
            "Preferences: keep the replies concise\n"
            "Constraints: no cold DMs; senior accounts only for high-risk communities\n"
            "Question: Should we stay Europe-only?"
        ),
        source_message_id="ctx-1",
    )
    campaign_manager.sync_session_memory(session)

    campaign_context = get_campaign_context_artifact(session)
    assert campaign_context is not None
    assert campaign_context.kind is WorkflowArtifactKind.CAMPAIGN_CONTEXT
    assert campaign_context.data["operator_preferences"] == ["keep the replies concise"]
    assert campaign_context.data["voice_profile"]["preferred_traits"] == [
        "educational",
        "founder-to-founder",
    ]
    assert campaign_context.data["voice_profile"]["avoid_traits"] == ["not hypey"]
    assert campaign_context.data["execution_constraints"] == [
        "no cold DMs",
        "senior accounts only for high-risk communities",
    ]
    assert campaign_context.data["open_ambiguities"] == ["Should we stay Europe-only?"]

    context = build_runtime_context(session, pending_approval=None)
    assert "campaign_context_data" in context
    assert "senior accounts only for high-risk communities" in context
    assert "founder-to-founder" in context

    operator_intent_text = (Path(campaign.workspace_path) / "operator-intent.md").read_text(encoding="utf-8")
    assert "## Operator preferences" in operator_intent_text
    assert "## Preferred voice traits" in operator_intent_text
    assert "## Voice traits to avoid" in operator_intent_text
    assert "## Execution constraints" in operator_intent_text
    assert "## Open ambiguities" in operator_intent_text


def test_revision_promotion_survives_across_turns_and_reaches_follow_on_agent(tmp_path) -> None:
    session_manager = SessionManager(JsonSessionStore(tmp_path / "sessions.json"))
    campaign_manager = CampaignManager(tmp_path / "campaigns")
    work_item_manager = WorkItemManager(tmp_path / "campaigns")

    session = session_manager.start_session("operator-revision")
    campaign = campaign_manager.ensure_campaign("operator-revision")
    session_manager.attach_campaign(
        session,
        campaign_id=campaign.campaign_id,
        campaign_workspace_path=campaign.workspace_path,
        canonical_memory_files=campaign.canonical_files,
        agent_memory_files=campaign.agent_memory_files,
    )
    session_manager.create_workflow_artifact(
        session=session,
        kind=WorkflowArtifactKind.CAMPAIGN_BRIEF,
        title="Campaign brief",
        summary="AI founders campaign brief.",
        data={
            "objective": "Find Telegram communities for AI founders",
            "target_audience": "AI founders",
            "offer": "Founder support offer",
            "geography": "Europe",
            "language": "English",
            "constraints": ["Stay value-first."],
            "success_criteria": [],
            "seed_target_groups": [],
            "notes": [],
            "source_messages": [],
        },
    )
    session_manager.create_workflow_artifact(
        session=session,
        kind=WorkflowArtifactKind.COMMUNITY_SHORTLIST,
        title="Community shortlist",
        summary="Initial shortlist ready.",
        data={
            "summary": "One strong founder community.",
            "recommended_next_step": "Move to strategy.",
            "verification_summary": "One live-confirmed community.",
            "coverage_summary": "Coverage is narrow but strong.",
            "communities": [
                {
                    "name": "EU AI Founders",
                    "handle": "@eu_ai_founders",
                    "type": "group",
                    "language": "English",
                    "geography": "Europe",
                    "relevance_score": 9,
                    "promo_tolerance": "medium",
                    "moderation_risk": "low",
                    "reason": "Aligned with AI founders in Europe.",
                    "verification_state": "live_confirmed",
                    "evidence_summary": "Exact live match.",
                    "recent_tone_summary": "Recent posts look like short conversational updates.",
                    "source_notes": ["Live Telegram validation."],
                }
            ],
        },
    )
    session_manager.create_workflow_artifact(
        session=session,
        kind=WorkflowArtifactKind.STRATEGY_PLAYBOOK,
        title="Strategy playbook",
        summary="Original strategy draft.",
        data={
            "campaign_strategy_summary": "Lead with practical founder lessons.",
            "communities": [
                {
                    "name": "EU AI Founders",
                    "handle": "@eu_ai_founders",
                    "messaging_angle": "Practical founder lessons",
                    "message_format": "text",
                    "frequency": "weekly",
                    "timing": "weekday mornings",
                    "risk_notes": "Keep the tone educational.",
                }
            ],
        },
    )
    session_manager.replace_workflow_snapshot(
        session,
        WorkflowSnapshot(
            stage=WorkflowStage.STRATEGY,
            summary="Strategy playbook ready for operator review.",
        ),
    )

    strategy_output = """Refined the founder positioning and kept the tone value-first.

STRATEGY_PLAYBOOK_JSON
```json
{
  "campaign_strategy_summary": "Lead with founder-specific lessons, keep the tone educational, and avoid hypey framing.",
  "communities": [
    {
      "name": "EU AI Founders",
      "handle": "@eu_ai_founders",
      "messaging_angle": "Tighter founder-to-founder positioning",
      "message_format": "text",
      "frequency": "weekly",
      "timing": "weekday mornings",
      "risk_notes": "Keep the tone educational and avoid hype."
    }
  ]
}
```"""
    account_output = """Built a conservative account plan around the approved tone guidance.

ACCOUNT_ASSIGNMENT_PLAN_JSON
```json
{
  "plan_summary": "Use one senior account first and keep the messaging educational.",
  "assignments": [
    {
      "community_name": "EU AI Founders",
      "community_handle": "@eu_ai_founders",
      "assigned_account": "account_senior_1",
      "scheduled_posts": [
        {
          "day_offset": 0,
          "time_window": "09:00-11:00",
          "message_angle": "Founder-to-founder lesson",
          "message_text": "Sharing one practical lesson that helped us get traction with AI founders in Europe."
        }
      ],
      "risk_level": "low",
      "notes": "Keep the tone educational and avoid hype."
    }
  ]
}
```"""

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [
        _fake_response(strategy_output),
        _fake_response(account_output),
    ]

    with (
        patch("anthropic.Anthropic", return_value=mock_client),
        patch("agents.strategy.agent._load_prompt", return_value="strategy prompt"),
        patch("agents.account_manager.agent._load_prompt", return_value="account prompt"),
    ):
        orchestrator = PurposeBuiltOrchestrator(
            session_manager=session_manager,
            work_item_manager=work_item_manager,
        )

        revision_message = "Tighten the founder angle and keep the tone educational, not hypey."
        session_manager.record_operator_message(session, revision_message)
        orchestrator.handle_turn(
            session,
            TelegramUpdate(
                chat_id="chat-1",
                user_id="operator-revision",
                text=revision_message,
                message_id="rev-1",
            ),
        )

        reloaded_session = session_manager.get_active_session("operator-revision")
        assert reloaded_session is not None
        campaign_context = get_campaign_context_artifact(reloaded_session)
        assert campaign_context is not None
        prompt_safe_context = build_runtime_context(reloaded_session, pending_approval=None)
        assert "campaign_context_data" in prompt_safe_context
        assert "active_revisions" in prompt_safe_context
        assert "Tighten the founder angle" in prompt_safe_context
        assert "not hypey" in prompt_safe_context

        session_manager.record_operator_message(reloaded_session, "continue")
        orchestrator.handle_turn(
            reloaded_session,
            TelegramUpdate(
                chat_id="chat-1",
                user_id="operator-revision",
                text="continue",
                message_id="rev-2",
            ),
        )

    assert mock_client.messages.create.call_count == 2

    first_system_prompt = "\n".join(block["text"] for block in mock_client.messages.create.call_args_list[0].kwargs["system"])
    second_system_prompt = "\n".join(block["text"] for block in mock_client.messages.create.call_args_list[1].kwargs["system"])
    assert "campaign_context_data" in first_system_prompt
    assert "Tighten the founder angle" in first_system_prompt
    assert "not hypey" in first_system_prompt
    assert "campaign_context_data" in second_system_prompt
    assert "accepted_revisions" in second_system_prompt
    assert "strategy: Tighten the founder angle" in second_system_prompt
    assert "not hypey" in second_system_prompt

    final_session = session_manager.get_active_session("operator-revision")
    assert final_session is not None
    final_context = get_campaign_context_artifact(final_session)
    assert final_context is not None
    revision_threads = final_context.data["revision_threads"]
    assert revision_threads[-1]["status"] == "accepted"
    assert "strategy: Tighten the founder angle" in final_context.data["persistent_decisions"]
