from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import inspect
from types import SimpleNamespace

from telegram_app.campaign_signals import CampaignSignalBridge, CampaignSignalManager, ObservationWorkRefresher
from telegram_app.capabilities.mtproto import AccountRecord, AccountRegistry, MessagingCapabilityImpl
from telegram_app.engagement import (
    EngagementEventKind,
    EngagementRoutingStatus,
    ManagedAccountEngagementStore,
    ManagedAccountEventListener,
)
from telegram_app.external_conversations import ExternalConversationManager, ExternalConversationProjector
from telegram_app.work_items import WorkItemManager


class FakeCapabilityWrapper:
    def __init__(self, *, result=None) -> None:  # noqa: ANN001
        self._result = result

    def is_available(self) -> tuple[bool, str]:
        return True, ""

    def run(self, account_id: str, operation):  # noqa: ANN001, ARG002
        return self._result


class FakeListenerWrapper:
    def __init__(self) -> None:
        self.offline_calls = 0

    def connect(self, account_id: str) -> None:  # noqa: ANN001, ARG002
        return None

    def run(self, account_id: str, operation):  # noqa: ANN001, ARG002
        client = _FakeListenerClient(self)
        result = operation(client)
        if inspect.isawaitable(result):
            return asyncio.run(result)
        return result


class _FakeListenerClient:
    def __init__(self, wrapper: FakeListenerWrapper) -> None:
        self._wrapper = wrapper
        self._tg_swarm_inbound_listener_installed = False
        self.handlers: list[tuple[object, object]] = []

    async def __call__(self, request):  # noqa: ANN001
        offline = getattr(request, "offline", None)
        if offline is None and hasattr(request, "kwargs"):
            offline = request.kwargs.get("offline")
        if offline is True:
            self._wrapper.offline_calls += 1
        return True

    def add_event_handler(self, handler, event_filter):  # noqa: ANN001
        self.handlers.append((handler, event_filter))


def test_messaging_send_records_outbound_reference_for_reply_matching(tmp_path) -> None:
    registry = AccountRegistry(tmp_path / "accounts.json")
    registry.save_account(AccountRecord(account_id="reader-1", phone="+15551234567"))
    store = ManagedAccountEngagementStore(tmp_path / "data")
    capability = MessagingCapabilityImpl(
        registry,
        FakeCapabilityWrapper(
            result={
                "message_id": 99,
                "date": "2026-05-23T12:00:00+00:00",
                "text": "hello",
            }
        ),
        engagement_store=store,
    )

    result = capability.send_message(
        "reader-1",
        "-100123",
        "hello",
        approval_context={
            "approved": True,
            "approval_mode": "operator",
            "approval_source": "test_engagement_listener",
            "campaign_id": "cmp-1",
            "conversation_id": "conv-1",
            "asset_refs": ["asset-1"],
            "approved_by": "operator-1",
            "approved_at": "2026-05-23T12:00:00+00:00",
            "approval_id": "ap-1",
        },
    )
    references = store.list_outbound_messages("reader-1")

    assert result.success
    assert len(references) == 1
    assert references[0].chat_id == "-100123"
    assert references[0].message_id == "99"
    assert references[0].campaign_id == "cmp-1"
    assert references[0].conversation_id == "conv-1"
    assert references[0].text == "hello"
    assert references[0].asset_refs == ["asset-1"]


def test_listener_records_inbound_dm_once_across_restarts(tmp_path) -> None:
    registry = AccountRegistry(tmp_path / "accounts.json")
    registry.save_account(AccountRecord(account_id="reader-1", phone="+15551234567"))
    store = ManagedAccountEngagementStore(tmp_path / "data")
    listener = ManagedAccountEventListener(registry, FakeListenerWrapper(), store)
    event = SimpleNamespace(
        is_private=True,
        message=SimpleNamespace(
            id=401,
            chat_id="user-42",
            sender_id="user-42",
            message="hello from a DM",
            date=datetime(2026, 5, 23, 12, 0, tzinfo=UTC),
            is_private=True,
        ),
    )

    first_record = listener.ingest_incoming_event("reader-1", event)
    restarted_listener = ManagedAccountEventListener(registry, FakeListenerWrapper(), store)
    second_record = restarted_listener.ingest_incoming_event("reader-1", event)
    stored_events = store.list_inbound_events("reader-1")
    listener_state = store.get_listener_state("reader-1")

    assert first_record is not None
    assert first_record.event_kind is EngagementEventKind.INBOUND_DM
    assert second_record is None
    assert len(stored_events) == 1
    assert stored_events[0].text == "hello from a DM"
    assert listener_state.last_event_id == first_record.event_id
    assert first_record.dedupe_key in listener_state.recent_dedupe_keys


def test_listener_routes_group_reply_when_outbound_reference_exists(tmp_path) -> None:
    registry = AccountRegistry(tmp_path / "accounts.json")
    registry.save_account(AccountRecord(account_id="reader-1", phone="+15551234567"))
    store = ManagedAccountEngagementStore(tmp_path / "data")
    store.record_outbound_message(
        "reader-1",
        "-100123",
        "777",
        sent_at=datetime(2026, 5, 23, 11, 55, tzinfo=UTC),
        campaign_id="cmp-1",
    )
    listener = ManagedAccountEventListener(registry, FakeListenerWrapper(), store)
    event = SimpleNamespace(
        is_private=False,
        message=SimpleNamespace(
            id=778,
            chat_id="-100123",
            sender_id="member-9",
            message="replying to your post",
            date=datetime(2026, 5, 23, 12, 5, tzinfo=UTC),
            reply_to_msg_id="777",
            is_private=False,
        ),
    )

    record = listener.ingest_incoming_event("reader-1", event)
    stored_events = store.list_inbound_events("reader-1")

    assert record is not None
    assert record.event_kind is EngagementEventKind.GROUP_REPLY
    assert record.campaign_id == "cmp-1"
    assert record.routing_status is EngagementRoutingStatus.ROUTED
    assert len(stored_events) == 1
    assert stored_events[0].reply_to_message_id == "777"


def test_listener_skips_unsupported_inbound_events_without_persisting(tmp_path) -> None:
    registry = AccountRegistry(tmp_path / "accounts.json")
    registry.save_account(AccountRecord(account_id="reader-1", phone="+15551234567"))
    store = ManagedAccountEngagementStore(tmp_path / "data")
    listener = ManagedAccountEventListener(registry, FakeListenerWrapper(), store)
    unsupported_event = SimpleNamespace(
        is_private=False,
        message=SimpleNamespace(
            id=901,
            chat_id="-100123",
            sender_id="member-11",
            message="ambient group chatter",
            date=datetime(2026, 5, 23, 12, 30, tzinfo=UTC),
            is_private=False,
        ),
    )

    record = listener.ingest_incoming_event("reader-1", unsupported_event)

    assert record is None
    assert store.list_inbound_events("reader-1") == []


def test_listener_sets_managed_account_offline_after_attaching(tmp_path) -> None:
    registry = AccountRegistry(tmp_path / "accounts.json")
    registry.save_account(AccountRecord(account_id="reader-1", phone="+15551234567"))
    store = ManagedAccountEngagementStore(tmp_path / "data")
    wrapper = FakeListenerWrapper()
    listener = ManagedAccountEventListener(registry, wrapper, store)

    listener._start_listener_for_account("reader-1")

    assert "reader-1" in listener._active_account_ids  # noqa: SLF001
    assert wrapper.offline_calls == 1


def test_listener_projects_routed_group_reply_into_campaign_conversation_state(tmp_path) -> None:
    registry = AccountRegistry(tmp_path / "accounts.json")
    registry.save_account(AccountRecord(account_id="reader-1", phone="+15551234567"))
    store = ManagedAccountEngagementStore(tmp_path / "data")
    store.record_outbound_message(
        "reader-1",
        "-100123",
        "777",
        sent_at=datetime(2026, 5, 23, 11, 55, tzinfo=UTC),
        campaign_id="cmp-1",
    )
    conversation_manager = ExternalConversationManager(tmp_path / "data" / "campaigns")
    listener = ManagedAccountEventListener(
        registry,
        FakeListenerWrapper(),
        store,
        ExternalConversationProjector(conversation_manager),
    )
    event = SimpleNamespace(
        is_private=False,
        message=SimpleNamespace(
            id=778,
            chat_id="-100123",
            sender_id="member-9",
            message="replying to your post",
            date=datetime(2026, 5, 23, 12, 5, tzinfo=UTC),
            reply_to_msg_id="777",
            is_private=False,
        ),
    )

    record = listener.ingest_incoming_event("reader-1", event)
    conversation = conversation_manager.find_group_reply_thread(
        "cmp-1",
        account_id="reader-1",
        chat_id="-100123",
        reply_target_message_id="777",
    )

    assert record is not None
    assert conversation is not None
    assert conversation.last_event_id == record.event_id
    assert conversation.last_inbound_message_id == "778"


def test_listener_emits_signal_for_repeated_group_reply_pressure(tmp_path) -> None:
    registry = AccountRegistry(tmp_path / "accounts.json")
    registry.save_account(AccountRecord(account_id="reader-1", phone="+15551234567"))
    store = ManagedAccountEngagementStore(tmp_path / "data")
    store.record_outbound_message(
        "reader-1",
        "-100123",
        "777",
        sent_at=datetime(2026, 5, 23, 11, 55, tzinfo=UTC),
        campaign_id="cmp-1",
    )
    campaigns_root = tmp_path / "data" / "campaigns"
    conversation_manager = ExternalConversationManager(campaigns_root)
    signal_manager = CampaignSignalManager(campaigns_root)
    work_item_manager = WorkItemManager(campaigns_root)
    listener = ManagedAccountEventListener(
        registry,
        FakeListenerWrapper(),
        store,
        ExternalConversationProjector(
            conversation_manager,
            signal_bridge=CampaignSignalBridge(
                signal_manager,
                observation_work_refresher=ObservationWorkRefresher(signal_manager, work_item_manager),
            ),
        ),
    )
    first_event = SimpleNamespace(
        is_private=False,
        message=SimpleNamespace(
            id=778,
            chat_id="-100123",
            sender_id="member-9",
            message="first reply to your post",
            date=datetime(2026, 5, 23, 12, 5, tzinfo=UTC),
            reply_to_msg_id="777",
            is_private=False,
        ),
    )
    second_event = SimpleNamespace(
        is_private=False,
        message=SimpleNamespace(
            id=779,
            chat_id="-100123",
            sender_id="member-9",
            message="following up again on your post",
            date=datetime(2026, 5, 23, 12, 7, tzinfo=UTC),
            reply_to_msg_id="777",
            is_private=False,
        ),
    )

    first_record = listener.ingest_incoming_event("reader-1", first_event)
    second_record = listener.ingest_incoming_event("reader-1", second_event)
    signals = signal_manager.list_for_campaign("cmp-1")
    observation_item = work_item_manager.find_latest("cmp-1", work_type="observation")

    assert first_record is not None
    assert second_record is not None
    assert len(signals) == 1
    assert signals[0].signal_type == "conversation_high_intent_shift"
    assert signals[0].context_refs[-1] == f"event:{second_record.event_id}"
    assert observation_item is not None
    assert observation_item.work_type == "observation"
