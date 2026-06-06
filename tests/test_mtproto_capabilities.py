from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import json
from types import SimpleNamespace
from unittest.mock import patch

from telegram_app.capabilities.mtproto.audit_logger import JsonlAuditLogger

from server import create_telegram_app_service
from telegram_app.capabilities import StubAccountCapability
from telegram_app.capabilities.mtproto import (
    AccountCapabilityImpl,
    AccountRecord,
    AccountRegistry,
    CommunityCapabilityImpl,
    MembershipCapabilityImpl,
    MessagingCapabilityImpl,
    TelethonClientWrapper,
    TelethonSessionManager,
)
from telegram_app.engagement import ManagedAccountEngagementStore
from telegram_app.capabilities.mtproto.registry import to_iso8601, utc_now


class FakeTelegramClient:
    def __init__(self, session_path: str, api_id: int, api_hash: str) -> None:
        self.session_path = session_path
        self.api_id = api_id
        self.api_hash = api_hash
        self.connected = False

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    def is_connected(self) -> bool:
        return self.connected

    async def fetch_identity(self) -> dict[str, str | int]:
        await asyncio.sleep(0)
        return {
            "session_path": self.session_path,
            "api_id": self.api_id,
        }


class FakeCapabilityWrapper:
    def __init__(self, *, result=None, error: Exception | None = None) -> None:  # noqa: ANN001
        self._result = result
        self._error = error

    def is_available(self) -> tuple[bool, str]:
        return True, ""

    def run(self, account_id: str, operation):  # noqa: ANN001
        if self._error is not None:
            raise self._error
        return self._result


class AsyncCapabilityWrapper:
    def __init__(self, client) -> None:  # noqa: ANN001
        self._client = client

    def is_available(self) -> tuple[bool, str]:
        return True, ""

    def run(self, account_id: str, operation):  # noqa: ANN001
        return asyncio.run(operation(self._client))


class FloodWaitError(Exception):
    def __init__(self, seconds: int) -> None:
        self.seconds = seconds
        super().__init__(f"Flood wait for {seconds} seconds")


class FakeSearchClient:
    def __init__(self, contacts_chats: list[object], global_chats: list[object]) -> None:
        self.contacts_chats = contacts_chats
        self.global_chats = global_chats
        self.request_names: list[str] = []

    async def get_entity(self, query: str):  # noqa: ANN001
        return self.contacts_chats[0]

    async def __call__(self, request):  # noqa: ANN001
        request_name = type(request).__name__
        self.request_names.append(request_name)
        if request_name == "SearchRequest":
            return SimpleNamespace(chats=self.contacts_chats)
        if request_name == "SearchGlobalRequest":
            return SimpleNamespace(chats=self.global_chats)
        raise AssertionError(f"Unexpected request type: {request_name}")


class FakeMessagingClient:
    def __init__(self, *, target_entity: object | None = None) -> None:
        self.send_calls: list[dict[str, object]] = []
        self.read_ack_calls: list[dict[str, object]] = []
        self.delete_dialog_calls: list[str] = []
        self.status_calls: list[bool] = []
        self.action_calls: list[dict[str, object]] = []
        self.target_entity = target_entity or SimpleNamespace(broadcast=False, megagroup=True, title="Example Group")

    async def __call__(self, request):  # noqa: ANN001
        offline = getattr(request, "offline", None)
        if offline is None and hasattr(request, "kwargs"):
            offline = request.kwargs.get("offline")
        if isinstance(offline, bool):
            self.status_calls.append(offline)
        return True

    def action(self, chat_id: str, action_name: str):  # noqa: ANN001
        client = self

        class _ActionContext:
            async def __aenter__(self_inner) -> None:
                client.action_calls.append({"phase": "start", "chat_id": chat_id, "action": action_name})

            async def __aexit__(self_inner, exc_type, exc, tb) -> None:  # noqa: ANN001
                client.action_calls.append({"phase": "stop", "chat_id": chat_id, "action": action_name})

        return _ActionContext()

    async def send_message(self, chat_id: str, text: str, **kwargs) -> SimpleNamespace:
        self.send_calls.append({"chat_id": chat_id, "text": text, **kwargs})
        return SimpleNamespace(
            id=321,
            date=datetime(2026, 5, 23, 12, 0, tzinfo=UTC),
            message=text,
            reply_to_msg_id=kwargs.get("reply_to"),
        )

    async def send_read_acknowledge(self, chat_id: str, message=None, *, max_id=None, clear_mentions=False, clear_reactions=False):  # noqa: ANN001
        self.read_ack_calls.append(
            {
                "chat_id": chat_id,
                "message": message,
                "max_id": max_id,
                "clear_mentions": clear_mentions,
                "clear_reactions": clear_reactions,
            }
        )
        return True

    async def get_messages(self, peer_id: str, limit: int = 20):  # noqa: ANN001
        return [
            SimpleNamespace(
                id=501,
                chat_id=peer_id,
                sender_id="user-42",
                message="Recent inbound context",
                date=datetime(2026, 5, 23, 11, 55, tzinfo=UTC),
                reply_to_msg_id=499,
                out=False,
                views=None,
            )
        ][:limit]

    async def get_entity(self, chat_id: str):  # noqa: ANN001
        return self.target_entity

    def iter_dialogs(self, limit: int = 20):  # noqa: ANN001
        async def generator():
            for index in range(limit):
                yield SimpleNamespace(
                    id=f"peer-{index + 1}",
                    name=f"Dialog {index + 1}",
                    unread_count=index,
                    archived=False,
                    is_user=index == 0,
                    is_group=index == 1,
                    is_channel=False,
                    entity=SimpleNamespace(id=f"peer-{index + 1}"),
                    message=SimpleNamespace(
                        id=700 + index,
                        message=f"preview-{index + 1}",
                        date=datetime(2026, 5, 23, 11, 50 + index, tzinfo=UTC),
                    ),
                )

        return generator()

    async def delete_dialog(self, peer_id: str, *, revoke: bool = False) -> None:
        self.delete_dialog_calls.append(peer_id)


class FlakyButDeliveredMessagingClient(FakeMessagingClient):
    def __init__(self) -> None:
        super().__init__()
        self._delivered_messages: list[SimpleNamespace] = []

    async def send_message(self, chat_id: str, text: str, **kwargs) -> SimpleNamespace:
        self.send_calls.append({"chat_id": chat_id, "text": text, **kwargs})
        delivered = SimpleNamespace(
            id=654,
            chat_id=chat_id,
            sender_id="self",
            message=text,
            date=datetime.now(UTC),
            reply_to_msg_id=kwargs.get("reply_to"),
            out=True,
            views=None,
        )
        self._delivered_messages.insert(0, delivered)
        raise OSError()

    async def get_messages(self, peer_id: str, limit: int = 20):  # noqa: ANN001
        combined = list(self._delivered_messages)
        combined.extend(await super().get_messages(peer_id, limit=limit))
        return combined[:limit]


class UserNotParticipantError(Exception):
    pass


class PeerIdInvalidError(Exception):
    pass


class MessageIdInvalidError(Exception):
    pass


class ChatWriteForbiddenError(Exception):
    pass


class FakeJoinClient:
    def __init__(self, entity: object) -> None:
        self.entity = entity
        self.join_requests: list[object] = []

    async def get_entity(self, community_id: str):  # noqa: ANN001
        return self.entity

    async def __call__(self, request):  # noqa: ANN001
        self.join_requests.append(request)
        return SimpleNamespace()


def _operator_approval_context(*, campaign_id: str = "cmp-1") -> dict[str, object]:
    return {
        "approved": True,
        "approval_mode": "operator",
        "approval_source": "test_mtproto_capabilities",
        "campaign_id": campaign_id,
        "approved_by": "operator-1",
        "approved_at": "2026-05-23T12:00:00+00:00",
        "approval_id": "ap-1",
    }


def _autonomous_approval_context(*, campaign_id: str = "cmp-1", conversation_id: str = "conv-1") -> dict[str, object]:
    return {
        "approved": True,
        "approval_mode": "autonomous",
        "approval_source": "engagement_brain_authorizer",
        "authorization_decision": "allowed",
        "authorized_action_type": "send_dm_reply",
        "campaign_id": campaign_id,
        "conversation_id": conversation_id,
        "context_fingerprint": "ctx-1",
        "authorized_at": "2026-05-23T12:00:00+00:00",
    }


def test_account_registry_persists_and_reads_accounts(tmp_path) -> None:
    registry = AccountRegistry(tmp_path / "accounts.json")
    registry.save_account(
        AccountRecord(
            account_id="reader-1",
            phone="+15551234567",
            tier="senior",
            health="active",
        )
    )

    reloaded_registry = AccountRegistry(tmp_path / "accounts.json")
    accounts = reloaded_registry.list_accounts()

    assert len(accounts) == 1
    assert accounts[0].account_id == "reader-1"
    assert accounts[0].phone == "+15551234567"


def test_telethon_client_wrapper_runs_async_client_calls_synchronously(tmp_path) -> None:
    session_manager = TelethonSessionManager(
        tmp_path / "sessions",
        client_factory=lambda session_path, api_id, api_hash: FakeTelegramClient(
            session_path,
            api_id,
            api_hash,
        ),
    )
    wrapper = TelethonClientWrapper(
        api_id=12345,
        api_hash="secret-hash",
        session_manager=session_manager,
    )

    identity = wrapper.run("reader-1", lambda client: client.fetch_identity())

    assert identity["api_id"] == 12345
    assert "reader-1" in str(identity["session_path"])


def test_telethon_session_manager_uses_namespaced_worker_session_copy(tmp_path) -> None:
    sessions_dir = tmp_path / "sessions"
    canonical_session = sessions_dir / "reader-1.session"
    canonical_session.parent.mkdir(parents=True, exist_ok=True)
    canonical_session.write_text("canonical", encoding="utf-8")

    session_manager = TelethonSessionManager(
        sessions_dir,
        session_namespace="listener",
        client_factory=lambda session_path, api_id, api_hash: FakeTelegramClient(
            session_path,
            api_id,
            api_hash,
        ),
    )

    client = session_manager.build_client("reader-1", 12345, "secret-hash")

    worker_session = sessions_dir / "reader-1__listener.session"
    assert worker_session.exists()
    assert worker_session.read_text(encoding="utf-8") == "canonical"
    assert client.session_path.endswith("reader-1__listener")


def test_telethon_session_manager_delete_session_file_removes_canonical_and_namespaced_artifacts(tmp_path) -> None:
    sessions_dir = tmp_path / "sessions"
    canonical_session = sessions_dir / "reader-1.session"
    worker_session = sessions_dir / "reader-1__executor.session"
    for candidate in (canonical_session, worker_session):
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_text("session", encoding="utf-8")

    session_manager = TelethonSessionManager(sessions_dir, session_namespace="executor")

    session_manager.delete_session_file("reader-1")

    assert not canonical_session.exists()
    assert not worker_session.exists()


def test_membership_join_enforces_pacing_limit_before_telegram_call(tmp_path) -> None:
    registry = AccountRegistry(tmp_path / "accounts.json")
    registry.save_account(
        AccountRecord(
            account_id="reader-1",
            phone="+15551234567",
            join_count_24h=3,
            join_window_started_at=to_iso8601(utc_now()),
        )
    )

    session_manager = TelethonSessionManager(
        tmp_path / "sessions",
        client_factory=lambda session_path, api_id, api_hash: FakeTelegramClient(
            session_path,
            api_id,
            api_hash,
        ),
    )
    wrapper = TelethonClientWrapper(
        api_id=12345,
        api_hash="secret-hash",
        session_manager=session_manager,
    )
    capability = MembershipCapabilityImpl(registry, wrapper)

    result = capability.join("reader-1", "@example_group")

    assert not result.success
    assert "2 joins per 24-hour warmup limit" in result.error


def test_membership_join_records_rate_limit_audit_and_health(tmp_path) -> None:
    registry = AccountRegistry(tmp_path / "accounts.json")
    registry.save_account(
        AccountRecord(
            account_id="reader-1",
            phone="+15551234567",
            health="active",
        )
    )
    audit_logger = JsonlAuditLogger(tmp_path / "audit" / "telegram_actions.jsonl")
    capability = MembershipCapabilityImpl(
        registry,
        FakeCapabilityWrapper(error=FloodWaitError(45)),
        audit_logger=audit_logger,
    )

    result = capability.join("reader-1", "@example_group")
    account = registry.get_account("reader-1")
    audit_lines = (tmp_path / "audit" / "telegram_actions.jsonl").read_text(encoding="utf-8").strip().splitlines()
    latest_event = json.loads(audit_lines[-1])

    assert not result.success
    assert result.data["wait_seconds"] == 45
    assert account is not None
    assert account.health == "rate_limited"
    assert latest_event["category"] == "membership_join_failed"


def test_membership_join_defers_broadcast_channels(tmp_path) -> None:
    registry = AccountRegistry(tmp_path / "accounts.json")
    registry.save_account(
        AccountRecord(
            account_id="reader-1",
            phone="+15551234567",
            health="active",
        )
    )
    client = FakeJoinClient(SimpleNamespace(broadcast=True, megagroup=False, title="Example Channel"))
    capability = MembershipCapabilityImpl(
        registry,
        AsyncCapabilityWrapper(client),
    )

    result = capability.join("reader-1", "@example_channel")

    assert not result.success
    assert result.data["outcome_code"] == "channel_join_deferred"
    assert "deferred in this version" in result.error.lower()
    assert client.join_requests == []


def test_messaging_send_requires_approval_and_records_success(tmp_path) -> None:
    registry = AccountRegistry(tmp_path / "accounts.json")
    registry.save_account(
        AccountRecord(
            account_id="reader-1",
            phone="+15551234567",
            health="active",
        )
    )
    audit_logger = JsonlAuditLogger(tmp_path / "audit" / "telegram_actions.jsonl")
    capability = MessagingCapabilityImpl(
        registry,
        FakeCapabilityWrapper(result={"message_id": 99, "date": "2026-05-11T12:00:00+00:00", "text": "hello"}),
        audit_logger=audit_logger,
    )

    blocked = capability.send_message("reader-1", "@example_group", "hello")
    sent = capability.send_message(
        "reader-1",
        "@example_group",
        "hello",
        approval_context=_operator_approval_context(campaign_id="cmp-1"),
    )
    legacy = capability.send_message(
        "reader-1",
        "@example_group",
        "hello again",
        approval_context={"approved": True, "campaign_id": "cmp-1"},
    )
    account = registry.get_account("reader-1")
    audit_lines = (tmp_path / "audit" / "telegram_actions.jsonl").read_text(encoding="utf-8").strip().splitlines()
    first_event = json.loads(audit_lines[0])
    second_event = json.loads(audit_lines[1])
    third_event = json.loads(audit_lines[2])

    assert not blocked.success
    assert "structured approved-send context" in blocked.error.lower()
    assert sent.success
    assert not legacy.success
    assert sent.data["message_id"] == 99
    assert account is not None
    assert account.metadata["last_send"]["outcome"] == "success"
    assert first_event["category"] == "message_send_blocked"
    assert second_event["category"] == "message_send_succeeded"
    assert third_event["category"] == "message_send_blocked"


def test_messaging_send_defers_broadcast_channels(tmp_path) -> None:
    registry = AccountRegistry(tmp_path / "accounts.json")
    registry.save_account(AccountRecord(account_id="reader-1", phone="+15551234567", health="active"))
    client = FakeMessagingClient(
        target_entity=SimpleNamespace(broadcast=True, megagroup=False, title="Example Channel")
    )
    capability = MessagingCapabilityImpl(registry, AsyncCapabilityWrapper(client))

    result = capability.send_message(
        "reader-1",
        "@example_channel",
        "hello",
        approval_context=_operator_approval_context(campaign_id="cmp-1"),
    )

    assert not result.success
    assert result.data["outcome_code"] == "channel_send_deferred"
    assert "deferred in this version" in result.error.lower()
    assert client.send_calls == []


def test_messaging_send_preserves_long_text_payload(tmp_path) -> None:
    registry = AccountRegistry(tmp_path / "accounts.json")
    registry.save_account(AccountRecord(account_id="reader-1", phone="+15551234567", health="active"))
    client = FakeMessagingClient()
    capability = MessagingCapabilityImpl(registry, AsyncCapabilityWrapper(client))
    long_text = "Founder note " * 400

    result = capability.send_message(
        "reader-1",
        "@example_group",
        long_text,
        approval_context=_operator_approval_context(campaign_id="cmp-1"),
    )

    assert result.success
    assert client.send_calls[0]["text"] == long_text
    assert client.send_calls[0]["parse_mode"] == "html"
    assert client.status_calls == [False, True]
    assert client.action_calls == [
        {"phase": "start", "chat_id": "@example_group", "action": "typing"},
        {"phase": "stop", "chat_id": "@example_group", "action": "typing"},
    ]
    assert client.read_ack_calls == []
    assert result.data["text"] == long_text


def test_messaging_send_uses_explicit_html_formatting_policy(tmp_path) -> None:
    registry = AccountRegistry(tmp_path / "accounts.json")
    registry.save_account(AccountRecord(account_id="reader-1", phone="+15551234567", health="active"))
    client = FakeMessagingClient()
    capability = MessagingCapabilityImpl(registry, AsyncCapabilityWrapper(client))

    result = capability.send_message(
        "reader-1",
        "@example_group",
        "Say `activate` and **review carefully**.",
        approval_context=_operator_approval_context(campaign_id="cmp-1"),
    )

    assert result.success
    assert client.send_calls[0]["text"] == "Say <code>activate</code> and <b>review carefully</b>."
    assert client.send_calls[0]["parse_mode"] == "html"
    assert result.data["text"] == "Say <code>activate</code> and <b>review carefully</b>."


def test_messaging_send_recovers_from_ambiguous_transient_error_without_duplicate_retry(tmp_path) -> None:
    registry = AccountRegistry(tmp_path / "accounts.json")
    registry.save_account(AccountRecord(account_id="reader-1", phone="+15551234567", health="active"))
    store = ManagedAccountEngagementStore(tmp_path / "data")
    client = FlakyButDeliveredMessagingClient()
    capability = MessagingCapabilityImpl(
        registry,
        AsyncCapabilityWrapper(client),
        engagement_store=store,
    )

    result = capability.send_message(
        "reader-1",
        "@example_group",
        "Quick sandbox check from SwarmKit",
        approval_context=_operator_approval_context(campaign_id="cmp-1"),
    )
    references = store.list_outbound_messages("reader-1")

    assert result.success
    assert result.data["verified_after_retry_error"] is True
    assert result.data["recovered_error_code"] == "transient_error"
    assert len(client.send_calls) == 1
    assert len(references) == 1
    assert references[0].text == "Quick sandbox check from SwarmKit"


def test_messaging_send_classifies_peer_invalid(tmp_path) -> None:
    registry = AccountRegistry(tmp_path / "accounts.json")
    registry.save_account(AccountRecord(account_id="reader-1", phone="+15551234567", health="active"))
    capability = MessagingCapabilityImpl(
        registry,
        FakeCapabilityWrapper(error=PeerIdInvalidError("bad peer")),
    )

    result = capability.send_message(
        "reader-1",
        "@missing_chat",
        "hello",
        approval_context=_operator_approval_context(campaign_id="cmp-1"),
    )
    account = registry.get_account("reader-1")

    assert not result.success
    assert result.data["outcome_code"] == "peer_invalid"
    assert "could not resolve that chat or peer" in result.error.lower()
    assert account is not None
    assert account.metadata["last_send"]["outcome"] == "peer_invalid"


def test_messaging_send_reply_classifies_missing_reply_target_message(tmp_path) -> None:
    registry = AccountRegistry(tmp_path / "accounts.json")
    registry.save_account(AccountRecord(account_id="reader-1", phone="+15551234567", health="active"))
    capability = MessagingCapabilityImpl(
        registry,
        FakeCapabilityWrapper(error=MessageIdInvalidError("missing reply target")),
    )

    result = capability.send_reply(
        "reader-1",
        "-100123",
        "777",
        "replying",
        approval_context=_autonomous_approval_context(campaign_id="cmp-1"),
    )
    account = registry.get_account("reader-1")

    assert not result.success
    assert result.data["outcome_code"] == "message_not_found"
    assert "could not find the target message" in result.error.lower()
    assert account is not None
    assert account.metadata["last_send_reply"]["outcome"] == "message_not_found"


def test_messaging_send_classifies_write_forbidden(tmp_path) -> None:
    registry = AccountRegistry(tmp_path / "accounts.json")
    registry.save_account(AccountRecord(account_id="reader-1", phone="+15551234567", health="active"))
    capability = MessagingCapabilityImpl(
        registry,
        FakeCapabilityWrapper(error=ChatWriteForbiddenError("forbidden")),
    )

    result = capability.send_message(
        "reader-1",
        "@guarded_chat",
        "hello",
        approval_context=_operator_approval_context(campaign_id="cmp-1"),
    )
    account = registry.get_account("reader-1")

    assert not result.success
    assert result.data["outcome_code"] == "write_forbidden"
    assert "not allowed to post" in result.error.lower()
    assert account is not None
    assert account.health == "flagged"


def test_messaging_send_reply_uses_reply_target_and_records_outbound_reference(tmp_path) -> None:
    registry = AccountRegistry(tmp_path / "accounts.json")
    registry.save_account(
        AccountRecord(
            account_id="reader-1",
            phone="+15551234567",
            health="active",
        )
    )
    store = ManagedAccountEngagementStore(tmp_path / "data")
    client = FakeMessagingClient()
    capability = MessagingCapabilityImpl(
        registry,
        AsyncCapabilityWrapper(client),
        engagement_store=store,
    )

    result = capability.send_reply(
        "reader-1",
        "-100123",
        "777",
        "Replying in thread",
        approval_context=_autonomous_approval_context(campaign_id="cmp-1"),
    )
    references = store.list_outbound_messages("reader-1")
    account = registry.get_account("reader-1")

    assert result.success
    assert result.data["reply_to_message_id"] == "777"
    assert client.read_ack_calls == [
        {
            "chat_id": "-100123",
            "message": None,
            "max_id": 777,
            "clear_mentions": False,
            "clear_reactions": False,
        }
    ]
    assert client.send_calls == [
        {
            "chat_id": "-100123",
            "text": "Replying in thread",
            "parse_mode": "html",
            "reply_to": 777,
        }
    ]
    assert client.status_calls == [False, True]
    assert len(references) == 1
    assert references[0].message_id == "321"
    assert references[0].campaign_id == "cmp-1"
    assert account is not None
    assert account.metadata["last_send_reply"]["outcome"] == "success"


def test_messaging_mark_read_returns_normalized_success(tmp_path) -> None:
    registry = AccountRegistry(tmp_path / "accounts.json")
    registry.save_account(AccountRecord(account_id="reader-1", phone="+15551234567", health="active"))
    client = FakeMessagingClient()
    capability = MessagingCapabilityImpl(registry, AsyncCapabilityWrapper(client))

    result = capability.mark_read("reader-1", "user-42", message_id="501")
    account = registry.get_account("reader-1")

    assert result.success
    assert result.data["message_id"] == "501"
    assert client.status_calls == [False, True]
    assert client.read_ack_calls == [
        {
            "chat_id": "user-42",
            "message": None,
            "max_id": 501,
            "clear_mentions": False,
            "clear_reactions": False,
        }
    ]
    assert account is not None
    assert account.metadata["last_mark_read"]["outcome"] == "success"


def test_messaging_get_dialog_history_is_account_scoped(tmp_path) -> None:
    registry = AccountRegistry(tmp_path / "accounts.json")
    registry.save_account(AccountRecord(account_id="reader-1", phone="+15551234567", health="active"))
    client = FakeMessagingClient()
    capability = MessagingCapabilityImpl(registry, AsyncCapabilityWrapper(client))

    result = capability.get_dialog_history("reader-1", "user-42", limit=5)

    assert result.success
    assert result.data["account_id"] == "reader-1"
    assert result.data["chat_id"] == "user-42"
    assert result.data["messages"][0]["reply_to_message_id"] == "499"
    assert client.status_calls == [False, True]
    assert client.read_ack_calls == [
        {
            "chat_id": "user-42",
            "message": None,
            "max_id": 501,
            "clear_mentions": False,
            "clear_reactions": False,
        }
    ]


def test_messaging_list_recent_dialogs_returns_compact_dialogs(tmp_path) -> None:
    registry = AccountRegistry(tmp_path / "accounts.json")
    registry.save_account(AccountRecord(account_id="reader-1", phone="+15551234567", health="active"))
    client = FakeMessagingClient()
    capability = MessagingCapabilityImpl(registry, AsyncCapabilityWrapper(client))

    result = capability.list_recent_dialogs("reader-1", limit=2)

    assert result.success
    assert len(result.data["dialogs"]) == 2
    assert result.data["dialogs"][0]["peer_id"] == "peer-1"
    assert result.data["dialogs"][0]["last_message_text"] == "preview-1"
    assert client.status_calls == [False, True]


def test_messaging_leave_dialog_treats_already_not_participating_as_success(tmp_path) -> None:
    registry = AccountRegistry(tmp_path / "accounts.json")
    registry.save_account(AccountRecord(account_id="reader-1", phone="+15551234567", health="active"))
    capability = MessagingCapabilityImpl(
        registry,
        FakeCapabilityWrapper(error=UserNotParticipantError("already gone")),
    )

    result = capability.leave_dialog("reader-1", "user-42")
    account = registry.get_account("reader-1")

    assert result.success
    assert result.data["outcome_code"] == "already_not_participating"
    assert account is not None
    assert account.metadata["last_leave_dialog"]["outcome"] == "success"


def test_messaging_send_stops_after_first_ambiguous_transient_error(tmp_path, monkeypatch) -> None:
    registry = AccountRegistry(tmp_path / "accounts.json")
    registry.save_account(AccountRecord(account_id="reader-1", phone="+15551234567", health="active"))
    client = FakeMessagingClient()

    class RetryableSendError(Exception):
        pass

    class FlakyCapabilityWrapper:
        def __init__(self) -> None:
            self.calls = 0

        def is_available(self) -> tuple[bool, str]:
            return True, ""

        def run(self, account_id: str, operation):  # noqa: ANN001, ARG002
            self.calls += 1
            if self.calls < 5:
                raise RetryableSendError("temporary failure")
            return asyncio.run(operation(client))

    backoff_seconds: list[float] = []

    capability = MessagingCapabilityImpl(registry, FlakyCapabilityWrapper())

    monkeypatch.setattr(
        "telegram_app.capabilities.mtproto.impl_messaging.classify_mtproto_exception",
        lambda exc, action: SimpleNamespace(  # noqa: ARG005
            retriable=True,
            health="active",
            wait_seconds=None,
            message="temporary failure",
            code="temporary_failure",
        ),
    )
    monkeypatch.setattr(
        "telegram_app.capabilities.mtproto.presence.block_for_seconds",
        lambda seconds: backoff_seconds.append(seconds),
    )

    result = capability.send_message(
        "reader-1",
        "@example_group",
        "hello",
        approval_context=_operator_approval_context(campaign_id="cmp-1"),
    )

    assert not result.success
    assert result.data["attempts"] == 1
    assert result.data["outcome_code"] == "temporary_failure"
    assert backoff_seconds == []


def test_service_uses_stub_capabilities_by_default(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_CAPABILITY_BACKEND", raising=False)
    monkeypatch.delenv("TG_SWARM_DATA_DIR", raising=False)
    monkeypatch.delenv("TELEGRAM_API_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_API_HASH", raising=False)
    service = create_telegram_app_service(state_dir=tmp_path / "runtime-state")

    assert isinstance(service._orchestrator._account_capability, StubAccountCapability)


def test_service_can_enable_mtproto_capabilities(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_CAPABILITY_BACKEND", "telethon")
    monkeypatch.setenv("TG_SWARM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("TELEGRAM_API_ID", "12345")
    monkeypatch.setenv("TELEGRAM_API_HASH", "secret-hash")

    service = create_telegram_app_service(state_dir=tmp_path / "runtime-state")
    orchestrator = service._orchestrator

    assert isinstance(orchestrator._account_capability, AccountCapabilityImpl)
    assert isinstance(orchestrator._community_capability, CommunityCapabilityImpl)
    assert isinstance(orchestrator._membership_capability, MembershipCapabilityImpl)
    assert isinstance(orchestrator._messaging_capability, MessagingCapabilityImpl)


def test_community_search_uses_global_fallback_for_sparse_harvest_results(tmp_path) -> None:
    registry = AccountRegistry(tmp_path / "accounts.json")
    registry.save_account(
        AccountRecord(
            account_id="reader-1",
            phone="+15551234567",
            health="active",
        )
    )
    contacts_chat = SimpleNamespace(
        id=101,
        title="AI Founders Club",
        username="ai_founders_club",
        megagroup=True,
        participants_count=2100,
        verified=False,
        scam=False,
        restricted=False,
    )
    global_duplicate = SimpleNamespace(
        id=101,
        title="AI Founders Club",
        username="ai_founders_club",
        megagroup=True,
        participants_count=2100,
        verified=False,
        scam=False,
        restricted=False,
    )
    global_chat = SimpleNamespace(
        id=202,
        title="Paris AI Founders",
        username="paris_ai_founders",
        megagroup=True,
        participants_count=980,
        verified=False,
        scam=False,
        restricted=False,
    )
    capability = CommunityCapabilityImpl(
        registry,
        AsyncCapabilityWrapper(FakeSearchClient([contacts_chat], [global_duplicate, global_chat])),
    )

    result = capability.search("AI founders", mode="harvest", limit=10)

    assert result.success
    assert result.data["source"] == "telethon_hybrid_harvest"
    assert result.data["fallback_used"] is True
    assert [item["search_source"] for item in result.data["results"]] == [
        "telethon_contacts_search",
        "telethon_messages_search_global",
    ]
    assert [item["username"] for item in result.data["results"]] == [
        "ai_founders_club",
        "paris_ai_founders",
    ]


def test_community_search_exact_mode_skips_global_fallback(tmp_path) -> None:
    registry = AccountRegistry(tmp_path / "accounts.json")
    registry.save_account(
        AccountRecord(
            account_id="reader-1",
            phone="+15551234567",
            health="active",
        )
    )
    contacts_chat = SimpleNamespace(
        id=101,
        title="AI Founders Club",
        username="ai_founders_club",
        megagroup=True,
        participants_count=2100,
        verified=False,
        scam=False,
        restricted=False,
    )
    client = FakeSearchClient([contacts_chat], [])
    capability = CommunityCapabilityImpl(
        registry,
        AsyncCapabilityWrapper(client),
    )

    result = capability.search("AI founders", mode="exact", limit=10)

    assert result.success
    assert result.data["source"] == "telethon_contacts_search"
    assert result.data["fallback_used"] is False
    assert client.request_names == ["SearchRequest"]
