from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from telegram_app.capabilities.base import CapabilityResult
from telegram_app.capabilities.mtproto import AccountRecord, AccountRegistry, MessagingCapabilityImpl
from telegram_app.engagement import (
    EngagementEventKind,
    EngagementRoutingStatus,
    ManagedAccountEngagementStore,
    ManagedAccountEventListener,
)
from telegram_app.external_conversations import ExternalConversationManager, ExternalConversationProjector
from telegram_app.live_execution import LiveActionStatus, LiveExecutionManager, LiveExecutionService
from telegram_app.models import WorkItemStatus, WorkflowArtifactKind
from telegram_app.prepared_execution import PreparedExecutionManager, PreparedExecutionService
from telegram_app.sessions import JsonSessionStore, SessionManager
from telegram_app.work_items import WorkItemManager


class AsyncCapabilityWrapper:
    def __init__(self, client) -> None:  # noqa: ANN001
        self._client = client

    def is_available(self) -> tuple[bool, str]:
        return True, ""

    def run(self, account_id: str, operation):  # noqa: ANN001, ARG002
        return __import__("asyncio").run(operation(self._client))


class FakeOutboundMessagingClient:
    def __init__(self) -> None:
        self.send_calls: list[dict[str, object]] = []
        self._message_id = 1000

    async def send_message(self, chat_id: str, text: str, **kwargs) -> SimpleNamespace:
        self._message_id += 1
        self.send_calls.append({"chat_id": chat_id, "text": text, **kwargs})
        return SimpleNamespace(
            id=self._message_id,
            date=datetime(2026, 5, 23, 12, self._message_id - 1001, tzinfo=UTC),
            message=text,
            reply_to_msg_id=kwargs.get("reply_to"),
        )


class FakeListenerWrapper:
    def connect(self, account_id: str) -> None:  # noqa: ANN001, ARG002
        return None

    def run(self, account_id: str, operation):  # noqa: ANN001, ARG002
        return operation(SimpleNamespace())


def test_prepared_wave_activation_dispatches_multi_account_outreach_and_routes_replies(tmp_path) -> None:
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
    session = session_manager.start_session("operator-wave")
    session_manager.attach_campaign(
        session,
        campaign_id="cmp-wave",
        campaign_workspace_path=str(campaigns_root / "cmp-wave"),
    )
    session_manager.create_workflow_artifact(
        session,
        WorkflowArtifactKind.ACCOUNT_ASSIGNMENT_PLAN,
        "Native outreach wave",
        data={
            "plan_summary": "Launch one immediate outreach wave across two accounts.",
            "assignments": [
                {
                    "community_name": "EU AI Founders",
                    "community_handle": "@eu_ai_founders",
                    "assigned_account": "reader-1",
                    "scheduled_posts": [
                        {
                            "day_offset": 0,
                            "time_window": "09:00-11:00",
                            "message_text": "Founder note for the Europe thread.",
                        }
                    ],
                },
                {
                    "community_name": "Paris AI Founders",
                    "community_handle": "@paris_ai_founders",
                    "assigned_account": "reader-2",
                    "scheduled_posts": [
                        {
                            "day_offset": 0,
                            "time_window": "09:00-11:00",
                            "message_text": "Founder note for the Paris thread.",
                        }
                    ],
                },
            ],
        },
    )
    work_item_manager.ensure_work_item(
        "cmp-wave",
        owner_role="account_manager",
        work_type="account_planning",
        goal="Prepare an account assignment plan.",
        status=WorkItemStatus.COMPLETED,
    )

    activation = prepared_execution_service.activate_latest_plan(session)

    registry = AccountRegistry(tmp_path / "accounts.json")
    registry.save_account(AccountRecord(account_id="reader-1", phone="+15551230001", health="active"))
    registry.save_account(AccountRecord(account_id="reader-2", phone="+15551230002", health="active"))
    engagement_store = ManagedAccountEngagementStore(tmp_path / "data")
    messaging_client = FakeOutboundMessagingClient()
    live_execution_service = LiveExecutionService(
        live_execution_manager,
        messaging_capability=MessagingCapabilityImpl(
            registry,
            AsyncCapabilityWrapper(messaging_client),
            engagement_store=engagement_store,
        ),
        worker_id="worker-wave",
    )

    first = live_execution_service.dispatch_next_ready(now=datetime(2026, 5, 23, 12, 0, tzinfo=UTC))
    second = live_execution_service.dispatch_next_ready(now=datetime(2026, 5, 23, 12, 1, tzinfo=UTC))

    listener = ManagedAccountEventListener(
        registry,
        FakeListenerWrapper(),
        engagement_store,
        ExternalConversationProjector(ExternalConversationManager(campaigns_root)),
    )
    outbound_reader_1 = engagement_store.list_outbound_messages("reader-1")
    outbound_reader_2 = engagement_store.list_outbound_messages("reader-2")
    first_reply = listener.ingest_incoming_event(
        "reader-1",
        SimpleNamespace(
            is_private=False,
            message=SimpleNamespace(
                id=2001,
                chat_id="@eu_ai_founders",
                sender_id="member-1",
                message="Can you share more about this?",
                date=datetime(2026, 5, 23, 12, 5, tzinfo=UTC),
                reply_to_msg_id=outbound_reader_1[0].message_id,
                is_private=False,
            ),
        ),
    )
    second_reply = listener.ingest_incoming_event(
        "reader-2",
        SimpleNamespace(
            is_private=False,
            message=SimpleNamespace(
                id=2002,
                chat_id="@paris_ai_founders",
                sender_id="member-2",
                message="Interesting angle. What do you mean?",
                date=datetime(2026, 5, 23, 12, 6, tzinfo=UTC),
                reply_to_msg_id=outbound_reader_2[0].message_id,
                is_private=False,
            ),
        ),
    )
    conversation_manager = ExternalConversationManager(campaigns_root)
    first_conversation = conversation_manager.find_group_reply_thread(
        "cmp-wave",
        account_id="reader-1",
        chat_id="@eu_ai_founders",
        reply_target_message_id=outbound_reader_1[0].message_id,
    )
    second_conversation = conversation_manager.find_group_reply_thread(
        "cmp-wave",
        account_id="reader-2",
        chat_id="@paris_ai_founders",
        reply_target_message_id=outbound_reader_2[0].message_id,
    )

    assert activation.status == "activated"
    assert activation.queued_count == 2
    assert first is not None
    assert second is not None
    assert first.status is LiveActionStatus.SUCCEEDED
    assert second.status is LiveActionStatus.SUCCEEDED
    assert [call["chat_id"] for call in messaging_client.send_calls] == [
        "@eu_ai_founders",
        "@paris_ai_founders",
    ]
    assert len(outbound_reader_1) == 1
    assert len(outbound_reader_2) == 1
    assert first_reply is not None
    assert second_reply is not None
    assert first_reply.event_kind is EngagementEventKind.GROUP_REPLY
    assert second_reply.routing_status is EngagementRoutingStatus.ROUTED
    assert first_conversation is not None
    assert second_conversation is not None
    assert first_conversation.last_inbound_message_id == "2001"
    assert second_conversation.last_inbound_message_id == "2002"
