from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

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
    assert "3 joins per 24-hour limit" in result.error


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
        approval_context={"approved": True, "approval_id": "ap-1"},
    )
    account = registry.get_account("reader-1")
    audit_lines = (tmp_path / "audit" / "telegram_actions.jsonl").read_text(encoding="utf-8").strip().splitlines()
    first_event = json.loads(audit_lines[0])
    second_event = json.loads(audit_lines[1])

    assert not blocked.success
    assert "require explicit approved operator context" in blocked.error.lower()
    assert sent.success
    assert sent.data["message_id"] == 99
    assert account is not None
    assert account.metadata["last_send"]["outcome"] == "success"
    assert first_event["category"] == "message_send_blocked"
    assert second_event["category"] == "message_send_succeeded"


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
