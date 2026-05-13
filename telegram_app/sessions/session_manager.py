"""Session coordination helpers."""

from __future__ import annotations

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

    def list_sessions_for_campaign(self, campaign_id: str) -> list[SessionRecord]:
        """Return all sessions attached to a campaign, newest first."""
        sessions = self._store.list_for_campaign(campaign_id)
        return sorted(sessions, key=lambda session: session.updated_at, reverse=True)

    def get_latest_session_for_campaign(self, campaign_id: str) -> SessionRecord | None:
        """Return the most recently updated session attached to a campaign."""
        sessions = self.list_sessions_for_campaign(campaign_id)
        return sessions[0] if sessions else None

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

    def attach_campaign(
        self,
        session: SessionRecord,
        campaign_id: str,
        campaign_workspace_path: str,
        *,
        canonical_memory_files: list[str] | None = None,
        agent_memory_files: list[str] | None = None,
    ) -> SessionRecord:
        """Attach a durable campaign reference to a session."""
        session.campaign_id = campaign_id
        session.campaign_workspace_path = campaign_workspace_path
        if canonical_memory_files is not None:
            session.canonical_memory_files = list(canonical_memory_files)
        if agent_memory_files is not None:
            session.agent_memory_files = list(agent_memory_files)
        session.linked_entity_ids["campaign_id"] = campaign_id
        session.linked_entity_ids["campaign_workspace_path"] = campaign_workspace_path

        snapshot = self.get_workflow_snapshot(session)
        snapshot.data["campaign_id"] = campaign_id
        snapshot.data["campaign_workspace_path"] = campaign_workspace_path
        session.workflow_state[WORKFLOW_SNAPSHOT_KEY] = snapshot.to_dict()

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

    def get_latest_artifact_of_kind(
        self,
        session: SessionRecord,
        kind: WorkflowArtifactKind,
    ) -> WorkflowArtifact | None:
        """Return the most recently updated artifact of the given kind, or None."""
        artifacts = [a for a in self.list_workflow_artifacts(session) if a.kind is kind]
        if not artifacts:
            return None
        return max(artifacts, key=lambda a: a.updated_at)

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
