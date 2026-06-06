"""MTProto onboarding gateway backed by the Telethon sync wrapper."""

from __future__ import annotations

import logging
import os

from telegram_app.auth.models import AuthGatewayResult

from .client import TelethonClientWrapper
from .error_classifier import classify_mtproto_exception

logger = logging.getLogger(__name__)


class TelethonAuthGateway:
    """Adapt Telethon auth operations to the onboarding manager protocol."""

    def __init__(self, client_wrapper: TelethonClientWrapper) -> None:
        self._client_wrapper = client_wrapper

    def request_login_code(self, account_id: str, phone: str) -> AuthGatewayResult:
        try:
            result = self._client_wrapper.request_login_code(account_id, phone)
        except Exception as exc:
            logger.exception(
                "Telethon request_login_code failed for %s phone=%s exc_type=%s PATH_present=%s Path_present=%s",
                account_id,
                phone,
                exc.__class__.__name__,
                "PATH" in os.environ,
                "Path" in os.environ,
            )
            error = classify_mtproto_exception(exc, action="requesting a login code")
            return AuthGatewayResult(
                success=False,
                error=error.message,
                error_code=error.code,
            )
        return AuthGatewayResult(
            success=True,
            phone_code_hash=str(result.get("phone_code_hash", "")),
        )

    def sign_in_with_code(
        self,
        account_id: str,
        phone: str,
        code: str,
        phone_code_hash: str,
    ) -> AuthGatewayResult:
        try:
            result = self._client_wrapper.sign_in_with_code(account_id, phone, code, phone_code_hash)
        except Exception as exc:
            error = classify_mtproto_exception(exc, action="signing in")
            return AuthGatewayResult(
                success=False,
                error=error.message,
                error_code=error.code,
            )

        if result.get("password_required"):
            return AuthGatewayResult(success=False, password_required=True)

        return AuthGatewayResult(
            success=bool(result.get("success")),
            user=dict(result.get("user", {})),
            error=str(result.get("error", "")),
            error_code=str(result.get("error_code", "")),
        )

    def sign_in_with_password(self, account_id: str, password: str) -> AuthGatewayResult:
        try:
            result = self._client_wrapper.sign_in_with_password(account_id, password)
        except Exception as exc:
            error = classify_mtproto_exception(exc, action="verifying the 2FA password")
            return AuthGatewayResult(
                success=False,
                error=error.message,
                error_code=error.code,
            )

        return AuthGatewayResult(
            success=bool(result.get("success")),
            user=dict(result.get("user", {})),
            error=str(result.get("error", "")),
            error_code=str(result.get("error_code", "")),
        )

    def cancel_login(self, account_id: str) -> None:
        self._client_wrapper.forget_account(account_id)
