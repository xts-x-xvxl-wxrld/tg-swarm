"""Approval coordination helpers."""

from __future__ import annotations

from uuid import uuid4

from telegram_app.approvals.approval_store import ApprovalStore
from telegram_app.models import ApprovalRecord, ApprovalStatus


class ApprovalManager:
    """Coordinates approval lifecycle mutations."""

    def __init__(self, store: ApprovalStore) -> None:
        self._store = store

    def create_pending(
        self,
        session_id: str,
        category: str,
        prompt: str,
        context: dict[str, object] | None = None,
    ) -> ApprovalRecord:
        """Create and persist a pending approval request."""
        approval = ApprovalRecord(
            approval_id=str(uuid4()),
            session_id=session_id,
            category=category,
            prompt=prompt,
            context=context or {},
        )
        return self._store.create(approval)

    def get(self, approval_id: str) -> ApprovalRecord | None:
        """Fetch an approval request by id."""
        return self._store.get(approval_id)

    def get_pending_for_session(self, session_id: str) -> ApprovalRecord | None:
        """Fetch the current pending approval for a session."""
        return self._store.get_pending_for_session(session_id)

    def resolve(
        self,
        approval: ApprovalRecord,
        status: ApprovalStatus,
        note: str = "",
    ) -> ApprovalRecord:
        """Resolve and persist an approval request."""
        approval.resolve(status=status, note=note)
        return self._store.update(approval)
