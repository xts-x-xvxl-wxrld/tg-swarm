from __future__ import annotations

from unittest.mock import MagicMock

from telegram_app.app_service import TelegramAppService
from telegram_app.auth import AuthGatewayResult, AuthManager, InMemoryAuthStateStore, JsonAuthStateStore
from telegram_app.capabilities.mtproto.registry import AccountRegistry
from telegram_app.approvals import ApprovalManager, JsonApprovalStore
from telegram_app.sessions import JsonSessionStore, SessionManager
from telegram_app.transport import TelegramResponse, TelegramUpdate


def _update(
    text: str,
    *,
    user_id: str = "operator-1",
    chat_id: str = "chat-1",
    command: str | None = None,
) -> TelegramUpdate:
    return TelegramUpdate(
        chat_id=chat_id,
        user_id=user_id,
        text=text,
        command=command,
    )


class FakeAuthGateway:
    def __init__(self) -> None:
        self.cancelled_account_ids: list[str] = []
        self.code_results: list[AuthGatewayResult] = []
        self.password_results: list[AuthGatewayResult] = []
        self.request_calls: list[tuple[str, str]] = []
        self.request_results: list[AuthGatewayResult] = []
        self.sign_in_code_calls: list[tuple[str, str, str, str]] = []
        self.sign_in_password_calls: list[tuple[str, str]] = []

    def request_login_code(self, account_id: str, phone: str) -> AuthGatewayResult:
        self.request_calls.append((account_id, phone))
        if not self.request_results:
            raise AssertionError("No request_login_code result queued.")
        return self.request_results.pop(0)

    def sign_in_with_code(
        self,
        account_id: str,
        phone: str,
        code: str,
        phone_code_hash: str,
    ) -> AuthGatewayResult:
        self.sign_in_code_calls.append((account_id, phone, code, phone_code_hash))
        if not self.code_results:
            raise AssertionError("No sign_in_with_code result queued.")
        return self.code_results.pop(0)

    def sign_in_with_password(self, account_id: str, password: str) -> AuthGatewayResult:
        self.sign_in_password_calls.append((account_id, password))
        if not self.password_results:
            raise AssertionError("No sign_in_with_password result queued.")
        return self.password_results.pop(0)

    def cancel_login(self, account_id: str) -> None:
        self.cancelled_account_ids.append(account_id)


def test_auth_manager_starts_and_resumes_active_wizard(tmp_path) -> None:
    gateway = FakeAuthGateway()
    registry = AccountRegistry(tmp_path / "accounts.json")
    manager = AuthManager(InMemoryAuthStateStore(), registry=registry, gateway=gateway)

    first_response = manager.start(_update("/addaccount", command="/addaccount"))
    resumed_response = manager.start(_update("/addaccount", command="/addaccount"))

    assert "step 1 of 3" in first_response.messages[0].text.lower()
    assert "already in progress" in resumed_response.messages[0].text.lower()
    assert manager.get_active_for_operator("operator-1") is not None


def test_auth_manager_persists_phone_step_and_completes_after_restart(tmp_path) -> None:
    store_path = tmp_path / "auth_states.json"
    registry = AccountRegistry(tmp_path / "accounts.json")
    gateway = FakeAuthGateway()
    gateway.request_results.append(AuthGatewayResult(success=True, phone_code_hash="hash-1"))
    gateway.code_results.append(AuthGatewayResult(success=True, user={"id": 42, "username": "growth_ops"}))

    manager = AuthManager(JsonAuthStateStore(store_path), registry=registry, gateway=gateway)
    manager.start(_update("/addaccount", command="/addaccount"))

    phone_response = manager.handle_update(_update("+1 555 123 4567"))
    restarted_manager = AuthManager(JsonAuthStateStore(store_path), registry=registry, gateway=gateway)
    code_response = restarted_manager.handle_update(_update("24680"))

    stored_account = registry.find_by_phone("+15551234567")
    assert "step 2 of 3" in phone_response.messages[0].text.lower()
    assert "now onboarded" in code_response.messages[0].text.lower()
    assert stored_account is not None
    assert stored_account.account_id == "account_15551234567"
    assert stored_account.metadata["username"] == "growth_ops"
    assert restarted_manager.get_active_for_operator("operator-1") is None


def test_auth_manager_refreshes_expired_code_when_telegram_allows_retry(tmp_path) -> None:
    gateway = FakeAuthGateway()
    gateway.request_results.extend(
        [
            AuthGatewayResult(success=True, phone_code_hash="hash-1"),
            AuthGatewayResult(success=True, phone_code_hash="hash-2"),
        ]
    )
    gateway.code_results.append(
        AuthGatewayResult(
            success=False,
            error="The confirmation code expired.",
            error_code="code_expired",
        )
    )
    registry = AccountRegistry(tmp_path / "accounts.json")
    manager = AuthManager(JsonAuthStateStore(tmp_path / "auth_states.json"), registry=registry, gateway=gateway)

    manager.start(_update("/addaccount", command="/addaccount"))
    manager.handle_update(_update("+15551234567"))
    response = manager.handle_update(_update("00000"))

    active_state = manager.get_active_for_operator("operator-1")
    assert active_state is not None
    assert active_state.phone_code_hash == "hash-2"
    assert active_state.code_attempts == 0
    assert "fresh one" in response.messages[0].text.lower()
    assert gateway.request_calls == [
        ("account_15551234567", "+15551234567"),
        ("account_15551234567", "+15551234567"),
    ]


def test_auth_manager_moves_to_password_step_then_retries_and_completes(tmp_path) -> None:
    gateway = FakeAuthGateway()
    gateway.request_results.append(AuthGatewayResult(success=True, phone_code_hash="hash-1"))
    gateway.code_results.append(AuthGatewayResult(success=False, password_required=True))
    gateway.password_results.extend(
        [
            AuthGatewayResult(success=False, error="Password is incorrect."),
            AuthGatewayResult(success=True, user={"id": 99, "first_name": "Alex"}),
        ]
    )
    registry = AccountRegistry(tmp_path / "accounts.json")
    manager = AuthManager(JsonAuthStateStore(tmp_path / "auth_states.json"), registry=registry, gateway=gateway)

    manager.start(_update("/addaccount", command="/addaccount"))
    manager.handle_update(_update("+15551234567"))
    password_prompt = manager.handle_update(_update("24680"))
    retry_response = manager.handle_update(_update("wrong-password"))
    success_response = manager.handle_update(_update("correct-password"))

    stored_account = registry.get_account("account_15551234567")
    assert "2fa enabled" in password_prompt.messages[0].text.lower()
    assert "attempt 1" in retry_response.messages[0].text.lower()
    assert "now onboarded" in success_response.messages[0].text.lower()
    assert stored_account is not None
    assert stored_account.metadata["first_name"] == "Alex"
    assert manager.get_active_for_operator("operator-1") is None


def test_telegram_app_service_routes_auth_flow_before_orchestrator_turns(tmp_path) -> None:
    gateway = FakeAuthGateway()
    gateway.request_results.append(AuthGatewayResult(success=True, phone_code_hash="hash-1"))
    auth_manager = AuthManager(
        InMemoryAuthStateStore(),
        registry=AccountRegistry(tmp_path / "accounts.json"),
        gateway=gateway,
    )
    session_manager = SessionManager(JsonSessionStore(tmp_path / "sessions.json"))
    approval_manager = ApprovalManager(JsonApprovalStore(tmp_path / "approvals.json"))
    orchestrator = MagicMock()
    orchestrator.handle_turn.return_value = TelegramResponse.single("chat-1", "orchestrator turn")

    service = TelegramAppService(
        session_manager=session_manager,
        approval_manager=approval_manager,
        orchestrator=orchestrator,
        auth_manager=auth_manager,
    )

    start_response = service.handle_update(_update("/addaccount", command="/addaccount"))
    phone_response = service.handle_update(_update("+15551234567"))
    cancel_response = service.handle_update(_update("/cancelauth", command="/cancelauth"))

    assert "step 1 of 3" in start_response.messages[0].text.lower()
    assert "step 2 of 3" in phone_response.messages[0].text.lower()
    assert cancel_response.messages[0].text == "Account onboarding cancelled."
    assert gateway.cancelled_account_ids == ["account_15551234567"]
    assert orchestrator.handle_turn.call_count == 0
