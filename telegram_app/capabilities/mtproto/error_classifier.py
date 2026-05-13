"""Normalize Telethon exceptions into stable runtime error details."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class MtprotoErrorDetails:
    """Structured classification for a Telethon failure."""

    code: str
    message: str
    health: str | None = None
    wait_seconds: int | None = None
    retriable: bool = False
    already_satisfied: bool = False


_TRANSIENT_ERROR_NAMES = {
    "OSError",
    "RpcCallFailError",
    "ServerError",
    "TimeoutError",
}

_BANNED_ERROR_NAMES = {
    "AuthKeyUnregisteredError",
    "PhoneNumberBannedError",
    "UserDeactivatedBanError",
}

_FLAGGED_ERROR_NAMES = {
    "PeerFloodError",
    "UserBannedInChannelError",
}


def classify_mtproto_exception(exc: Exception, *, action: str) -> MtprotoErrorDetails:
    """Map a Telethon exception to a stable capability/runtime shape."""
    class_name = exc.__class__.__name__
    wait_seconds = int(getattr(exc, "seconds", 0) or 0)

    if class_name == "PhoneCodeExpiredError":
        return MtprotoErrorDetails(
            code="code_expired",
            message="The Telegram login code expired. Request a fresh code and try again.",
        )
    if class_name == "PhoneCodeInvalidError":
        return MtprotoErrorDetails(
            code="code_invalid",
            message="That Telegram login code was invalid.",
        )
    if class_name == "PasswordHashInvalidError":
        return MtprotoErrorDetails(
            code="password_invalid",
            message="That Telegram 2FA password was invalid.",
        )
    if class_name == "PhoneNumberInvalidError":
        return MtprotoErrorDetails(
            code="phone_invalid",
            message="That Telegram phone number was invalid.",
        )
    if class_name == "SessionPasswordNeededError":
        return MtprotoErrorDetails(
            code="password_required",
            message="Telegram requires a 2FA password for this account.",
        )
    if class_name in {"FloodWaitError", "SlowModeWaitError"}:
        return MtprotoErrorDetails(
            code="rate_limited",
            message=f"Telegram asked this account to wait {wait_seconds} seconds before {action} can continue.",
            health="rate_limited",
            wait_seconds=wait_seconds,
        )
    if class_name == "UserAlreadyParticipantError":
        return MtprotoErrorDetails(
            code="already_member",
            message="This account is already a member of that community.",
            already_satisfied=True,
        )
    if class_name == "ChatWriteForbiddenError":
        return MtprotoErrorDetails(
            code="write_forbidden",
            message="This account is not allowed to post in that chat.",
            health="flagged",
        )
    if class_name == "ChannelPrivateError":
        return MtprotoErrorDetails(
            code="community_private",
            message="That community is private or inaccessible to this account.",
        )
    if class_name == "InviteRequestSentError":
        return MtprotoErrorDetails(
            code="join_request_sent",
            message="Telegram accepted the join request, but the community still requires approval.",
        )
    if class_name in _BANNED_ERROR_NAMES:
        return MtprotoErrorDetails(
            code="account_banned",
            message="Telegram rejected the account because it appears banned or deactivated.",
            health="banned",
        )
    if class_name in _FLAGGED_ERROR_NAMES:
        return MtprotoErrorDetails(
            code="account_flagged",
            message="Telegram flagged this account for the requested action.",
            health="flagged",
        )
    if class_name in _TRANSIENT_ERROR_NAMES:
        return MtprotoErrorDetails(
            code="transient_error",
            message=f"Telegram {action} failed with a transient error: {exc}",
            retriable=True,
        )

    return MtprotoErrorDetails(
        code="unexpected_error",
        message=f"Telegram {action} failed: {exc}",
    )

