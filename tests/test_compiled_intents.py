from unittest.mock import MagicMock, patch

from telegram_app.approvals import ApprovalManager, JsonApprovalStore
from telegram_app.campaign_memory.operational_notes import NEXT_ACTIONS_DESTINATION
from telegram_app.campaigns import CampaignManager
from telegram_app.compiled_intents import (
    CompiledIntentApplicator,
    CompiledIntentSafetyClass,
    CompiledIntentStatus,
    CompiledIntentStore,
    build_compiled_intent,
    compile_output_proposals,
    compile_conversation_belief_update,
    compile_prepared_execution_invalidation,
    compile_review_request,
    validate_compiled_intent,
)
from telegram_app.external_conversations import (
    ConversationBeliefState,
    ConsentPosture,
    ExternalConversationManager,
    ExternalConversationRecord,
    ExternalConversationStatus,
    ThreadOrigin,
)
from telegram_app.models import WorkflowArtifactKind, WorkflowSnapshot, WorkflowStage, WorkItemPriority, WorkItemStatus
from telegram_app.orchestrator import PurposeBuiltOrchestrator
from telegram_app.prepared_execution import PreparedExecutionManager, PreparedExecutionService
from telegram_app.sessions import JsonSessionStore, SessionManager
from telegram_app.live_execution import LiveActionStatus, LiveActionType, LiveExecutionManager, LiveExecutionService
from telegram_app.scheduling import ScheduleManager
from telegram_app.transport import TelegramUpdate
from telegram_app.workflow_validation import parse_output_proposal_list
from telegram_app.work_items import WorkItemManager


def test_compiled_intent_store_persists_lifecycle_fields(tmp_path) -> None:
    store = CompiledIntentStore(tmp_path / "campaigns")
    intent = build_compiled_intent(
        campaign_id="cmp-lifecycle",
        kind="memory.note",
        summary="Persist a next-actions note.",
        payload={"destination": NEXT_ACTIONS_DESTINATION, "line": "Review the pricing proof point."},
        source_role="orchestrator",
        safety_class=CompiledIntentSafetyClass.STATE_MUTATION,
        grounding_refs=["session:sess-1"],
        confidence=0.82,
    )

    assert validate_compiled_intent(intent) is None
    store.save(intent)
    intent.mark_accepted()
    store.save(intent)
    intent.mark_applied("Saved a campaign memory note to `next_actions`.")
    store.save(intent)

    reloaded = store.get("cmp-lifecycle", intent.intent_id)
    assert reloaded is not None
    assert reloaded.status is CompiledIntentStatus.APPLIED
    assert reloaded.accepted_at is not None
    assert reloaded.applied_at is not None
    assert reloaded.application_result == "Saved a campaign memory note to `next_actions`."


def test_compile_output_proposals_supports_shared_prompt_contract() -> None:
    compiled = compile_output_proposals(
        "cmp-output-proposals",
        [
            {
                "kind": "schedule.create",
                "summary": "Create a weekly discovery refresh.",
                "payload": {
                    "owner_role": "discovery",
                    "work_type": "discovery",
                    "goal": "Refresh discovery coverage weekly.",
                    "interval_minutes": 10080,
                    "priority": "high",
                },
                "confidence": 0.95,
            },
            {
                "kind": "planning.review_posture",
                "summary": "Strategy output is ready for operator review.",
                "payload": {
                    "work_type": "strategy",
                    "review_state": "ready_for_review",
                    "operator_prompt": "I have a strategy draft ready.",
                },
                "confidence": 0.9,
            },
            {
                "kind": "memory.note",
                "summary": "Save a campaign learning note.",
                "payload": {
                    "destination": NEXT_ACTIONS_DESTINATION,
                    "line": "Pricing interest keeps surfacing early.",
                },
                "confidence": 0.7,
            },
            {
                "kind": "live_action.enqueue_operator_send",
                "summary": "Queue a sandbox group message.",
                "payload": {
                    "account_id": "account_1",
                    "action_type": "send_group_message",
                    "chat_id": "@sandbox_group",
                    "text": "Hello from the sandbox.",
                },
                "confidence": 0.88,
            },
        ],
        source_role="engagement_brain",
        grounding_refs=["campaign:cmp-output-proposals"],
    )

    assert [intent.kind for intent in compiled] == [
        "schedule.create",
        "planning.review_posture",
        "memory.note",
        "live_action.enqueue_operator_send",
    ]
    assert compiled[0].safety_class is CompiledIntentSafetyClass.SCHEDULE_MUTATION
    assert compiled[1].safety_class is CompiledIntentSafetyClass.ADVISORY
    assert compiled[2].safety_class is CompiledIntentSafetyClass.STATE_MUTATION
    assert compiled[3].safety_class is CompiledIntentSafetyClass.EXECUTION_ADJACENT


def test_orchestrator_direct_schedule_request_marks_blocked_compiled_intent(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    session_manager = SessionManager(JsonSessionStore(tmp_path / "sessions.json"))
    approval_manager = ApprovalManager(JsonApprovalStore(tmp_path / "approvals.json"))
    campaign_manager = CampaignManager(campaigns_root)
    compiled_intent_store = CompiledIntentStore(campaigns_root)
    compiled_intent_applicator = CompiledIntentApplicator()

    session = session_manager.start_session("operator-blocked-schedule")
    campaign = campaign_manager.ensure_campaign("operator-blocked-schedule", campaign_id="cmp-blocked-schedule")
    session_manager.attach_campaign(
        session,
        campaign.campaign_id,
        campaign.workspace_path,
        canonical_memory_files=campaign.canonical_files,
        agent_memory_files=campaign.agent_memory_files,
    )

    orchestrator = PurposeBuiltOrchestrator(
        session_manager=session_manager,
        approval_manager=approval_manager,
        campaign_manager=campaign_manager,
        compiled_intent_store=compiled_intent_store,
        compiled_intent_applicator=compiled_intent_applicator,
    )
    response = orchestrator.handle_turn(
        session=session,
        update=TelegramUpdate(
            chat_id="chat-blocked-schedule",
            user_id="operator-blocked-schedule",
            text="Set up a weekly discovery refresh for this campaign.",
        ),
    )

    stored_intents = compiled_intent_store.list_for_campaign(campaign.campaign_id)
    assert len(stored_intents) == 1
    blocked_intent = stored_intents[0]
    assert blocked_intent.status is CompiledIntentStatus.BLOCKED
    assert "Recurring schedule changes are not available" in blocked_intent.blocked_reason
    assert "Recurring schedule changes are not available" in response.messages[0].text

    summary = compiled_intent_store.summarize_recent_outcomes(
        campaign.campaign_id,
        work_type="discovery",
    )
    assert summary["counts"]["blocked"] == 1
    assert summary["items"][0]["status"] == "blocked"


def test_compiled_intent_applicator_can_apply_work_and_memory_note(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    campaign_manager = CampaignManager(campaigns_root)
    work_item_manager = WorkItemManager(campaigns_root)
    campaign = campaign_manager.ensure_campaign("operator-work", campaign_id="cmp-work")
    applicator = CompiledIntentApplicator(
        work_item_manager=work_item_manager,
        campaign_manager=campaign_manager,
    )

    work_intent = build_compiled_intent(
        campaign_id=campaign.campaign_id,
        kind="work.propose",
        summary="Propose a refreshed strategy review.",
        payload={
            "owner_role": "strategy",
            "work_type": "strategy",
            "goal": "Refresh the strategy playbook with the latest conversion friction.",
            "priority": "high",
            "constraints": ["Keep the plan focused on English-speaking groups."],
            "context_refs": ["artifact:strategy-1"],
        },
        source_role="orchestrator",
        safety_class=CompiledIntentSafetyClass.STATE_MUTATION,
    )

    note_intent = build_compiled_intent(
        campaign_id=campaign.campaign_id,
        kind="memory.note",
        summary="Persist an operator-readable next action.",
        payload={
            "destination": NEXT_ACTIONS_DESTINATION,
            "line": "Revisit the CTA framing before the next strategy pass.",
        },
        source_role="orchestrator",
        safety_class=CompiledIntentSafetyClass.STATE_MUTATION,
    )

    assert validate_compiled_intent(work_intent) is None
    assert validate_compiled_intent(note_intent) is None

    work_result = applicator.apply(work_intent)
    note_result = applicator.apply(note_intent)

    work_items = work_item_manager.list_for_campaign(campaign.campaign_id)
    assert len(work_items) == 1
    assert work_items[0].status is WorkItemStatus.PENDING
    assert work_items[0].priority.value == "high"
    assert work_items[0].context_refs == ["artifact:strategy-1"]
    assert "Proposed `strategy` work" in work_result
    assert "Saved a campaign memory note" in note_result
    assert "Revisit the CTA framing" in (campaigns_root / campaign.campaign_id / "next-actions.md").read_text(encoding="utf-8")


def test_compiled_intent_applicator_can_queue_low_risk_live_action(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    campaign_manager = CampaignManager(campaigns_root)
    live_execution_manager = LiveExecutionManager(campaigns_root)
    live_execution_service = LiveExecutionService(live_execution_manager)
    campaign = campaign_manager.ensure_campaign("operator-low-risk", campaign_id="cmp-low-risk")
    applicator = CompiledIntentApplicator(
        campaign_manager=campaign_manager,
        live_execution_service=live_execution_service,
    )
    intent = build_compiled_intent(
        campaign_id=campaign.campaign_id,
        kind="live_action.enqueue_low_risk",
        summary="Leave one stale DM thread.",
        payload={
            "action_type": LiveActionType.LEAVE_DIALOG.value,
            "account_id": "reader-1",
            "peer_id": "user-42",
        },
        source_role="orchestrator",
        safety_class=CompiledIntentSafetyClass.EXECUTION_ADJACENT,
    )

    result = applicator.apply(intent)
    queued_actions = live_execution_manager.list_for_campaign(campaign.campaign_id)

    assert "Queued low-risk action `leave_dialog`" in result
    assert len(queued_actions) == 1
    assert queued_actions[0].action_type is LiveActionType.LEAVE_DIALOG
    assert queued_actions[0].payload["peer_id"] == "user-42"


def test_validate_low_risk_live_action_rejects_send_actions() -> None:
    intent = build_compiled_intent(
        campaign_id="cmp-invalid-low-risk-send",
        kind="live_action.enqueue_low_risk",
        summary="Try to send a message through the low-risk path.",
        payload={
            "account_id": "account_1",
            "action_type": "send_message",
            "chat_id": "@sandbox_group",
            "text": "Hello.",
        },
        source_role="orchestrator",
        safety_class=CompiledIntentSafetyClass.EXECUTION_ADJACENT,
    )

    assert (
        validate_compiled_intent(intent)
        == "Outbound sends must use `live_action.enqueue_operator_send`, not `live_action.enqueue_low_risk`."
    )


def test_compiled_intent_applicator_can_queue_operator_send_group_message(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    campaign_manager = CampaignManager(campaigns_root)
    live_execution_manager = LiveExecutionManager(campaigns_root)
    live_execution_service = LiveExecutionService(live_execution_manager)
    campaign = campaign_manager.ensure_campaign("operator-send", campaign_id="cmp-operator-send")
    applicator = CompiledIntentApplicator(
        campaign_manager=campaign_manager,
        live_execution_service=live_execution_service,
    )
    intent = build_compiled_intent(
        campaign_id=campaign.campaign_id,
        kind="live_action.enqueue_operator_send",
        summary="Send one sandbox group message.",
        payload={
            "account_id": "sender-1",
            "operator_id": "operator-123",
            "action_type": "send_message",
            "chat_id": "@sandbox_group",
            "text": "Hello from the sandbox.",
        },
        source_role="orchestrator",
        safety_class=CompiledIntentSafetyClass.EXECUTION_ADJACENT,
    )

    assert validate_compiled_intent(intent) is None

    result = applicator.apply(intent)
    queued_actions = live_execution_manager.list_for_campaign(campaign.campaign_id)

    assert "Queued operator-approved send `send_group_message`" in result
    assert len(queued_actions) == 1
    assert queued_actions[0].action_type is LiveActionType.SEND_GROUP_MESSAGE
    assert queued_actions[0].payload["chat_id"] == "@sandbox_group"
    assert queued_actions[0].payload["text"] == "Hello from the sandbox."
    approval_context = queued_actions[0].payload["approval_context"]
    assert approval_context["approval_mode"] == "operator"
    assert approval_context["approved_by"] == "operator-123"
    assert queued_actions[0].conversation_id == ""


def test_compiled_intent_applicator_ignores_stray_conversation_id_on_group_message(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    campaign_manager = CampaignManager(campaigns_root)
    live_execution_manager = LiveExecutionManager(campaigns_root)
    live_execution_service = LiveExecutionService(live_execution_manager)
    campaign = campaign_manager.ensure_campaign("operator-send-stray-conversation", campaign_id="cmp-stray-conversation")
    applicator = CompiledIntentApplicator(
        campaign_manager=campaign_manager,
        live_execution_service=live_execution_service,
    )
    intent = build_compiled_intent(
        campaign_id=campaign.campaign_id,
        kind="live_action.enqueue_operator_send",
        summary="Send one sandbox group message with stray conversation linkage.",
        payload={
            "account_id": "sender-1",
            "operator_id": "operator-123",
            "action_type": "send_group_message",
            "chat_id": "@sandbox_group",
            "text": "Hello from the sandbox.",
            "conversation_id": "session-not-a-thread",
        },
        source_role="orchestrator",
        safety_class=CompiledIntentSafetyClass.EXECUTION_ADJACENT,
    )

    assert validate_compiled_intent(intent) is None

    applicator.apply(intent)
    queued_actions = live_execution_manager.list_for_campaign(campaign.campaign_id)

    assert len(queued_actions) == 1
    assert queued_actions[0].action_type is LiveActionType.SEND_GROUP_MESSAGE
    assert queued_actions[0].conversation_id == ""
    assert "conversation_id" not in queued_actions[0].payload["approval_context"]


def test_parse_output_proposals_supports_fenced_marker_then_fenced_json() -> None:
    output = """
Queued both joins now.

```
COMPILED_PROPOSALS_JSON
```

```json
[
  {
    "kind": "live_action.enqueue_low_risk",
    "summary": "Join @swarmtestgroup with account @maximovkaxxx.",
    "payload": {
      "account_id": "account_38671210769",
      "action_type": "join_community",
      "community_id": "swarmtestgroup",
      "conversation_id": "conv-1"
    },
    "confidence": 0.97
  }
]
```

Joins queued.
""".strip()

    proposals = parse_output_proposal_list(output)

    assert proposals is not None
    assert len(proposals) == 1
    assert proposals[0]["kind"] == "live_action.enqueue_low_risk"
    assert proposals[0]["payload"]["community_id"] == "swarmtestgroup"


def test_compiled_intent_applicator_can_apply_review_request_and_belief_update(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    campaign_manager = CampaignManager(campaigns_root)
    work_item_manager = WorkItemManager(campaigns_root)
    conversation_manager = ExternalConversationManager(campaigns_root)
    campaign = campaign_manager.ensure_campaign("operator-review", campaign_id="cmp-review")
    work_item = work_item_manager.ensure_work_item(
        campaign.campaign_id,
        owner_role="strategy",
        work_type="strategy",
        goal="Refresh the strategy playbook.",
        status=WorkItemStatus.IN_PROGRESS,
    )
    assert work_item is not None
    conversation_manager.save(
        ExternalConversationRecord(
            conversation_id="conv-review-1",
            campaign_id=campaign.campaign_id,
            account_id="reader-1",
            peer_id="user-42",
            chat_id="user-42",
            thread_origin=ThreadOrigin.DIRECT_INBOUND_DM,
            consent_posture=ConsentPosture.INBOUND_ONLY,
            status=ExternalConversationStatus.ACTIVE,
            external_user_messaged_first=True,
        )
    )
    applicator = CompiledIntentApplicator(
        work_item_manager=work_item_manager,
        conversation_manager=conversation_manager,
    )

    review_intent = compile_review_request(
        campaign.campaign_id,
        review_payload={
            "work_item_id": work_item.work_item_id,
            "owner_role": "strategy",
            "work_type": "strategy",
            "summary": "Strategy playbook ready for operator review.",
            "context_refs": ["artifact:strategy-2"],
            "related_memory_refs": ["artifact:strategy-2"],
        },
        source_role="orchestrator",
    )
    belief_intent = compile_conversation_belief_update(
        campaign.campaign_id,
        conversation_id="conv-review-1",
        belief_state=ConversationBeliefState(
            intent_posture="evaluating_fit",
            known_fit_signals=["asked about pricing"],
            commercial_stage="potential_fit",
            last_meaningful_shift="The thread showed early commercial curiosity.",
            suggested_next_move="Ask one narrow qualifying question.",
        ),
        summary="The thread showed early commercial curiosity.",
        source_role="engagement_brain",
    )

    assert review_intent is not None
    assert validate_compiled_intent(review_intent) is None
    assert validate_compiled_intent(belief_intent) is None

    review_result = applicator.apply(review_intent)
    belief_result = applicator.apply(belief_intent)
    updated_work_item = work_item_manager.get(campaign.campaign_id, work_item.work_item_id)
    updated_conversation = conversation_manager.get(campaign.campaign_id, "conv-review-1")

    assert updated_work_item is not None
    assert updated_work_item.status is WorkItemStatus.REVIEW_PENDING
    assert updated_work_item.context_refs == ["artifact:strategy-2"]
    assert updated_work_item.related_memory_refs == ["artifact:strategy-2"]
    assert updated_conversation is not None
    assert updated_conversation.belief_state.intent_posture == "evaluating_fit"
    assert updated_conversation.belief_state.known_fit_signals == ["asked about pricing"]
    assert updated_conversation.summary == "The thread showed early commercial curiosity."
    assert "ready for operator review" in review_result.lower()
    assert "updated belief state" in belief_result.lower()


def test_orchestrator_schedule_action_persists_compiled_intent_before_apply(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    session_manager = SessionManager(JsonSessionStore(tmp_path / "sessions.json"))
    approval_manager = ApprovalManager(JsonApprovalStore(tmp_path / "approvals.json"))
    campaign_manager = CampaignManager(campaigns_root)
    schedule_manager = ScheduleManager(campaigns_root)
    compiled_intent_store = CompiledIntentStore(campaigns_root)
    compiled_intent_applicator = CompiledIntentApplicator(schedule_manager=schedule_manager)

    session = session_manager.start_session("operator-schedule-intent")
    campaign = campaign_manager.ensure_campaign("operator-schedule-intent", campaign_id="cmp-schedule-intent")
    session_manager.attach_campaign(
        session,
        campaign.campaign_id,
        campaign.workspace_path,
        canonical_memory_files=campaign.canonical_files,
        agent_memory_files=campaign.agent_memory_files,
    )

    orchestrator_output = """I'll keep discovery coverage fresh with a weekly recurring refresh.

COMPILED_PROPOSALS_JSON
```json
[
  {
    "kind": "schedule.create",
    "summary": "Create a weekly recurring discovery refresh.",
    "payload": {
      "owner_role": "discovery",
      "work_type": "discovery",
      "goal": "Refresh the discovery shortlist for AI founder communities.",
      "interval_minutes": 10080,
      "constraints": ["Keep the shortlist focused on Europe."],
      "priority": "high"
    },
    "confidence": 0.95
  }
]
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
            schedule_manager=schedule_manager,
            campaign_manager=campaign_manager,
            compiled_intent_store=compiled_intent_store,
            compiled_intent_applicator=compiled_intent_applicator,
        )
        response = orchestrator.handle_turn(
            session=session,
            update=TelegramUpdate(
                chat_id="chat-schedule-intent",
                user_id="operator-schedule-intent",
                text="Set up a weekly discovery refresh for this campaign.",
            ),
        )

    stored_intents = compiled_intent_store.list_for_campaign(campaign.campaign_id)
    assert len(stored_intents) == 1
    compiled_intent = stored_intents[0]
    assert compiled_intent.kind == "schedule.create"
    assert compiled_intent.status is CompiledIntentStatus.APPLIED
    assert compiled_intent.accepted_at is not None
    assert compiled_intent.applied_at is not None
    assert "Saved a recurring `discovery` schedule" in compiled_intent.application_result
    assert "Saved a recurring `discovery` schedule" in response.messages[0].text


def test_orchestrator_operator_send_request_persists_compiled_intent_before_apply(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    session_manager = SessionManager(JsonSessionStore(tmp_path / "sessions.json"))
    approval_manager = ApprovalManager(JsonApprovalStore(tmp_path / "approvals.json"))
    campaign_manager = CampaignManager(campaigns_root)
    live_execution_manager = LiveExecutionManager(campaigns_root)
    live_execution_service = LiveExecutionService(live_execution_manager)
    compiled_intent_store = CompiledIntentStore(campaigns_root)
    compiled_intent_applicator = CompiledIntentApplicator(
        campaign_manager=campaign_manager,
        live_execution_service=live_execution_service,
    )

    session = session_manager.start_session("operator-direct-send")
    campaign = campaign_manager.ensure_campaign("operator-direct-send", campaign_id="cmp-direct-send")
    session_manager.attach_campaign(
        session,
        campaign.campaign_id,
        campaign.workspace_path,
        canonical_memory_files=campaign.canonical_files,
        agent_memory_files=campaign.agent_memory_files,
    )

    orchestrator_output = """I queued the sandbox post now.

COMPILED_PROPOSALS_JSON
```json
[
  {
    "kind": "live_action.enqueue_operator_send",
    "summary": "Send one sandbox group message now.",
    "payload": {
      "account_id": "account_sender_1",
      "action_type": "send_group_message",
      "chat_id": "@sandbox_group",
      "text": "Hello sandbox group."
    },
    "confidence": 0.95
  }
]
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
            campaign_manager=campaign_manager,
            compiled_intent_store=compiled_intent_store,
            compiled_intent_applicator=compiled_intent_applicator,
        )
        response = orchestrator.handle_turn(
            session=session,
            update=TelegramUpdate(
                chat_id="chat-direct-send",
                user_id="operator-direct-send",
                text="Send a sandbox message into our test group now.",
            ),
        )

    stored_intents = compiled_intent_store.list_for_campaign(campaign.campaign_id)
    queued_actions = live_execution_manager.list_for_campaign(campaign.campaign_id)

    assert len(stored_intents) == 1
    compiled_intent = stored_intents[0]
    assert compiled_intent.kind == "live_action.enqueue_operator_send"
    assert compiled_intent.status is CompiledIntentStatus.APPLIED
    assert "Queued operator-approved send `send_group_message`" in compiled_intent.application_result
    assert len(queued_actions) == 1
    assert queued_actions[0].action_type is LiveActionType.SEND_GROUP_MESSAGE
    assert queued_actions[0].payload["approval_context"]["approved_by"] == "operator-direct-send"
    assert "Queued operator-approved send `send_group_message`" in response.messages[0].text


def test_orchestrator_review_pending_persists_review_request_intent(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    session_manager = SessionManager(JsonSessionStore(tmp_path / "sessions.json"))
    campaign_manager = CampaignManager(campaigns_root)
    work_item_manager = WorkItemManager(campaigns_root)
    compiled_intent_store = CompiledIntentStore(campaigns_root)
    compiled_intent_applicator = CompiledIntentApplicator(work_item_manager=work_item_manager)

    session = session_manager.start_session("operator-review-request")
    campaign = campaign_manager.ensure_campaign("operator-review-request", campaign_id="cmp-review-request")
    session_manager.attach_campaign(
        session,
        campaign.campaign_id,
        campaign.workspace_path,
        canonical_memory_files=campaign.canonical_files,
        agent_memory_files=campaign.agent_memory_files,
    )
    work_item = work_item_manager.ensure_work_item(
        campaign.campaign_id,
        owner_role="strategy",
        work_type="strategy",
        goal="Refresh the strategy playbook.",
        status=WorkItemStatus.IN_PROGRESS,
    )
    assert work_item is not None

    orchestrator = PurposeBuiltOrchestrator(
        session_manager=session_manager,
        work_item_manager=work_item_manager,
        campaign_manager=campaign_manager,
        compiled_intent_store=compiled_intent_store,
        compiled_intent_applicator=compiled_intent_applicator,
    )
    orchestrator._mark_review_pending(  # noqa: SLF001
        session,
        work_item,
        result_summary="Strategy playbook ready for operator review.",
        related_memory_refs=["artifact:strategy-99"],
    )

    stored_intents = compiled_intent_store.list_for_campaign(campaign.campaign_id)
    updated_work_item = work_item_manager.get(campaign.campaign_id, work_item.work_item_id)

    assert len(stored_intents) == 1
    assert stored_intents[0].kind == "review.request"
    assert stored_intents[0].status is CompiledIntentStatus.APPLIED
    assert updated_work_item is not None
    assert updated_work_item.status is WorkItemStatus.REVIEW_PENDING
    assert updated_work_item.context_refs == ["artifact:strategy-99"]


def test_orchestrator_reopen_stage_work_item_persists_refresh_intent(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    session_manager = SessionManager(JsonSessionStore(tmp_path / "sessions.json"))
    campaign_manager = CampaignManager(campaigns_root)
    work_item_manager = WorkItemManager(campaigns_root)
    compiled_intent_store = CompiledIntentStore(campaigns_root)
    compiled_intent_applicator = CompiledIntentApplicator(work_item_manager=work_item_manager)

    session = session_manager.start_session("operator-revision-refresh")
    campaign = campaign_manager.ensure_campaign("operator-revision-refresh", campaign_id="cmp-revision-refresh")
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
        summary="Brief",
        data={
            "objective": "Find Telegram communities for AI founders",
            "target_audience": "AI founders",
            "geography": "Europe",
            "constraints": ["Stay value-first."],
        },
    )
    work_item = work_item_manager.ensure_work_item(
        campaign.campaign_id,
        owner_role="discovery",
        work_type="discovery",
        goal="Refresh the discovery shortlist.",
        constraints=["Stay value-first."],
        priority=WorkItemPriority.HIGH,
        status=WorkItemStatus.REVIEW_PENDING,
    )
    assert work_item is not None

    orchestrator = PurposeBuiltOrchestrator(
        session_manager=session_manager,
        work_item_manager=work_item_manager,
        campaign_manager=campaign_manager,
        compiled_intent_store=compiled_intent_store,
        compiled_intent_applicator=compiled_intent_applicator,
    )
    orchestrator._reopen_stage_work_item(  # noqa: SLF001
        session,
        "discovery",
        "Refreshing the community shortlist after operator feedback.",
    )

    stored_intents = compiled_intent_store.list_for_campaign(campaign.campaign_id)
    refreshed_work_item = work_item_manager.get(campaign.campaign_id, work_item.work_item_id)

    assert len(stored_intents) == 1
    assert stored_intents[0].kind == "work.refresh"
    assert stored_intents[0].status is CompiledIntentStatus.APPLIED
    assert stored_intents[0].payload["trigger_source"] == "operator_feedback"
    assert refreshed_work_item is not None
    assert refreshed_work_item.status is WorkItemStatus.IN_PROGRESS
    assert refreshed_work_item.trigger_source == "operator_feedback"
    assert refreshed_work_item.refresh_reason == "Refreshing the community shortlist after operator feedback."


def test_compiled_intent_applicator_can_invalidate_stale_prepared_execution(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    session_manager = SessionManager(JsonSessionStore(tmp_path / "sessions.json"))
    work_item_manager = WorkItemManager(campaigns_root)
    live_execution_manager = LiveExecutionManager(campaigns_root)
    prepared_execution_manager = PreparedExecutionManager(campaigns_root)
    prepared_execution_service = PreparedExecutionService(
        prepared_execution_manager,
        live_execution_manager,
        session_manager=session_manager,
        work_item_manager=work_item_manager,
    )
    campaign_manager = CampaignManager(campaigns_root)
    compiled_intent_store = CompiledIntentStore(campaigns_root)
    applicator = CompiledIntentApplicator(
        prepared_execution_service=prepared_execution_service,
    )

    session = session_manager.start_session("operator-prepared-invalidation")
    campaign = campaign_manager.ensure_campaign("operator-prepared-invalidation", campaign_id="cmp-prepared-invalidation")
    session_manager.attach_campaign(
        session,
        campaign.campaign_id,
        campaign.workspace_path,
        canonical_memory_files=campaign.canonical_files,
        agent_memory_files=campaign.agent_memory_files,
    )
    artifact = session_manager.create_workflow_artifact(
        session=session,
        kind=WorkflowArtifactKind.ACCOUNT_ASSIGNMENT_PLAN,
        title="Account assignment plan",
        summary="Initial plan",
        data={
            "plan_summary": "Initial plan.",
            "assignments": [
                {
                    "community_name": "EU AI Founders",
                    "community_handle": "@eu_ai_founders",
                    "assigned_account": "account_senior_1",
                    "scheduled_posts": [
                        {
                            "day_offset": 0,
                            "time_window": "09:00-11:00",
                            "message_text": "Initial launch draft.",
                        },
                        {
                            "day_offset": 1,
                            "time_window": "10:00-12:00",
                            "message_text": "Initial held draft.",
                        },
                    ],
                }
            ],
        },
    )
    work_item_manager.ensure_work_item(
        campaign.campaign_id,
        owner_role="account_manager",
        work_type="account_planning",
        goal="Prepare an account assignment plan.",
        status=WorkItemStatus.COMPLETED,
    )
    first_activation = prepared_execution_service.activate_latest_plan(session)
    assert first_activation.batch is not None

    artifact.data["assignments"][0]["scheduled_posts"][0]["message_text"] = "Revised launch draft."
    session_manager.save_workflow_artifact(session, artifact)

    invalidation_intent = compile_prepared_execution_invalidation(
        campaign.campaign_id,
        invalidation_payload={
            "reason": "A newer account-plan revision replaced the prepared execution state.",
            "source_plan_artifact_id": artifact.artifact_id,
        },
        source_role="orchestrator",
        grounding_refs=[f"artifact:{artifact.artifact_id}"],
    )
    assert validate_compiled_intent(invalidation_intent) is None
    compiled_intent_store.save(invalidation_intent)
    invalidation_intent.mark_accepted()
    compiled_intent_store.save(invalidation_intent)

    result = applicator.apply(invalidation_intent)
    invalidation_intent.mark_applied(result)
    compiled_intent_store.save(invalidation_intent)

    stored_intent = compiled_intent_store.get(campaign.campaign_id, invalidation_intent.intent_id)
    reloaded_batch = prepared_execution_manager.get_batch(campaign.campaign_id, first_activation.batch.batch_id)
    queued_actions = live_execution_manager.list_for_campaign(campaign.campaign_id)

    assert stored_intent is not None
    assert stored_intent.status is CompiledIntentStatus.APPLIED
    assert "prepared execution state no longer matches this revised plan" in stored_intent.application_result.lower()
    assert reloaded_batch is not None
    assert reloaded_batch.status.value == "superseded"
    assert queued_actions[0].status is LiveActionStatus.CANCELLED


def test_strategy_specialist_output_persists_advisory_planning_proposals(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    session_manager = SessionManager(JsonSessionStore(tmp_path / "sessions.json"))
    campaign_manager = CampaignManager(campaigns_root)
    work_item_manager = WorkItemManager(campaigns_root)
    compiled_intent_store = CompiledIntentStore(campaigns_root)
    compiled_intent_applicator = CompiledIntentApplicator(work_item_manager=work_item_manager)

    session = session_manager.start_session("operator-strategy-proposals")
    campaign = campaign_manager.ensure_campaign("operator-strategy-proposals", campaign_id="cmp-strategy-proposals")
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
        summary="Brief",
        data={
            "objective": "Find Telegram communities for AI founders",
            "target_audience": "AI founders",
            "geography": "Europe",
            "constraints": ["Stay value-first."],
        },
    )
    session_manager.create_workflow_artifact(
        session=session,
        kind=WorkflowArtifactKind.COMMUNITY_SHORTLIST,
        title="Community shortlist",
        summary="Shortlist ready.",
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
                }
            ],
        },
    )

    strategy_output = """Lead with practical founder lessons and keep the tone educational.

STRATEGY_PLAYBOOK_JSON
```json
{
  "campaign_strategy_summary": "Lead with practical founder lessons and keep the tone educational.",
  "communities": [
    {
      "name": "EU AI Founders",
      "handle": "@eu_ai_founders",
      "messaging_angle": "Practical founder lessons",
      "message_format": "text",
      "frequency": "weekly",
      "timing": "weekday mornings",
      "risk_notes": "Keep the tone educational."
    }
  ]
}
```
COMPILED_PROPOSALS_JSON
```json
[
      {
        "kind": "planning.review_posture",
        "summary": "Strategy output is ready for operator review.",
        "payload": {
          "work_type": "strategy",
          "review_state": "ready_for_review",
          "operator_prompt": "I have a strategy draft ready. Tell me what to change, or tell me if you want me to move into account planning next."
        },
        "confidence": 0.95
      },
  {
    "kind": "planning.follow_on_recommendation",
    "summary": "Recommend account planning after strategy review.",
    "payload": {
      "current_work_type": "strategy",
      "recommended_next_work_type": "account_planning",
      "recommended_action": "refresh_if_stale",
      "reason": "Account planning should use the approved strategy playbook as its input."
    },
    "confidence": 0.9
  }
]
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
            work_item_manager=work_item_manager,
            campaign_manager=campaign_manager,
            compiled_intent_store=compiled_intent_store,
            compiled_intent_applicator=compiled_intent_applicator,
        )
        orchestrator._run_strategy_agent(  # noqa: SLF001
            session,
            TelegramUpdate(chat_id="chat-strategy-proposals", user_id="operator-strategy-proposals", text="continue"),
        )

    stored_intents = compiled_intent_store.list_for_campaign(campaign.campaign_id)
    planning_intents = [intent for intent in stored_intents if intent.kind.startswith("planning.")]

    assert {intent.kind for intent in planning_intents} == {
        "planning.review_posture",
        "planning.follow_on_recommendation",
    }
    assert all(intent.status is CompiledIntentStatus.ACCEPTED for intent in planning_intents)
    review_posture = next(intent for intent in planning_intents if intent.kind == "planning.review_posture")
    assert (
        review_posture.payload["operator_prompt"]
        == "I have a strategy draft ready. Tell me what to change, or tell me if you want me to move into account planning next."
    )


def test_account_manager_falls_back_to_default_advisory_proposals(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    session_manager = SessionManager(JsonSessionStore(tmp_path / "sessions.json"))
    campaign_manager = CampaignManager(campaigns_root)
    work_item_manager = WorkItemManager(campaigns_root)
    compiled_intent_store = CompiledIntentStore(campaigns_root)
    compiled_intent_applicator = CompiledIntentApplicator(work_item_manager=work_item_manager)

    session = session_manager.start_session("operator-account-proposals")
    campaign = campaign_manager.ensure_campaign("operator-account-proposals", campaign_id="cmp-account-proposals")
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
        summary="Brief",
        data={
            "objective": "Find Telegram communities for AI founders",
            "target_audience": "AI founders",
            "geography": "Europe",
            "constraints": ["Stay value-first."],
        },
    )
    session_manager.create_workflow_artifact(
        session=session,
        kind=WorkflowArtifactKind.COMMUNITY_SHORTLIST,
        title="Community shortlist",
        summary="Shortlist ready.",
        data={"communities": [{"name": "EU AI Founders", "handle": "@eu_ai_founders"}]},
    )
    session_manager.create_workflow_artifact(
        session=session,
        kind=WorkflowArtifactKind.STRATEGY_PLAYBOOK,
        title="Strategy playbook",
        summary="Strategy ready.",
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

    account_output = """Built a conservative account plan around the approved tone guidance.

ACCOUNT_ASSIGNMENT_PLAN_JSON
```json
{
  "plan_summary": "Use one senior account first and hold the rest for later days.",
  "assignments": [
    {
      "community_name": "EU AI Founders",
      "community_handle": "@eu_ai_founders",
      "assigned_account": "account_senior_1",
      "scheduled_posts": [
        {
          "day_offset": 0,
          "time_window": "09:00-11:00",
          "message_angle": "Founder lessons",
          "message_text": "Sharing one practical founder lesson that has worked well in similar groups."
        }
      ],
      "risk_level": "low",
      "notes": "Start conservatively."
    }
  ]
}
```"""

    fake_content_block = MagicMock()
    fake_content_block.text = account_output
    fake_api_response = MagicMock()
    fake_api_response.content = [fake_content_block]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = fake_api_response

    with patch("anthropic.Anthropic", return_value=mock_client):
        orchestrator = PurposeBuiltOrchestrator(
            session_manager=session_manager,
            work_item_manager=work_item_manager,
            campaign_manager=campaign_manager,
            compiled_intent_store=compiled_intent_store,
            compiled_intent_applicator=compiled_intent_applicator,
        )
        orchestrator._run_account_manager_agent(  # noqa: SLF001
            session,
            TelegramUpdate(chat_id="chat-account-proposals", user_id="operator-account-proposals", text="continue"),
        )

    stored_intents = compiled_intent_store.list_for_campaign(campaign.campaign_id)
    planning_intents = [intent for intent in stored_intents if intent.kind.startswith("planning.")]

    assert {intent.kind for intent in planning_intents} == {
        "planning.review_posture",
        "planning.execution_state_impact",
    }
    assert all(intent.status is CompiledIntentStatus.ACCEPTED for intent in planning_intents)
    review_posture = next(intent for intent in planning_intents if intent.kind == "planning.review_posture")
    assert (
        review_posture.payload["operator_prompt"]
        == "I have an account plan ready. Tell me what to change, or tell me when you want to lock this revision in."
    )


def test_orchestrator_direct_schedule_request_compiles_without_marker_block(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    session_manager = SessionManager(JsonSessionStore(tmp_path / "sessions.json"))
    approval_manager = ApprovalManager(JsonApprovalStore(tmp_path / "approvals.json"))
    campaign_manager = CampaignManager(campaigns_root)
    schedule_manager = ScheduleManager(campaigns_root)
    compiled_intent_store = CompiledIntentStore(campaigns_root)
    compiled_intent_applicator = CompiledIntentApplicator(schedule_manager=schedule_manager)

    session = session_manager.start_session("operator-direct-schedule")
    campaign = campaign_manager.ensure_campaign("operator-direct-schedule", campaign_id="cmp-direct-schedule")
    session_manager.attach_campaign(
        session,
        campaign.campaign_id,
        campaign.workspace_path,
        canonical_memory_files=campaign.canonical_files,
        agent_memory_files=campaign.agent_memory_files,
    )

    mock_client = MagicMock()

    with patch("anthropic.Anthropic", return_value=mock_client):
        orchestrator = PurposeBuiltOrchestrator(
            session_manager=session_manager,
            approval_manager=approval_manager,
            schedule_manager=schedule_manager,
            campaign_manager=campaign_manager,
            compiled_intent_store=compiled_intent_store,
            compiled_intent_applicator=compiled_intent_applicator,
        )
        response = orchestrator.handle_turn(
            session=session,
            update=TelegramUpdate(
                chat_id="chat-direct-schedule",
                user_id="operator-direct-schedule",
                text="Set up a weekly discovery refresh for this campaign.",
            ),
        )

    stored_intents = compiled_intent_store.list_for_campaign(campaign.campaign_id)
    assert len(stored_intents) == 1
    compiled_intent = stored_intents[0]
    assert compiled_intent.kind == "schedule.create"
    assert compiled_intent.status is CompiledIntentStatus.APPLIED
    assert compiled_intent.payload["work_type"] == "discovery"
    assert "Saved a recurring `discovery` schedule" in response.messages[0].text
    assert mock_client.messages.create.call_count == 0


def test_review_approval_persists_follow_on_work_compiled_intent(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    session_manager = SessionManager(JsonSessionStore(tmp_path / "sessions.json"))
    campaign_manager = CampaignManager(campaigns_root)
    work_item_manager = WorkItemManager(campaigns_root)
    compiled_intent_store = CompiledIntentStore(campaigns_root)
    compiled_intent_applicator = CompiledIntentApplicator(work_item_manager=work_item_manager)

    session = session_manager.start_session("operator-follow-on")
    campaign = campaign_manager.ensure_campaign("operator-follow-on", campaign_id="cmp-follow-on")
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
        summary="Brief",
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
        summary="Shortlist ready.",
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
                    "recent_tone_summary": "Recent posts look conversational.",
                    "source_notes": ["Live Telegram validation."],
                }
            ],
        },
    )
    session_manager.replace_workflow_snapshot(
        session,
        WorkflowSnapshot(
            stage=WorkflowStage.DISCOVERY,
            summary="Community shortlist ready for operator review.",
        ),
    )
    work_item_manager.ensure_work_item(
        campaign.campaign_id,
        owner_role="discovery",
        work_type="discovery",
        goal="Review the current shortlist.",
        constraints=["Stay value-first."],
        priority=WorkItemPriority.HIGH,
        status=WorkItemStatus.REVIEW_PENDING,
    )

    strategy_output = """Refined the value-first founder positioning.

STRATEGY_PLAYBOOK_JSON
```json
{
  "campaign_strategy_summary": "Lead with practical founder lessons and keep the tone educational.",
  "communities": [
    {
      "name": "EU AI Founders",
      "handle": "@eu_ai_founders",
      "messaging_angle": "Practical founder lessons",
      "message_format": "text",
      "frequency": "weekly",
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
            work_item_manager=work_item_manager,
            campaign_manager=campaign_manager,
            compiled_intent_store=compiled_intent_store,
            compiled_intent_applicator=compiled_intent_applicator,
        )
        response = orchestrator.handle_turn(
            session,
            TelegramUpdate(
                chat_id="chat-follow-on",
                user_id="operator-follow-on",
                text="approve",
            ),
        )

    stored_intents = compiled_intent_store.list_for_campaign(campaign.campaign_id)
    follow_on_intents = [intent for intent in stored_intents if intent.kind == "work.propose"]
    strategy_work = work_item_manager.find_latest(campaign.campaign_id, work_type="strategy")

    assert "value-first founder positioning" in response.messages[0].text.lower()
    assert len(follow_on_intents) == 1
    assert follow_on_intents[0].status is CompiledIntentStatus.APPLIED
    assert follow_on_intents[0].payload["work_type"] == "strategy"
    assert follow_on_intents[0].payload["trigger_source"] == "review_acceptance"
    assert follow_on_intents[0].payload["status"] == "in_progress"
    assert strategy_work is not None
    assert strategy_work.status is WorkItemStatus.REVIEW_PENDING
    assert strategy_work.trigger_source == "review_acceptance"
    assert "refreshing strategy planning" in strategy_work.refresh_reason.lower()


def test_review_approval_refreshes_existing_follow_on_work_with_compiled_intent(tmp_path) -> None:
    campaigns_root = tmp_path / "campaigns"
    session_manager = SessionManager(JsonSessionStore(tmp_path / "sessions.json"))
    campaign_manager = CampaignManager(campaigns_root)
    work_item_manager = WorkItemManager(campaigns_root)
    compiled_intent_store = CompiledIntentStore(campaigns_root)
    compiled_intent_applicator = CompiledIntentApplicator(work_item_manager=work_item_manager)

    session = session_manager.start_session("operator-follow-on-refresh")
    campaign = campaign_manager.ensure_campaign("operator-follow-on-refresh", campaign_id="cmp-follow-on-refresh")
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
        summary="Brief",
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
        kind=WorkflowArtifactKind.STRATEGY_PLAYBOOK,
        title="Strategy playbook",
        summary="Old strategy",
        data={
            "campaign_strategy_summary": "Old positioning.",
            "communities": [],
        },
    )
    session_manager.create_workflow_artifact(
        session=session,
        kind=WorkflowArtifactKind.COMMUNITY_SHORTLIST,
        title="Community shortlist",
        summary="Updated shortlist ready.",
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
                    "recent_tone_summary": "Recent posts look conversational.",
                    "source_notes": ["Live Telegram validation."],
                }
            ],
        },
    )
    session_manager.replace_workflow_snapshot(
        session,
        WorkflowSnapshot(
            stage=WorkflowStage.DISCOVERY,
            summary="Community shortlist ready for operator review.",
        ),
    )
    work_item_manager.ensure_work_item(
        campaign.campaign_id,
        owner_role="discovery",
        work_type="discovery",
        goal="Review the current shortlist.",
        constraints=["Stay value-first."],
        priority=WorkItemPriority.HIGH,
        status=WorkItemStatus.REVIEW_PENDING,
    )
    work_item_manager.ensure_work_item(
        campaign.campaign_id,
        owner_role="strategy",
        work_type="strategy",
        goal="Refresh the strategy playbook.",
        constraints=["Stay value-first."],
        priority=WorkItemPriority.HIGH,
        status=WorkItemStatus.COMPLETED,
    )

    strategy_output = """Refined the value-first founder positioning.

STRATEGY_PLAYBOOK_JSON
```json
{
  "campaign_strategy_summary": "Lead with practical founder lessons and keep the tone educational.",
  "communities": [
    {
      "name": "EU AI Founders",
      "handle": "@eu_ai_founders",
      "messaging_angle": "Practical founder lessons",
      "message_format": "text",
      "frequency": "weekly",
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
            work_item_manager=work_item_manager,
            campaign_manager=campaign_manager,
            compiled_intent_store=compiled_intent_store,
            compiled_intent_applicator=compiled_intent_applicator,
        )
        response = orchestrator.handle_turn(
            session,
            TelegramUpdate(
                chat_id="chat-follow-on-refresh",
                user_id="operator-follow-on-refresh",
                text="approve",
            ),
        )

    stored_intents = compiled_intent_store.list_for_campaign(campaign.campaign_id)
    follow_on_intents = [intent for intent in stored_intents if intent.kind == "work.refresh"]
    strategy_work = work_item_manager.find_latest(campaign.campaign_id, work_type="strategy")

    assert "value-first founder positioning" in response.messages[0].text.lower()
    assert len(follow_on_intents) == 1
    assert follow_on_intents[0].status is CompiledIntentStatus.APPLIED
    assert follow_on_intents[0].payload["work_type"] == "strategy"
    assert follow_on_intents[0].payload["status"] == "in_progress"
    assert strategy_work is not None
    assert strategy_work.status is WorkItemStatus.REVIEW_PENDING
    assert strategy_work.trigger_source == "review_acceptance"
