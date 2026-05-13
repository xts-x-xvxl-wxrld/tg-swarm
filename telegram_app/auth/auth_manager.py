"""Operator-facing wizard for onboarding Telegram user accounts."""

from __future__ import annotations

import re
from typing import Protocol
from uuid import uuid4

from telegram_app.auth.auth_store import AuthStateStore
from telegram_app.auth.models import AuthGatewayResult, AuthStep, PendingAuthState
from telegram_app.capabilities.mtproto.registry import AccountRecord, AccountRegistry, to_iso8601, utc_now
from telegram_app.transport import TelegramResponse, TelegramUpdate

_PHONE_PATTERN = re.compile(r"^\+?[0-9][0-9\s\-]{6,}$")
_CODE_PATTERN = re.compile(r"[0-9A-Za-z]+")


class AuthGateway(Protocol):
    """Minimal MTProto operations needed for onboarding."""

    def request_login_code(self, account_id: str, phone: str) -> AuthGatewayResult:
        """Request Telegram to send a login code."""

    def sign_in_with_code(
        self,
        account_id: str,
        phone: str,
        code: str,
        phone_code_hash: str,
    ) -> AuthGatewayResult:
        """Complete sign-in with a login code."""

    def sign_in_with_password(self, account_id: str, password: str) -> AuthGatewayResult:
        """Complete sign-in with a Telegram 2FA password."""

    def cancel_login(self, account_id: str) -> None:
        """Clean up any partial login state."""


class AuthManager:
    """Own the onboarding state machine outside the campaign workflow."""

    def __init__(
        self,
        store: AuthStateStore,
        registry: AccountRegistry | None = None,
        gateway: AuthGateway | None = None,
    ) -> None:
        self._store = store
        self._registry = registry
        self._gateway = gateway

    def get_active_for_operator(self, operator_id: str) -> PendingAuthState | None:
        """Return the active onboarding flow for an operator, if present."""
        return self._store.get_active_for_operator(operator_id)

    def start(self, update: TelegramUpdate) -> TelegramResponse:
        """Start a new operator-facing account onboarding flow."""
        active = self.get_active_for_operator(update.user_id)
        if active is not None:
            return TelegramResponse.single(update.chat_id, self._resume_message(active))

        if not self._is_available():
            return TelegramResponse.single(update.chat_id, self._unavailable_message())

        state = PendingAuthState(
            auth_id=str(uuid4()),
            operator_id=update.user_id,
            chat_id=update.chat_id,
        )
        self._store.create(state)
        return TelegramResponse.single(
            update.chat_id,
            "Account onboarding started.\n\nStep 1 of 3: send the phone number for the Telegram user account, including country code.",
        )

    def cancel(self, update: TelegramUpdate) -> TelegramResponse:
        """Cancel a pending onboarding flow and clean up partial MTProto state."""
        state = self.get_active_for_operator(update.user_id)
        if state is None:
            return TelegramResponse.single(update.chat_id, "There is no active account onboarding flow to cancel.")

        if self._gateway is not None and state.account_id:
            self._gateway.cancel_login(state.account_id)

        state.step = AuthStep.CANCELLED
        state.last_error = ""
        state.code_attempts = 0
        state.password_attempts = 0
        state.touch()
        self._store.update(state)
        return TelegramResponse.single(update.chat_id, "Account onboarding cancelled.")

    def handle_update(self, update: TelegramUpdate) -> TelegramResponse:
        """Advance the onboarding wizard using the operator's latest message."""
        state = self.get_active_for_operator(update.user_id)
        if state is None:
            return TelegramResponse.single(update.chat_id, "No account onboarding is in progress.")

        if update.command is not None:
            return TelegramResponse.single(
                update.chat_id,
                "Finish the current account onboarding step, or send /cancelauth to exit the wizard.",
            )

        if state.step is AuthStep.WAITING_PHONE:
            return self._handle_phone_step(state, update)
        if state.step is AuthStep.WAITING_CODE:
            return self._handle_code_step(state, update)
        if state.step is AuthStep.WAITING_PASSWORD:
            return self._handle_password_step(state, update)

        return TelegramResponse.single(
            update.chat_id,
            "This onboarding flow is no longer active. Start a new one with /addaccount.",
        )

    def _handle_phone_step(self, state: PendingAuthState, update: TelegramUpdate) -> TelegramResponse:
        phone = self._normalize_phone(update.text)
        if not phone:
            return TelegramResponse.single(
                update.chat_id,
                "That does not look like a valid phone number yet. Send it with the country code, for example `+15551234567`.",
            )

        assert self._registry is not None
        assert self._gateway is not None

        existing = self._registry.find_by_phone(phone)
        if existing is not None:
            return TelegramResponse.single(
                update.chat_id,
                f"The phone number {phone} is already onboarded as `{existing.account_id}`.",
            )

        account_id = self._registry.build_account_id(phone)
        result = self._gateway.request_login_code(account_id, phone)
        if not result.success:
            return TelegramResponse.single(
                update.chat_id,
                f"I could not request a Telegram login code yet: {result.error}",
            )

        state.account_id = account_id
        state.phone = phone
        state.phone_code_hash = result.phone_code_hash
        state.step = AuthStep.WAITING_CODE
        state.last_error = ""
        state.code_attempts = 0
        state.password_attempts = 0
        state.touch()
        self._store.update(state)
        return TelegramResponse.single(
            update.chat_id,
            "Step 2 of 3: Telegram sent a login code. Reply with the code exactly as you received it.",
        )

    def _handle_code_step(self, state: PendingAuthState, update: TelegramUpdate) -> TelegramResponse:
        code = self._normalize_code(update.text)
        if not code:
            return TelegramResponse.single(
                update.chat_id,
                "I need the Telegram login code as plain text. Send the code, or /cancelauth to stop.",
            )

        assert self._gateway is not None

        result = self._gateway.sign_in_with_code(
            state.account_id,
            state.phone,
            code,
            state.phone_code_hash,
        )
        if result.password_required:
            state.step = AuthStep.WAITING_PASSWORD
            state.last_error = ""
            state.password_attempts = 0
            state.touch()
            self._store.update(state)
            return TelegramResponse.single(
                update.chat_id,
                "Step 3 of 3: this account has Telegram 2FA enabled. Reply with the account password.",
            )

        if not result.success:
            if result.error_code == "code_expired":
                return self._restart_code_step(state, update)

            state.code_attempts += 1
            state.last_error = result.error
            state.touch()
            self._store.update(state)
            return TelegramResponse.single(
                update.chat_id,
                self._build_code_retry_message(state, result.error),
            )

        self._finalize_success(state, result.user)
        return TelegramResponse.single(
            update.chat_id,
            f"Account `{state.account_id}` is now onboarded and ready for Telegram reads.",
        )

    def _handle_password_step(self, state: PendingAuthState, update: TelegramUpdate) -> TelegramResponse:
        password = update.text.strip()
        if not password:
            return TelegramResponse.single(
                update.chat_id,
                "I need the Telegram 2FA password to finish onboarding. Send the password, or /cancelauth to stop.",
            )

        assert self._gateway is not None

        result = self._gateway.sign_in_with_password(state.account_id, password)
        if not result.success:
            state.password_attempts += 1
            state.last_error = result.error
            state.touch()
            self._store.update(state)
            return TelegramResponse.single(
                update.chat_id,
                self._build_password_retry_message(state, result.error),
            )

        self._finalize_success(state, result.user)
        return TelegramResponse.single(
            update.chat_id,
            f"Account `{state.account_id}` is now onboarded and ready for Telegram reads.",
        )

    def _finalize_success(self, state: PendingAuthState, user: dict[str, object]) -> None:
        assert self._registry is not None

        record = AccountRecord(
            account_id=state.account_id,
            phone=state.phone,
            tier="standard",
            health="active",
            last_active=to_iso8601(utc_now()),
            metadata={
                **dict(user),
                "onboarded_at": to_iso8601(utc_now()),
                "auth_flow": {"method": "telegram_phone_login"},
            },
        )
        self._registry.save_account(record)
        state.step = AuthStep.COMPLETED
        state.last_error = ""
        state.touch()
        self._store.update(state)

    def _restart_code_step(self, state: PendingAuthState, update: TelegramUpdate) -> TelegramResponse:
        assert self._gateway is not None

        refreshed = self._gateway.request_login_code(state.account_id, state.phone)
        if refreshed.success:
            state.phone_code_hash = refreshed.phone_code_hash
            state.last_error = ""
            state.code_attempts = 0
            state.touch()
            self._store.update(state)
            return TelegramResponse.single(
                update.chat_id,
                "That login code expired, so I asked Telegram for a fresh one. Reply with the new code, or /cancelauth to stop.",
            )

        state.step = AuthStep.WAITING_PHONE
        state.phone_code_hash = ""
        state.last_error = refreshed.error
        state.code_attempts = 0
        state.touch()
        self._store.update(state)
        return TelegramResponse.single(
            update.chat_id,
            "That login code expired and I could not refresh it automatically. "
            "Send the phone number again to request a fresh code, or /cancelauth to stop.",
        )

    def _is_available(self) -> bool:
        return self._registry is not None and self._gateway is not None

    def _unavailable_message(self) -> str:
        return (
            "Account onboarding is not available yet. Enable the Telethon backend and configure "
            "`TELEGRAM_API_ID` plus `TELEGRAM_API_HASH` first."
        )

    def _normalize_phone(self, text: str) -> str:
        candidate = text.strip()
        if not _PHONE_PATTERN.match(candidate):
            return ""
        digits = re.sub(r"[\s\-]", "", candidate)
        return digits if digits.startswith("+") else f"+{digits}"

    def _normalize_code(self, text: str) -> str:
        candidate = text.strip().replace(" ", "")
        if not candidate:
            return ""
        match = _CODE_PATTERN.fullmatch(candidate)
        return candidate if match else ""

    def _resume_message(self, state: PendingAuthState) -> str:
        if state.step is AuthStep.WAITING_PHONE:
            return (
                "Account onboarding is already in progress.\n\n"
                "Step 1 of 3: send the phone number for the Telegram user account, including country code."
            )
        if state.step is AuthStep.WAITING_CODE:
            return (
                "Account onboarding is already in progress.\n\n"
                f"Step 2 of 3: resume the login for `{state.account_id or 'this account'}` by sending the current Telegram code, "
                "or /cancelauth to stop."
            )
        if state.step is AuthStep.WAITING_PASSWORD:
            return (
                "Account onboarding is already in progress.\n\n"
                f"Step 3 of 3: resume the login for `{state.account_id or 'this account'}` by sending the Telegram 2FA password, "
                "or /cancelauth to stop."
            )
        return "This onboarding flow is no longer active. Start a new one with /addaccount."

    def _build_code_retry_message(self, state: PendingAuthState, error: str) -> str:
        attempt_label = f"Attempt {state.code_attempts}."
        return (
            f"That code did not work yet: {error}\n\n"
            f"{attempt_label} Send the code again, or /cancelauth to stop."
        )

    def _build_password_retry_message(self, state: PendingAuthState, error: str) -> str:
        attempt_label = f"Attempt {state.password_attempts}."
        return (
            f"That password did not work yet: {error}\n\n"
            f"{attempt_label} Send the password again, or /cancelauth to stop."
        )
