"""State records for operator-driven Telegram account onboarding."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class AuthStep(StrEnum):
    """Steps in the account onboarding wizard."""

    WAITING_PHONE = "waiting_phone"
    WAITING_CODE = "waiting_code"
    WAITING_PASSWORD = "waiting_password"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        """Return whether this step ends the active auth flow."""
        return self in {self.COMPLETED, self.CANCELLED, self.FAILED}


@dataclass(slots=True)
class PendingAuthState:
    """Durable onboarding state for one operator."""

    auth_id: str
    operator_id: str
    chat_id: str
    step: AuthStep = AuthStep.WAITING_PHONE
    account_id: str = ""
    phone: str = ""
    phone_code_hash: str = ""
    last_error: str = ""
    code_attempts: int = 0
    password_attempts: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def touch(self) -> None:
        """Refresh the update timestamp."""
        self.updated_at = datetime.now(UTC)

    def to_dict(self) -> dict[str, str]:
        """Serialize the auth state for JSON persistence."""
        return {
            "auth_id": self.auth_id,
            "operator_id": self.operator_id,
            "chat_id": self.chat_id,
            "step": self.step.value,
            "account_id": self.account_id,
            "phone": self.phone,
            "phone_code_hash": self.phone_code_hash,
            "last_error": self.last_error,
            "code_attempts": str(self.code_attempts),
            "password_attempts": str(self.password_attempts),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, str] | None) -> "PendingAuthState":
        """Hydrate auth state from JSON persistence."""
        payload = payload or {}
        raw_step = payload.get("step", AuthStep.WAITING_PHONE.value)
        step = AuthStep._value2member_map_.get(raw_step, AuthStep.WAITING_PHONE)
        return cls(
            auth_id=str(payload.get("auth_id", "")),
            operator_id=str(payload.get("operator_id", "")),
            chat_id=str(payload.get("chat_id", "")),
            step=step,
            account_id=str(payload.get("account_id", "")),
            phone=str(payload.get("phone", "")),
            phone_code_hash=str(payload.get("phone_code_hash", "")),
            last_error=str(payload.get("last_error", "")),
            code_attempts=max(int(payload.get("code_attempts", 0) or 0), 0),
            password_attempts=max(int(payload.get("password_attempts", 0) or 0), 0),
            created_at=datetime.fromisoformat(payload["created_at"])
            if payload.get("created_at")
            else datetime.now(UTC),
            updated_at=datetime.fromisoformat(payload["updated_at"])
            if payload.get("updated_at")
            else datetime.now(UTC),
        )


@dataclass(slots=True)
class AuthGatewayResult:
    """Structured result returned by the MTProto auth gateway."""

    success: bool
    phone_code_hash: str = ""
    password_required: bool = False
    error: str = ""
    error_code: str = ""
    user: dict[str, object] = field(default_factory=dict)
