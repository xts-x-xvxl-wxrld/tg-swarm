"""File-backed account registry for MTProto capability implementations."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from typing import Any

from telegram_app.capabilities.mtproto.warmup import (
    WarmupActionClass,
    WarmupBudgetStatus,
    build_budget_status,
    ensure_onboarded_at,
    increment_budget_usage,
    summarize_warmup,
    utc_now as warmup_utc_now,
)

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
    onboarded_at: str = ""
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
            onboarded_at=str(payload.get("onboarded_at", "")).strip(),
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
        record.onboarded_at = ensure_onboarded_at(record.onboarded_at, now=warmup_utc_now())

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
        allowed, reason, _status = self.can_perform_action(account_id, action="join")
        if not allowed:
            return False, reason
        return True, ""

    def can_send(self, account_id: str) -> tuple[bool, str]:
        """Return whether the account can send a Telegram message right now."""
        allowed, reason, _status = self.can_perform_action(account_id, action="send")
        if not allowed:
            return False, reason
        return True, ""

    def can_perform_action(
        self,
        account_id: str,
        *,
        action: str,
        now: datetime | None = None,
    ) -> tuple[bool, str, WarmupBudgetStatus | None]:
        """Return whether an account may perform one action under health, cooldown, and warmup budgets."""
        record = self.get_account(account_id)
        if record is None:
            return False, f"Unknown Telegram account: {account_id}", None

        current_time = now or utc_now()
        if record.health == "banned":
            return False, f"Telegram account {account_id} is banned.", None
        if record.health == "flagged":
            return False, f"Telegram account {account_id} is flagged and should not perform managed actions until reviewed.", None

        rate_limit_until = parse_iso8601(record.rate_limit_until)
        if rate_limit_until is not None and rate_limit_until > current_time:
            wait_seconds = int((rate_limit_until - current_time).total_seconds())
            return (
                False,
                f"Telegram account {account_id} is rate-limited for another {wait_seconds} seconds.",
                None,
            )

        action_class = self._warmup_action_class_for(action)
        if action_class is None:
            return True, "", None

        status = build_budget_status(
            record.metadata,
            onboarded_at=record.onboarded_at,
            action_class=action_class,
            now=current_time,
        )
        if action_class is WarmupActionClass.JOINS:
            self._refresh_join_window(record)
            status = build_budget_status(
                record.metadata,
                onboarded_at=record.onboarded_at,
                action_class=action_class,
                now=current_time,
            )
            if record.join_count_24h >= status.budget_limit:
                return (
                    False,
                    (
                        f"Telegram account {account_id} has reached the {status.budget_limit} joins per "
                        f"{JOIN_WINDOW_HOURS}-hour warmup limit for {status.stage_label.replace('_', ' ')}."
                    ),
                    status,
                )
        elif status.remaining_count < 1:
            return (
                False,
                (
                    f"Telegram account {account_id} reached its `{action_class.value}` warmup budget "
                    f"({status.budget_limit} actions per {JOIN_WINDOW_HOURS}-hour window on {status.stage_label.replace('_', ' ')})."
                ),
                status,
            )
        return True, "", status

    def describe_warmup(self, account_id: str, *, now: datetime | None = None) -> dict[str, object]:
        """Return a prompt-safe warmup summary for one account."""
        record = self.get_account(account_id)
        if record is None:
            return {}
        return summarize_warmup(
            record.metadata,
            onboarded_at=record.onboarded_at,
            now=now or utc_now(),
        )

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
        record.metadata = increment_budget_usage(
            record.metadata,
            onboarded_at=record.onboarded_at,
            action_class=WarmupActionClass.JOINS,
            now=now,
        )
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
        return self.mark_action_success(account_id, action="send", target=chat_id)

    def mark_action_success(
        self,
        account_id: str,
        *,
        action: str,
        target: str = "",
    ) -> AccountRecord | None:
        """Update state after a successful managed-account action."""
        record = self.get_account(account_id)
        if record is None:
            return None

        record.last_active = to_iso8601(utc_now())
        record.health = "active"
        record.rate_limit_until = ""
        action_class = self._warmup_action_class_for(action)
        if action_class is not None:
            record.metadata = increment_budget_usage(
                record.metadata,
                onboarded_at=record.onboarded_at,
                action_class=action_class,
                now=utc_now(),
            )
        self._record_action(
            record,
            action=action,
            target=target,
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
        return self.mark_action_failure(
            account_id,
            action="send",
            target=chat_id,
            health=health,
            wait_seconds=wait_seconds,
            error=error,
            outcome=outcome,
        )

    def mark_action_failure(
        self,
        account_id: str,
        *,
        action: str,
        target: str = "",
        health: str | None = None,
        wait_seconds: int | None = None,
        error: str | None = None,
        outcome: str = "failed",
    ) -> AccountRecord | None:
        """Update state after a failed managed-account action."""
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
            action=action,
            target=target,
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

    def _warmup_action_class_for(self, action: str) -> WarmupActionClass | None:
        normalized = action.strip().lower()
        if normalized in {"get_membership", "read_messages", "get_dialog_history", "list_recent_dialogs", "mark_read", "leave_dialog"}:
            return WarmupActionClass.READS
        if normalized in {"join", "join_community"}:
            return WarmupActionClass.JOINS
        if normalized == "send_group_reply":
            return WarmupActionClass.GROUP_REPLIES
        if normalized == "send_dm_reply":
            return WarmupActionClass.DM_REPLIES
        if normalized == "follow_up_reply":
            return WarmupActionClass.FOLLOW_UP_REPLIES
        if normalized in {"send", "send_message", "send_group_message"}:
            return WarmupActionClass.OUTBOUND_STARTS
        return None
