"""Approval persistence contracts."""

from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Protocol

from telegram_app.json_store import load_json_file, write_json_file
from telegram_app.models import ApprovalRecord


class ApprovalStore(Protocol):
    """Persistence contract for approval requests."""

    def create(self, approval: ApprovalRecord) -> ApprovalRecord:
        """Persist a new approval request."""

    def get(self, approval_id: str) -> ApprovalRecord | None:
        """Fetch an approval by id."""

    def update(self, approval: ApprovalRecord) -> ApprovalRecord:
        """Persist a mutated approval."""

    def get_pending_for_session(self, session_id: str) -> ApprovalRecord | None:
        """Return the pending approval for a session, if any."""


class InMemoryApprovalStore:
    """Simple in-memory store for early approval flow development."""

    def __init__(self) -> None:
        self._approvals: dict[str, ApprovalRecord] = {}

    def create(self, approval: ApprovalRecord) -> ApprovalRecord:
        self._approvals[approval.approval_id] = approval
        return approval

    def get(self, approval_id: str) -> ApprovalRecord | None:
        return self._approvals.get(approval_id)

    def update(self, approval: ApprovalRecord) -> ApprovalRecord:
        self._approvals[approval.approval_id] = approval
        return approval

    def get_pending_for_session(self, session_id: str) -> ApprovalRecord | None:
        for approval in self._approvals.values():
            if approval.session_id == session_id and approval.resolved_at is None:
                return approval
        return None


class JsonApprovalStore:
    """File-backed approval store that preserves pending decisions across restarts."""

    def __init__(self, file_path: str | Path) -> None:
        self._file_path = Path(file_path)
        self._lock = RLock()
        self._approvals: dict[str, ApprovalRecord] = {}
        self._load()

    def create(self, approval: ApprovalRecord) -> ApprovalRecord:
        with self._lock:
            self._approvals[approval.approval_id] = approval
            self._persist()
            return approval

    def get(self, approval_id: str) -> ApprovalRecord | None:
        with self._lock:
            return self._approvals.get(approval_id)

    def update(self, approval: ApprovalRecord) -> ApprovalRecord:
        with self._lock:
            self._approvals[approval.approval_id] = approval
            self._persist()
            return approval

    def get_pending_for_session(self, session_id: str) -> ApprovalRecord | None:
        with self._lock:
            pending = [
                approval
                for approval in self._approvals.values()
                if approval.session_id == session_id and approval.resolved_at is None
            ]
        if not pending:
            return None
        return max(pending, key=lambda approval: approval.created_at)

    def _load(self) -> None:
        payload = load_json_file(
            self._file_path,
            default={"approvals": {}},
        )
        raw_approvals = payload.get("approvals", {})
        if not isinstance(raw_approvals, dict):
            raw_approvals = {}

        self._approvals = {
            approval_id: ApprovalRecord.from_dict(approval_payload)
            for approval_id, approval_payload in raw_approvals.items()
            if isinstance(approval_payload, dict)
        }

    def _persist(self) -> None:
        payload = {
            "approvals": {
                approval_id: approval.to_dict()
                for approval_id, approval in self._approvals.items()
            }
        }
        write_json_file(self._file_path, payload)
