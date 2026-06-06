"""Durable account-scoped policy posture for live engagement."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Any

from telegram_app.json_store import load_json_file, write_json_file


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized or normalized.lower() in {"none", "null"}:
        return None
    return datetime.fromisoformat(normalized)


@dataclass(slots=True)
class AccountPolicyState:
    """Account-scoped cooldown and pause posture shared across campaigns."""

    account_id: str
    is_paused: bool = False
    pause_reason: str = ""
    cooldown_until: datetime | None = None
    cooldown_reason: str = ""
    last_rate_limit_at: datetime | None = None
    recent_rate_limit_count: int = 0
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)

    def touch(self) -> None:
        self.updated_at = _utc_now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "cooldown_reason": self.cooldown_reason,
            "cooldown_until": self.cooldown_until.isoformat() if self.cooldown_until else "",
            "created_at": self.created_at.isoformat(),
            "is_paused": self.is_paused,
            "last_rate_limit_at": self.last_rate_limit_at.isoformat() if self.last_rate_limit_at else "",
            "pause_reason": self.pause_reason,
            "recent_rate_limit_count": self.recent_rate_limit_count,
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "AccountPolicyState":
        payload = payload or {}
        return cls(
            account_id=str(payload.get("account_id", "")).strip(),
            is_paused=bool(payload.get("is_paused", False)),
            pause_reason=str(payload.get("pause_reason", "")).strip(),
            cooldown_until=_parse_datetime(str(payload.get("cooldown_until", "")).strip()),
            cooldown_reason=str(payload.get("cooldown_reason", "")).strip(),
            last_rate_limit_at=_parse_datetime(str(payload.get("last_rate_limit_at", "")).strip()),
            recent_rate_limit_count=max(int(payload.get("recent_rate_limit_count", 0) or 0), 0),
            created_at=_parse_datetime(str(payload.get("created_at", "")).strip()) or _utc_now(),
            updated_at=_parse_datetime(str(payload.get("updated_at", "")).strip()) or _utc_now(),
        )


@dataclass(slots=True)
class CommunityPolicyState:
    """Campaign-scoped moderation posture for one community path."""

    campaign_id: str
    chat_id: str
    community_id: str = ""
    is_paused: bool = False
    pause_reason: str = ""
    last_write_forbidden_at: datetime | None = None
    recent_write_forbidden_count: int = 0
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)

    def touch(self) -> None:
        self.updated_at = _utc_now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "chat_id": self.chat_id,
            "community_id": self.community_id,
            "created_at": self.created_at.isoformat(),
            "is_paused": self.is_paused,
            "last_write_forbidden_at": (
                self.last_write_forbidden_at.isoformat() if self.last_write_forbidden_at else ""
            ),
            "pause_reason": self.pause_reason,
            "recent_write_forbidden_count": self.recent_write_forbidden_count,
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "CommunityPolicyState":
        payload = payload or {}
        return cls(
            campaign_id=str(payload.get("campaign_id", "")).strip(),
            chat_id=str(payload.get("chat_id", "")).strip(),
            community_id=str(payload.get("community_id", "")).strip(),
            is_paused=bool(payload.get("is_paused", False)),
            pause_reason=str(payload.get("pause_reason", "")).strip(),
            last_write_forbidden_at=_parse_datetime(str(payload.get("last_write_forbidden_at", "")).strip()),
            recent_write_forbidden_count=max(int(payload.get("recent_write_forbidden_count", 0) or 0), 0),
            created_at=_parse_datetime(str(payload.get("created_at", "")).strip()) or _utc_now(),
            updated_at=_parse_datetime(str(payload.get("updated_at", "")).strip()) or _utc_now(),
        )


class LiveExecutionPolicyStateManager:
    """Persist minimal account and community policy posture outside conversation records."""

    def __init__(self, data_root: str | Path) -> None:
        self._data_root = Path(data_root).resolve()
        self._lock = RLock()

    def get_account_state(self, account_id: str) -> AccountPolicyState | None:
        if not account_id.strip():
            return None
        payload = self._load_payload()
        raw_state = payload.get("accounts", {}).get(account_id.strip())
        if not isinstance(raw_state, dict):
            return None
        state = AccountPolicyState.from_dict(raw_state)
        return state if state.account_id else None

    def get_community_state(self, campaign_id: str, chat_id: str) -> CommunityPolicyState | None:
        campaign_key = campaign_id.strip()
        chat_key = chat_id.strip()
        if not campaign_key or not chat_key:
            return None
        payload = self._load_payload()
        raw_state = payload.get("communities", {}).get(self._community_key(campaign_key, chat_key))
        if not isinstance(raw_state, dict):
            return None
        state = CommunityPolicyState.from_dict(raw_state)
        return state if state.campaign_id and state.chat_id else None

    def pause_account(self, account_id: str, *, reason: str) -> AccountPolicyState:
        with self._lock:
            state = self._get_or_create_account_state(account_id)
            state.is_paused = True
            state.pause_reason = reason.strip()
            return self._save_account_state(state)

    def resume_account(self, account_id: str) -> AccountPolicyState:
        with self._lock:
            state = self._get_or_create_account_state(account_id)
            state.is_paused = False
            state.pause_reason = ""
            return self._save_account_state(state)

    def record_account_rate_limit(
        self,
        account_id: str,
        *,
        wait_seconds: int,
        reason: str,
        now: datetime | None = None,
    ) -> AccountPolicyState:
        with self._lock:
            state = self._get_or_create_account_state(account_id)
            current_time = now or _utc_now()
            state.cooldown_until = current_time + timedelta(seconds=max(wait_seconds, 1))
            state.cooldown_reason = reason.strip()
            state.last_rate_limit_at = current_time
            state.recent_rate_limit_count += 1
            return self._save_account_state(state)

    def clear_account_cooldown(self, account_id: str) -> AccountPolicyState:
        with self._lock:
            state = self._get_or_create_account_state(account_id)
            state.cooldown_until = None
            state.cooldown_reason = ""
            return self._save_account_state(state)

    def pause_community(
        self,
        campaign_id: str,
        chat_id: str,
        *,
        reason: str,
        community_id: str = "",
    ) -> CommunityPolicyState:
        with self._lock:
            state = self._get_or_create_community_state(campaign_id, chat_id, community_id=community_id)
            state.is_paused = True
            state.pause_reason = reason.strip()
            if community_id.strip():
                state.community_id = community_id.strip()
            return self._save_community_state(state)

    def resume_community(self, campaign_id: str, chat_id: str) -> CommunityPolicyState:
        with self._lock:
            state = self._get_or_create_community_state(campaign_id, chat_id)
            state.is_paused = False
            state.pause_reason = ""
            return self._save_community_state(state)

    def record_community_write_friction(
        self,
        campaign_id: str,
        chat_id: str,
        *,
        reason: str,
        community_id: str = "",
        now: datetime | None = None,
        pause_threshold: int = 2,
    ) -> CommunityPolicyState:
        with self._lock:
            state = self._get_or_create_community_state(campaign_id, chat_id, community_id=community_id)
            current_time = now or _utc_now()
            state.last_write_forbidden_at = current_time
            state.recent_write_forbidden_count += 1
            if community_id.strip():
                state.community_id = community_id.strip()
            if state.recent_write_forbidden_count >= max(pause_threshold, 1):
                state.is_paused = True
                state.pause_reason = reason.strip()
            return self._save_community_state(state)

    def path(self) -> Path:
        return self._data_root / "live-engagement-policy" / "state.json"

    def _get_or_create_account_state(self, account_id: str) -> AccountPolicyState:
        existing = self.get_account_state(account_id)
        if existing is not None:
            return existing
        return AccountPolicyState(account_id=account_id.strip())

    def _get_or_create_community_state(
        self,
        campaign_id: str,
        chat_id: str,
        *,
        community_id: str = "",
    ) -> CommunityPolicyState:
        existing = self.get_community_state(campaign_id, chat_id)
        if existing is not None:
            return existing
        return CommunityPolicyState(
            campaign_id=campaign_id.strip(),
            chat_id=chat_id.strip(),
            community_id=community_id.strip(),
        )

    def _save_account_state(self, state: AccountPolicyState) -> AccountPolicyState:
        payload = self._load_payload()
        raw_accounts = payload.setdefault("accounts", {})
        if not isinstance(raw_accounts, dict):
            raw_accounts = {}
            payload["accounts"] = raw_accounts
        state.touch()
        raw_accounts[state.account_id] = state.to_dict()
        payload["updated_at"] = state.updated_at.isoformat()
        self._write_payload(payload)
        return state

    def _save_community_state(self, state: CommunityPolicyState) -> CommunityPolicyState:
        payload = self._load_payload()
        raw_communities = payload.setdefault("communities", {})
        if not isinstance(raw_communities, dict):
            raw_communities = {}
            payload["communities"] = raw_communities
        state.touch()
        raw_communities[self._community_key(state.campaign_id, state.chat_id)] = state.to_dict()
        payload["updated_at"] = state.updated_at.isoformat()
        self._write_payload(payload)
        return state

    def _load_payload(self) -> dict[str, Any]:
        return load_json_file(
            self.path(),
            default={"accounts": {}, "communities": {}, "updated_at": ""},
        )

    def _write_payload(self, payload: dict[str, Any]) -> None:
        write_json_file(self.path(), payload)

    def _community_key(self, campaign_id: str, chat_id: str) -> str:
        return "|".join([campaign_id.strip(), chat_id.strip()])
