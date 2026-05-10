"""Session coordination helpers."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import uuid4

from telegram_app.models import (
    SessionRecord,
    SessionStatus,
    WorkflowArtifact,
    WorkflowArtifactKind,
    WorkflowSnapshot,
    WorkflowStage,
)
from telegram_app.sessions.session_store import SessionStore
from telegram_app.transport.telegram_responses import TelegramResponse

AGENCY_HISTORY_KEY = "agency_history"
MESSAGE_HISTORY_KEY = "message_history"
WORKFLOW_SNAPSHOT_KEY = "workflow_snapshot"
WORKFLOW_ARTIFACTS_KEY = "workflow_artifacts"


class SessionManager:
    """Coordinates session lifecycle mutations."""

    def __init__(self, store: SessionStore) -> None:
        self._store = store

    def start_session(self, operator_id: str) -> SessionRecord:
        """Create and persist a fresh operator session."""
        session = SessionRecord(
            session_id=str(uuid4()),
            operator_id=operator_id,
            status=SessionStatus.NEW,
            workflow_state={
                AGENCY_HISTORY_KEY: [],
                MESSAGE_HISTORY_KEY: [],
                WORKFLOW_SNAPSHOT_KEY: WorkflowSnapshot(
                    stage=WorkflowStage.INTAKE,
                    summary="Waiting for the operator to describe the goal.",
                ).to_dict(),
                WORKFLOW_ARTIFACTS_KEY: [],
            },
        )
        return self._store.create(session)

    def get_active_session(self, operator_id: str) -> SessionRecord | None:
        """Fetch the active session for an operator."""
        return self._store.get_active_for_operator(operator_id)

    def record_operator_message(self, session: SessionRecord, message: str) -> SessionRecord:
        """Persist the latest operator message and mark the session active."""
        session.latest_operator_message = message
        session.status = SessionStatus.ACTIVE
        self._append_message_history(session, role="operator", text=message)
        session.touch()
        return self._store.update(session)

    def record_app_response(self, session: SessionRecord, response: TelegramResponse) -> SessionRecord:
        """Persist the outbound app response text for session continuity."""
        for message in response.messages:
            self._append_message_history(session, role="assistant", text=message.text)
        session.touch()
        return self._store.update(session)

    def get_agency_history(self, session: SessionRecord) -> list[object]:
        """Return the stored Agency Swarm input history for a session."""
        history = session.workflow_state.get(AGENCY_HISTORY_KEY, [])
        if not isinstance(history, list):
            return []
        return list(history)

    def replace_agency_history(
        self,
        session: SessionRecord,
        history: Sequence[object],
    ) -> SessionRecord:
        """Replace the stored Agency Swarm input history for a session."""
        session.workflow_state[AGENCY_HISTORY_KEY] = list(history)
        session.touch()
        return self._store.update(session)

    def save_session(self, session: SessionRecord) -> SessionRecord:
        """Persist in-place session mutations performed elsewhere in the runtime."""
        session.touch()
        return self._store.update(session)

    def mark_pending_approval(self, session: SessionRecord, approval_id: str) -> SessionRecord:
        """Attach a pending approval to a session."""
        session.pending_approval_id = approval_id
        session.status = SessionStatus.PENDING_APPROVAL
        session.workflow_state[WORKFLOW_SNAPSHOT_KEY] = WorkflowSnapshot(
            stage=WorkflowStage.WAITING_FOR_APPROVAL,
            summary="Waiting for operator approval before continuing.",
            data={"pending_approval_id": approval_id},
        ).to_dict()
        session.touch()
        return self._store.update(session)

    def get_workflow_snapshot(self, session: SessionRecord) -> WorkflowSnapshot:
        """Return the persisted workflow snapshot for the session."""
        payload = session.workflow_state.get(WORKFLOW_SNAPSHOT_KEY, {})
        if not isinstance(payload, dict):
            payload = {}
        return WorkflowSnapshot.from_dict(payload)

    def replace_workflow_snapshot(
        self,
        session: SessionRecord,
        snapshot: WorkflowSnapshot,
    ) -> SessionRecord:
        """Persist the latest workflow snapshot for the session."""
        session.workflow_state[WORKFLOW_SNAPSHOT_KEY] = snapshot.to_dict()
        session.touch()
        return self._store.update(session)

    def list_workflow_artifacts(self, session: SessionRecord) -> list[WorkflowArtifact]:
        """Return the structured workflow artifacts saved for the session."""
        payloads = self._get_workflow_artifact_payloads(session)
        return [WorkflowArtifact.from_dict(payload) for payload in payloads]

    def save_workflow_artifact(
        self,
        session: SessionRecord,
        artifact: WorkflowArtifact,
    ) -> SessionRecord:
        """Insert or replace a structured workflow artifact within a session."""
        artifact.touch()
        payloads = self._get_workflow_artifact_payloads(session)
        artifact_payload = artifact.to_dict()

        for index, payload in enumerate(payloads):
            if payload.get("artifact_id") == artifact.artifact_id:
                payloads[index] = artifact_payload
                break
        else:
            payloads.append(artifact_payload)

        session.workflow_state[WORKFLOW_ARTIFACTS_KEY] = payloads
        session.touch()
        return self._store.update(session)

    def create_workflow_artifact(
        self,
        session: SessionRecord,
        kind: WorkflowArtifactKind,
        title: str,
        summary: str = "",
        data: dict[str, object] | None = None,
    ) -> WorkflowArtifact:
        """Create and persist a new workflow artifact for a session."""
        artifact = WorkflowArtifact(
            artifact_id=str(uuid4()),
            kind=kind,
            title=title,
            summary=summary,
            data=dict(data or {}),
        )
        self.save_workflow_artifact(session, artifact)
        return artifact

    def _append_message_history(self, session: SessionRecord, role: str, text: str) -> None:
        history = session.workflow_state.setdefault(MESSAGE_HISTORY_KEY, [])
        if not isinstance(history, list):
            history = []
            session.workflow_state[MESSAGE_HISTORY_KEY] = history
        history.append({"role": role, "text": text})

    def _get_workflow_artifact_payloads(self, session: SessionRecord) -> list[dict[str, object]]:
        payloads = session.workflow_state.setdefault(WORKFLOW_ARTIFACTS_KEY, [])
        if not isinstance(payloads, list):
            payloads = []
            session.workflow_state[WORKFLOW_ARTIFACTS_KEY] = payloads
        return [dict(payload) for payload in payloads if isinstance(payload, dict)]
