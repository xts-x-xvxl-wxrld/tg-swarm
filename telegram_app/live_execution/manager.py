"""File-backed queue and lookup helpers for managed-account live execution."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
from threading import RLock
import time
from uuid import uuid4

from telegram_app.json_store import load_json_file, write_json_file
from telegram_app.live_execution.models import (
    LiveActionAttemptRecord,
    LiveActionRecord,
    LiveActionStatus,
    LiveActionType,
    utc_now,
)

DEFAULT_GUARD_STALE_SECONDS = 10.0
DEFAULT_GUARD_WAIT_SECONDS = 0.05
DEFAULT_GUARD_ATTEMPTS = 5

_QUEUED_STATUSES = frozenset({LiveActionStatus.QUEUED, LiveActionStatus.RETRY_WAIT})
_ACTIVE_STATUSES = frozenset(
    {
        LiveActionStatus.QUEUED,
        LiveActionStatus.CLAIMED,
        LiveActionStatus.RUNNING,
        LiveActionStatus.RETRY_WAIT,
    }
)


class LiveExecutionManager:
    """Persist live execution queue state under campaign-backed JSON files."""

    def __init__(self, campaigns_root: str | Path) -> None:
        self._campaigns_root = Path(campaigns_root).resolve()
        self._lock = RLock()
        self._guard_path = self._campaigns_root / ".live-execution.lock"

    def enqueue(
        self,
        campaign_id: str,
        account_id: str,
        *,
        action_type: LiveActionType,
        payload: dict[str, object],
        conversation_id: str = "",
        idempotency_key: str = "",
        action_id: str | None = None,
        source_batch_id: str = "",
        source_prepared_item_id: str = "",
        source_plan_artifact_id: str = "",
        max_retries: int = 3,
        next_attempt_at: datetime | None = None,
    ) -> LiveActionRecord:
        """Persist one new action unless the idempotency key already exists."""
        normalized_payload = dict(payload)
        normalized_campaign_id = campaign_id.strip()
        normalized_account_id = account_id.strip()
        normalized_conversation_id = conversation_id.strip()
        normalized_idempotency = idempotency_key.strip() or self.build_idempotency_key(
            normalized_campaign_id,
            normalized_account_id,
            action_type=action_type,
            conversation_id=normalized_conversation_id,
            payload=normalized_payload,
        )
        candidate = LiveActionRecord(
            action_id=(action_id or str(uuid4())).strip(),
            campaign_id=normalized_campaign_id,
            account_id=normalized_account_id,
            action_type=action_type,
            payload=normalized_payload,
            conversation_id=normalized_conversation_id,
            source_batch_id=source_batch_id.strip(),
            source_prepared_item_id=source_prepared_item_id.strip(),
            source_plan_artifact_id=source_plan_artifact_id.strip(),
            idempotency_key=normalized_idempotency,
            max_retries=max(max_retries, 0),
            next_attempt_at=next_attempt_at,
        )

        with self._lock:
            return self._with_guard(lambda: self._enqueue_locked(candidate))

    def get(self, campaign_id: str, action_id: str) -> LiveActionRecord | None:
        """Load one action by campaign and identifier."""
        if not campaign_id or not action_id:
            return None
        payload = self._load_actions_payload(campaign_id)
        raw_action = payload.get("actions", {}).get(action_id)
        if not isinstance(raw_action, dict):
            return None
        action = LiveActionRecord.from_dict(raw_action)
        return action if action.action_id else None

    def save(self, action: LiveActionRecord) -> LiveActionRecord:
        """Persist one action mutation and rebuild its campaign indexes."""
        with self._lock:
            return self._with_guard(lambda: self._save_locked(action))

    def list_for_campaign(self, campaign_id: str) -> list[LiveActionRecord]:
        """Return all actions for one campaign sorted by newest update first."""
        payload = self._load_actions_payload(campaign_id)
        raw_actions = payload.get("actions", {})
        if not isinstance(raw_actions, dict):
            return []
        actions = [
            LiveActionRecord.from_dict(item)
            for item in raw_actions.values()
            if isinstance(item, dict)
        ]
        return sorted(actions, key=lambda item: item.updated_at, reverse=True)

    def list_queued_for_campaign(self, campaign_id: str) -> list[LiveActionRecord]:
        """Return pending queued or retry-wait actions for one campaign."""
        return [
            action
            for action in self.list_for_campaign(campaign_id)
            if action.status in _QUEUED_STATUSES
        ]

    def list_queued_for_account(self, account_id: str) -> list[LiveActionRecord]:
        """Return queued or retry-wait actions for one account across campaigns."""
        normalized_account_id = account_id.strip()
        if not normalized_account_id:
            return []
        queued_actions: list[LiveActionRecord] = []
        for campaign_id in self._list_campaign_ids():
            for action in self.list_queued_for_campaign(campaign_id):
                if action.account_id == normalized_account_id:
                    queued_actions.append(action)
        return sorted(queued_actions, key=lambda item: item.updated_at, reverse=True)

    def list_active_for_conversation(self, campaign_id: str, conversation_id: str) -> list[LiveActionRecord]:
        """Return non-terminal actions linked to one conversation."""
        normalized_conversation_id = conversation_id.strip()
        if not campaign_id or not normalized_conversation_id:
            return []
        payload = self._load_indexes_payload(campaign_id)
        raw_ids = payload.get("active_by_conversation", {}).get(normalized_conversation_id, [])
        if not isinstance(raw_ids, list):
            return []
        actions = [
            self.get(campaign_id, str(action_id).strip())
            for action_id in raw_ids
        ]
        return [action for action in actions if action is not None and action.status in _ACTIVE_STATUSES]

    def find_by_idempotency_key(
        self,
        idempotency_key: str,
        *,
        campaign_id: str | None = None,
    ) -> LiveActionRecord | None:
        """Resolve one action from its persisted idempotency key."""
        normalized_key = idempotency_key.strip()
        if not normalized_key:
            return None

        campaign_ids = [campaign_id] if campaign_id else self._list_campaign_ids()
        for candidate_campaign_id in campaign_ids:
            if not candidate_campaign_id:
                continue
            payload = self._load_indexes_payload(candidate_campaign_id)
            raw_lookup = payload.get("by_idempotency_key", {})
            if not isinstance(raw_lookup, dict):
                continue
            action_id = str(raw_lookup.get(normalized_key, "")).strip()
            action = self.get(candidate_campaign_id, action_id)
            if action is not None:
                return action
        return None

    def claim_next_ready(
        self,
        *,
        owner_id: str,
        claim_ttl_seconds: int,
        now: datetime | None = None,
    ) -> LiveActionRecord | None:
        """Atomically claim the oldest ready action across campaigns."""
        current_time = now or utc_now()
        normalized_owner_id = owner_id.strip()
        if not normalized_owner_id:
            raise ValueError("owner_id is required to claim live actions.")

        with self._lock:
            return self._with_guard(
                lambda: self._claim_next_ready_locked(
                    owner_id=normalized_owner_id,
                    claim_ttl_seconds=claim_ttl_seconds,
                    now=current_time,
                )
            )

    def record_attempt(self, attempt: LiveActionAttemptRecord) -> LiveActionAttemptRecord:
        """Append one execution attempt to the campaign-local audit log."""
        payload = attempt.to_dict()
        with self._lock:
            return self._with_guard(lambda: self._record_attempt_locked(attempt.campaign_id, payload, attempt))

    def cancel_action_if_pending(
        self,
        campaign_id: str,
        action_id: str,
        *,
        reason: str,
    ) -> LiveActionRecord | None:
        """Cancel one queued action only if it has not been claimed for execution yet."""
        normalized_reason = reason.strip()
        with self._lock:
            return self._with_guard(
                lambda: self._cancel_action_if_pending_locked(
                    campaign_id,
                    action_id,
                    reason=normalized_reason,
                )
            )

    def list_attempts(self, campaign_id: str, *, action_id: str | None = None) -> list[LiveActionAttemptRecord]:
        """Return attempt records for one campaign, optionally filtered to one action."""
        path = self.attempts_path(campaign_id)
        if not path.exists():
            return []

        attempts: list[LiveActionAttemptRecord] = []
        with self._lock:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                payload = json.loads(line)
                if not isinstance(payload, dict):
                    continue
                attempt = LiveActionAttemptRecord.from_dict(payload)
                if action_id and attempt.action_id != action_id:
                    continue
                attempts.append(attempt)
        return attempts

    def actions_path(self, campaign_id: str) -> Path:
        """Return the mutable actions-state path for one campaign."""
        return self._campaign_root(campaign_id) / "live-execution" / "actions.json"

    def indexes_path(self, campaign_id: str) -> Path:
        """Return the campaign-local live execution index path."""
        return self._campaign_root(campaign_id) / "live-execution" / "indexes.json"

    def attempts_path(self, campaign_id: str) -> Path:
        """Return the append-only attempts log for one campaign."""
        return self._campaign_root(campaign_id) / "live-execution" / "attempts.jsonl"

    def build_idempotency_key(
        self,
        campaign_id: str,
        account_id: str,
        *,
        action_type: LiveActionType,
        conversation_id: str,
        payload: dict[str, object],
    ) -> str:
        """Build a stable idempotency key from the action identity and payload."""
        normalized_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        key_material = "|".join(
            [
                campaign_id.strip(),
                account_id.strip(),
                conversation_id.strip(),
                action_type.value,
                normalized_payload,
            ]
        )
        return hashlib.sha256(key_material.encode("utf-8")).hexdigest()

    def _enqueue_locked(self, candidate: LiveActionRecord) -> LiveActionRecord:
        existing = self.find_by_idempotency_key(candidate.idempotency_key, campaign_id=candidate.campaign_id)
        if existing is not None:
            return existing
        return self._save_locked(candidate)

    def _save_locked(self, action: LiveActionRecord) -> LiveActionRecord:
        payload = self._load_actions_payload(action.campaign_id)
        raw_actions = payload.setdefault("actions", {})
        if not isinstance(raw_actions, dict):
            raw_actions = {}
            payload["actions"] = raw_actions
        action.touch()
        raw_actions[action.action_id] = action.to_dict()
        payload["updated_at"] = action.updated_at.isoformat()
        self._write_actions_payload(action.campaign_id, payload)
        self._rebuild_indexes(action.campaign_id, raw_actions)
        return action

    def _claim_next_ready_locked(
        self,
        *,
        owner_id: str,
        claim_ttl_seconds: int,
        now: datetime,
    ) -> LiveActionRecord | None:
        best_campaign_id = ""
        best_action: LiveActionRecord | None = None
        best_sort_key: tuple[datetime, int, datetime, str] | None = None

        for campaign_id in self._list_campaign_ids():
            payload = self._load_actions_payload(campaign_id)
            raw_actions = payload.get("actions", {})
            if not isinstance(raw_actions, dict):
                continue

            for raw_action in raw_actions.values():
                if not isinstance(raw_action, dict):
                    continue
                action = LiveActionRecord.from_dict(raw_action)
                if not action.action_id:
                    continue
                if action.status is LiveActionStatus.CLAIMED and action.claim_expires_at and action.claim_expires_at <= now:
                    action.status = LiveActionStatus.QUEUED
                    action.claimed_by = ""
                    action.claimed_at = None
                    action.claim_expires_at = None
                    raw_actions[action.action_id] = action.to_dict()
                if not action.is_ready(now=now):
                    continue
                sort_key = (
                    action.next_attempt_at or action.created_at,
                    self._rotation_score(action),
                    action.created_at,
                    action.action_id,
                )
                if best_sort_key is None or sort_key < best_sort_key:
                    best_campaign_id = campaign_id
                    best_action = action
                    best_sort_key = sort_key

            if payload.get("actions") is raw_actions:
                payload["updated_at"] = now.isoformat()
                self._write_actions_payload(campaign_id, payload)
                self._rebuild_indexes(campaign_id, raw_actions)

        if best_action is None:
            return None

        best_action.status = LiveActionStatus.CLAIMED
        best_action.claimed_by = owner_id
        best_action.claimed_at = now
        best_action.claim_expires_at = datetime.fromtimestamp(
            now.timestamp() + max(claim_ttl_seconds, 1),
            tz=UTC,
        )
        best_action.touch()
        return self._save_locked(best_action)

    def _rotation_score(self, action: LiveActionRecord) -> int:
        key_material = "|".join(
            [
                action.account_id,
                action.action_type.value,
                action.conversation_id,
                action.action_id,
            ]
        )
        return int(hashlib.sha256(key_material.encode("utf-8")).hexdigest()[:8], 16)

    def _record_attempt_locked(
        self,
        campaign_id: str,
        payload: dict[str, object],
        attempt: LiveActionAttemptRecord,
    ) -> LiveActionAttemptRecord:
        path = self.attempts_path(campaign_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True, sort_keys=True))
            handle.write("\n")
        return attempt

    def _cancel_action_if_pending_locked(
        self,
        campaign_id: str,
        action_id: str,
        *,
        reason: str,
    ) -> LiveActionRecord | None:
        action = self.get(campaign_id, action_id)
        if action is None:
            return None
        if action.status not in _QUEUED_STATUSES:
            return None
        action.status = LiveActionStatus.CANCELLED
        action.terminal_failure_reason = reason
        action.last_result_summary = reason
        action.completed_at = utc_now()
        action.claimed_by = ""
        action.claimed_at = None
        action.claim_expires_at = None
        return self._save_locked(action)

    def _rebuild_indexes(self, campaign_id: str, raw_actions: dict[str, object]) -> None:
        by_idempotency_key: dict[str, str] = {}
        queued_by_account: dict[str, list[str]] = {}
        active_by_conversation: dict[str, list[str]] = {}

        for raw_action in raw_actions.values():
            if not isinstance(raw_action, dict):
                continue
            action = LiveActionRecord.from_dict(raw_action)
            if not action.action_id:
                continue
            if action.idempotency_key:
                by_idempotency_key[action.idempotency_key] = action.action_id
            if action.status in _QUEUED_STATUSES and action.account_id:
                queued_by_account.setdefault(action.account_id, []).append(action.action_id)
            if action.is_active() and action.conversation_id:
                active_by_conversation.setdefault(action.conversation_id, []).append(action.action_id)

        payload = {
            "by_idempotency_key": by_idempotency_key,
            "queued_by_account": queued_by_account,
            "active_by_conversation": active_by_conversation,
            "updated_at": utc_now().isoformat(),
        }
        write_json_file(self.indexes_path(campaign_id), payload)

    def _load_actions_payload(self, campaign_id: str) -> dict[str, object]:
        return load_json_file(self.actions_path(campaign_id), default={"actions": {}, "updated_at": ""})

    def _write_actions_payload(self, campaign_id: str, payload: dict[str, object]) -> None:
        write_json_file(self.actions_path(campaign_id), payload)

    def _load_indexes_payload(self, campaign_id: str) -> dict[str, object]:
        return load_json_file(
            self.indexes_path(campaign_id),
            default={
                "by_idempotency_key": {},
                "queued_by_account": {},
                "active_by_conversation": {},
                "updated_at": "",
            },
        )

    def _list_campaign_ids(self) -> list[str]:
        if not self._campaigns_root.exists():
            return []
        return sorted(
            path.name
            for path in self._campaigns_root.iterdir()
            if path.is_dir()
        )

    def _campaign_root(self, campaign_id: str) -> Path:
        return self._campaigns_root / campaign_id

    def _with_guard(self, operation):  # noqa: ANN001
        current_time = utc_now()
        if not self._acquire_guard(current_time):
            raise TimeoutError("Could not acquire the live execution state guard.")
        try:
            return operation()
        finally:
            self._release_guard()

    def _acquire_guard(self, current_time: datetime) -> bool:
        self._campaigns_root.mkdir(parents=True, exist_ok=True)
        for _attempt in range(DEFAULT_GUARD_ATTEMPTS):
            try:
                file_descriptor = os.open(self._guard_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(file_descriptor)
                return True
            except FileExistsError:
                if self._guard_is_stale(current_time):
                    self._guard_path.unlink(missing_ok=True)
                    continue
                time.sleep(DEFAULT_GUARD_WAIT_SECONDS)
        return False

    def _guard_is_stale(self, current_time: datetime) -> bool:
        if not self._guard_path.exists():
            return False
        age_seconds = current_time.timestamp() - self._guard_path.stat().st_mtime
        return age_seconds >= DEFAULT_GUARD_STALE_SECONDS

    def _release_guard(self) -> None:
        self._guard_path.unlink(missing_ok=True)
