from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock, patch

from agents.discovery.agent import DiscoveryAgent
from agents.strategy.agent import StrategyAgent
from telegram_app.agent_runtime import AgentRuntimeBroker
from telegram_app.approvals import ApprovalManager, JsonApprovalStore
from telegram_app.capabilities import (
    CapabilityResult,
    StubAccountCapability,
    StubCommunityCapability,
    StubMessagingCapability,
)
from telegram_app.llm import TelegramCapabilityToolbox
from telegram_app.orchestrator import PurposeBuiltOrchestrator
from telegram_app.models import WorkflowSnapshot, WorkflowStage
from telegram_app.sessions import JsonSessionStore, SessionManager
from telegram_app.transport import TelegramUpdate


@dataclass
class FakeTextBlock:
    text: str
    type: str = "text"


@dataclass
class FakeToolUseBlock:
    id: str
    name: str
    input: dict[str, object]
    type: str = "tool_use"


@dataclass
class FakeApiResponse:
    content: list[object]


class RecordingAnthropicClient:
    def __init__(self, responses: list[FakeApiResponse]) -> None:
        self._responses = list(responses)
        self.requests: list[dict[str, object]] = []
        self.messages = self

    def create(self, **kwargs):  # noqa: ANN003
        self.requests.append(kwargs)
        if not self._responses:
            raise AssertionError("No fake Anthropic responses remaining.")
        return self._responses.pop(0)


class SimpleAccountCapability:
    def list_accounts(self) -> CapabilityResult:
        return CapabilityResult(
            success=True,
            data={
                "accounts": [
                    {
                        "account_id": "reader-1",
                        "health": "active",
                        "tier": "senior",
                    }
                ]
            },
            audit={"implementation": "simple_account_capability"},
        )

    def get_account(self, account_id: str) -> CapabilityResult:
        return CapabilityResult(
            success=True,
            data={"account": {"account_id": account_id, "health": "active"}},
            audit={"implementation": "simple_account_capability"},
        )


class SimpleMembershipCapability:
    def get_membership(self, account_id: str, community_id: str) -> CapabilityResult:
        return CapabilityResult(
            success=True,
            data={"account_id": account_id, "community_id": community_id, "is_member": False},
            audit={"implementation": "simple_membership_capability"},
        )

    def join(self, account_id: str, community_id: str) -> CapabilityResult:
        return CapabilityResult(
            success=True,
            data={"account_id": account_id, "community_id": community_id, "outcome_code": "success"},
            audit={"implementation": "simple_membership_capability"},
        )


def test_telegram_capability_toolbox_executes_tool_roundtrip() -> None:
    toolbox = TelegramCapabilityToolbox(account_capability=SimpleAccountCapability())
    client = RecordingAnthropicClient(
        [
            FakeApiResponse([FakeToolUseBlock(id="tool-1", name="telegram_list_accounts", input={})]),
            FakeApiResponse([FakeTextBlock("Used live account data.")]),
        ]
    )

    result = toolbox.run_completion(
        client=client,
        model="claude-sonnet-4-6",
        max_tokens=512,
        system=[{"type": "text", "text": "system"}],
        messages=[{"role": "user", "content": "Show me the roster."}],
    )

    assert result.final_output == "Used live account data."
    assert result.tool_call_count == 1
    assert result.tool_names == ["telegram_list_accounts"]
    assert len(client.requests) == 2

    follow_up_messages = client.requests[1]["messages"]
    assert follow_up_messages[-1]["role"] == "user"
    tool_result_payload = follow_up_messages[-1]["content"][0]["content"]
    assert '"account_id": "reader-1"' in tool_result_payload


def test_agent_runtime_broker_marks_stub_runtime_as_not_live_ready() -> None:
    broker = AgentRuntimeBroker(
        account_capability=StubAccountCapability(),
        community_capability=StubCommunityCapability(),
        messaging_capability=StubMessagingCapability(),
    )

    capability_summary = broker.build_telegram_capability_summary()
    roster_summary = broker.build_account_roster_summary()

    assert capability_summary["live_readiness"] == "stubbed"
    assert capability_summary["operator_action_required"] is True
    assert roster_summary["source"] == "stub"
    assert roster_summary["live_ready"] is False


def test_orchestrator_appends_runtime_notice_when_discovery_runs_in_stub_mode(tmp_path) -> None:
    session_manager = SessionManager(JsonSessionStore(tmp_path / "sessions.json"))
    approval_manager = ApprovalManager(JsonApprovalStore(tmp_path / "approvals.json"))
    session = session_manager.start_session("operator-1")
    session_manager.replace_workflow_snapshot(
        session,
        WorkflowSnapshot(stage=WorkflowStage.DISCOVERY, summary="Ready for discovery."),
    )

    discovery_output = """I found an initial shortlist.

DISCOVERY_SHORTLIST_JSON
```json
{
  "summary": "One candidate found.",
  "recommended_next_step": "Review the shortlist.",
  "communities": [
    {
      "name": "EU AI Founders",
      "handle": "@eu_ai_founders",
      "type": "group",
      "topic": "AI founders",
      "language": "en",
      "geography": "Europe",
      "relevance_score": 8,
      "promo_tolerance": "medium",
      "moderation_risk": "low",
      "reason": "Aligned with the campaign brief.",
      "verification_state": "training_knowledge_fallback",
      "source_notes": ["Fallback only."]
    }
  ]
}
```

COMPILED_PROPOSALS_JSON
```json
[]
```"""

    mock_client = MagicMock()
    mock_client.messages.create.return_value = FakeApiResponse([FakeTextBlock(discovery_output)])

    with patch("anthropic.Anthropic", return_value=mock_client):
        orchestrator = PurposeBuiltOrchestrator(
            session_manager=session_manager,
            approval_manager=approval_manager,
            account_capability=StubAccountCapability(),
            community_capability=StubCommunityCapability(),
            messaging_capability=StubMessagingCapability(),
        )
        response = orchestrator.handle_turn(
            session,
            TelegramUpdate(chat_id="chat-1", user_id="operator-1", text="continue"),
        )

    assert "Runtime notice:" in response.messages[0].text
    assert "stub mode" in response.messages[0].text
    assert "/addaccount" in response.messages[0].text


def test_specialist_agents_build_full_read_side_toolbox_when_live_capabilities_exist() -> None:
    with patch("anthropic.Anthropic", return_value=MagicMock()):
        discovery_agent = DiscoveryAgent(
            account_capability=SimpleAccountCapability(),
            community_capability=StubCommunityCapability(),
            membership_capability=SimpleMembershipCapability(),
            messaging_capability=StubMessagingCapability(),
        )
        strategy_agent = StrategyAgent(
            account_capability=SimpleAccountCapability(),
            community_capability=StubCommunityCapability(),
            membership_capability=SimpleMembershipCapability(),
            messaging_capability=StubMessagingCapability(),
        )

    discovery_tool_names = {tool["name"] for tool in discovery_agent._toolbox.build_tools()}
    strategy_tool_names = {tool["name"] for tool in strategy_agent._toolbox.build_tools()}
    expected_tools = {
        "telegram_list_accounts",
        "telegram_get_account",
        "telegram_search_communities",
        "telegram_get_community_profile",
        "telegram_get_membership",
        "telegram_read_messages",
        "telegram_get_dialog_history",
        "telegram_list_recent_dialogs",
    }

    assert expected_tools.issubset(discovery_tool_names)
    assert expected_tools.issubset(strategy_tool_names)
