"""File-backed account registry for MTProto capability implementations."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from typing import Any

JOIN_WINDOW_HOURS = 24
JOIN_LIMIT_PER_WINDOW = 3


def utc_now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(tz=UTC)


def to_iso8601(value: datetime | None) -> str:
    """Serialize a datetime to an ISO 8601 string."""
    if value is None:
        return ""
    return value.astimezone(UTC).isoformat()


def parse_iso8601(value: str) -> datetime | None:
    """Parse an ISO 8601 string, returning None when the field is empty."""
    if not value:
        return None
    return datetime.fromisoformat(value)


@dataclass(slots=True)
class AccountRecord:
    """Normalized Telegram account metadata used by the capability layer."""

    account_id: str
    phone: str
    tier: str = "standard"
    health: str = "active"
    join_count_24h: int = 0
    last_active: str = ""
    join_window_started_at: str = ""
    rate_limit_until: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AccountRecord":
        """Create a record from persisted JSON data."""
        return cls(
            account_id=str(payload.get("account_id", "")).strip(),
            phone=str(payload.get("phone", "")).strip(),
            tier=str(payload.get("tier", "standard")).strip() or "standard",
            health=str(payload.get("health", "active")).strip() or "active",
            join_count_24h=max(int(payload.get("join_count_24h", 0) or 0), 0),
            last_active=str(payload.get("last_active", "")).strip(),
            join_window_started_at=str(payload.get("join_window_started_at", "")).strip(),
            rate_limit_until=str(payload.get("rate_limit_until", "")).strip(),
            metadata=dict(payload.get("metadata", {}) or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert a record back to a JSON-safe payload."""
        return asdict(self)


class AccountRegistry:
    """Persist Telegram account state in a local JSON file."""

    def __init__(self, registry_path: str | Path) -> None:
        self._registry_path = Path(registry_path)
        self._ensure_registry_file()

    @property
    def path(self) -> Path:
        """Expose the resolved registry path for diagnostics."""
        return self._registry_path

    def list_accounts(self) -> list[AccountRecord]:
        """Return all known accounts in file order."""
        payload = self._read_payload()
        return [AccountRecord.from_dict(item) for item in payload.get("accounts", [])]

    def get_account(self, account_id: str) -> AccountRecord | None:
        """Return one account record by id."""
        normalized_id = account_id.strip()
        for account in self.list_accounts():
            if account.account_id == normalized_id:
                self._refresh_join_window(account)
                return account
        return None

    def find_by_phone(self, phone: str) -> AccountRecord | None:
        """Return one account record by phone number."""
        normalized_phone = phone.strip()
        for account in self.list_accounts():
            if account.phone == normalized_phone:
                self._refresh_join_window(account)
                return account
        return None

    def build_account_id(self, phone: str) -> str:
        """Generate a stable account id from a phone number."""
        digits = "".join(character for character in phone if character.isdigit())
        return f"account_{digits}"

    def save_account(self, record: AccountRecord) -> AccountRecord:
        """Create or update an account record."""
        accounts = self.list_accounts()
        self._refresh_join_window(record)

        for index, existing in enumerate(accounts):
            if existing.account_id == record.account_id:
                accounts[index] = record
                self._write_accounts(accounts)
                return record

        accounts.append(record)
        self._write_accounts(accounts)
        return record

    def resolve_default_read_account(self) -> AccountRecord | None:
        """Choose the best account for read-side Telegram operations."""
        accounts = self.list_accounts()
        if not accounts:
            return None

        active_accounts = [
            account
            for account in accounts
            if account.health not in {"banned", "rate_limited"}
        ]
        if active_accounts:
            return active_accounts[0]
        return accounts[0]

    def can_join(self, account_id: str) -> tuple[bool, str]:
        """Return whether the account can join another community right now."""
        record = self.get_account(account_id)
        if record is None:
            return False, f"Unknown Telegram account: {account_id}"

        if record.health == "banned":
            return False, f"Telegram account {account_id} is banned."
        if record.health == "flagged":
            return False, f"Telegram account {account_id} is flagged and should not join communities until reviewed."

        rate_limit_until = parse_iso8601(record.rate_limit_until)
        if rate_limit_until is not None and rate_limit_until > utc_now():
            wait_seconds = int((rate_limit_until - utc_now()).total_seconds())
            return False, f"Telegram account {account_id} is rate-limited for another {wait_seconds} seconds."

        self._refresh_join_window(record)
        if record.join_count_24h >= JOIN_LIMIT_PER_WINDOW:
            return False, (
                f"Telegram account {account_id} has reached the {JOIN_LIMIT_PER_WINDOW} joins per "
                f"{JOIN_WINDOW_HOURS}-hour limit."
            )

        return True, ""

    def can_send(self, account_id: str) -> tuple[bool, str]:
        """Return whether the account can send a Telegram message right now."""
        record = self.get_account(account_id)
        if record is None:
            return False, f"Unknown Telegram account: {account_id}"

        if record.health == "banned":
            return False, f"Telegram account {account_id} is banned."
        if record.health == "flagged":
            return False, f"Telegram account {account_id} is flagged and should not send messages until reviewed."

        rate_limit_until = parse_iso8601(record.rate_limit_until)
        if rate_limit_until is not None and rate_limit_until > utc_now():
            wait_seconds = int((rate_limit_until - utc_now()).total_seconds())
            return False, f"Telegram account {account_id} is rate-limited for another {wait_seconds} seconds."

        return True, ""

    def mark_join_success(self, account_id: str, *, community_id: str = "") -> AccountRecord | None:
        """Update pacing state after a successful join."""
        record = self.get_account(account_id)
        if record is None:
            return None

        self._refresh_join_window(record)
        now = utc_now()
        if not record.join_window_started_at:
            record.join_window_started_at = to_iso8601(now)
        record.join_count_24h += 1
        record.last_active = to_iso8601(now)
        record.health = "active"
        record.rate_limit_until = ""
        self._record_action(
            record,
            action="join",
            target=community_id,
            outcome="success",
        )
        return self.save_account(record)

    def mark_join_failure(
        self,
        account_id: str,
        *,
        community_id: str = "",
        health: str | None = None,
        wait_seconds: int | None = None,
        error: str | None = None,
        outcome: str = "failed",
    ) -> AccountRecord | None:
        """Update state after a failed join attempt."""
        record = self.get_account(account_id)
        if record is None:
            return None

        record.last_active = to_iso8601(utc_now())
        if health:
            record.health = health
        if wait_seconds is not None and wait_seconds > 0:
            record.rate_limit_until = to_iso8601(utc_now() + timedelta(seconds=wait_seconds))
        if error:
            record.metadata["last_error"] = error
        self._record_action(
            record,
            action="join",
            target=community_id,
            outcome=outcome,
            error=error,
            wait_seconds=wait_seconds,
        )
        return self.save_account(record)

    def mark_send_success(self, account_id: str, *, chat_id: str = "") -> AccountRecord | None:
        """Update state after a successful outbound Telegram send."""
        record = self.get_account(account_id)
        if record is None:
            return None

        record.last_active = to_iso8601(utc_now())
        record.health = "active"
        record.rate_limit_until = ""
        self._record_action(
            record,
            action="send",
            target=chat_id,
            outcome="success",
        )
        return self.save_account(record)

    def mark_send_failure(
        self,
        account_id: str,
        *,
        chat_id: str = "",
        health: str | None = None,
        wait_seconds: int | None = None,
        error: str | None = None,
        outcome: str = "failed",
    ) -> AccountRecord | None:
        """Update state after a failed outbound Telegram send."""
        record = self.get_account(account_id)
        if record is None:
            return None

        record.last_active = to_iso8601(utc_now())
        if health:
            record.health = health
        if wait_seconds is not None and wait_seconds > 0:
            record.rate_limit_until = to_iso8601(utc_now() + timedelta(seconds=wait_seconds))
        if error:
            record.metadata["last_error"] = error
        self._record_action(
            record,
            action="send",
            target=chat_id,
            outcome=outcome,
            error=error,
            wait_seconds=wait_seconds,
        )
        return self.save_account(record)

    def _ensure_registry_file(self) -> None:
        self._registry_path.parent.mkdir(parents=True, exist_ok=True)
        if not self._registry_path.exists():
            self._registry_path.write_text(
                json.dumps({"accounts": []}, indent=2) + "\n",
                encoding="utf-8",
            )

    def _read_payload(self) -> dict[str, Any]:
        raw = self._registry_path.read_text(encoding="utf-8").strip()
        if not raw:
            return {"accounts": []}
        payload = json.loads(raw)
        if "accounts" not in payload or not isinstance(payload["accounts"], list):
            raise ValueError(f"Invalid Telegram account registry format in {self._registry_path}")
        return payload

    def _write_accounts(self, accounts: list[AccountRecord]) -> None:
        payload = {"accounts": [account.to_dict() for account in accounts]}
        self._registry_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _refresh_join_window(self, record: AccountRecord) -> None:
        window_started_at = parse_iso8601(record.join_window_started_at)
        if window_started_at is None:
            record.join_count_24h = 0
            return

        if utc_now() - window_started_at >= timedelta(hours=JOIN_WINDOW_HOURS):
            record.join_count_24h = 0
            record.join_window_started_at = ""

    def _record_action(
        self,
        record: AccountRecord,
        *,
        action: str,
        target: str,
        outcome: str,
        error: str | None = None,
        wait_seconds: int | None = None,
    ) -> None:
        now = to_iso8601(utc_now())
        payload: dict[str, Any] = {
            "action": action,
            "target": target,
            "outcome": outcome,
            "recorded_at": now,
        }
        if error:
            payload["error"] = error
        if wait_seconds is not None and wait_seconds > 0:
            payload["wait_seconds"] = wait_seconds

        record.metadata["last_action"] = payload
        record.metadata[f"last_{action}"] = payload
        if wait_seconds is not None and wait_seconds > 0:
            record.metadata["recent_rate_limit"] = payload
