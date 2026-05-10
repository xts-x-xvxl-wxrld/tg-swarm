"""Purpose-built orchestrator that calls Claude directly via the Anthropic SDK."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import anthropic

from telegram_app.app_service import OrchestratorTurnHandler
from telegram_app.approvals import ApprovalManager
from telegram_app.discovery import (
    parse_discovery_shortlist,
    persist_discovery_shortlist,
    should_run_discovery,
    strip_discovery_json_block,
)
from telegram_app.intake import get_workflow_snapshot
from telegram_app.models import (
    ApprovalRecord,
    ApprovalStatus,
    SessionRecord,
    SessionStatus,
    WorkflowSnapshot,
    WorkflowStage,
)
from telegram_app.orchestrator.context_builder import build_runtime_context
from telegram_app.sessions import SessionManager
from telegram_app.transport import TelegramResponse, TelegramUpdate

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
# telegram_app/orchestrator/orchestrator.py
# parent       = telegram_app/orchestrator/
# parent.parent = telegram_app/
# parent.parent.parent = tg-swarm/  <- repo root

_APPROVAL_PHRASES = ("go ahead", "sounds good", "looks good", "let's go", "move on", "move forward")
_REJECTION_PHRASES = ("not quite", "not good", "try again", "start over", "not right")
_APPROVAL_WORDS = frozenset({"yes", "approve", "approved", "ok", "okay", "confirmed", "confirm", "proceed", "go", "sure", "perfect", "great"})
_REJECTION_WORDS = frozenset({"no", "reject", "rejected", "change", "revise", "revision", "redo", "modify", "different", "nope", "nah"})


def _load_prompt(name: str) -> str:
    """Load a prompt from the prompts/ directory at the repo root."""
    path = REPO_ROOT / "prompts" / name
    return path.read_text(encoding="utf-8")


def _resolve_model() -> str:
    """Resolve the Anthropic model to use, falling back to claude-sonnet-4-6."""
    model = os.getenv("DEFAULT_MODEL", "claude-sonnet-4-6").strip()
    # Strip provider prefix (e.g. "anthropic/claude-sonnet-4-6" -> "claude-sonnet-4-6")
    if "/" in model:
        model = model.split("/", 1)[1]
    if not model.startswith("claude-"):
        model = "claude-sonnet-4-6"
    return model


def _build_messages(
    message_history: list[dict],
) -> list[dict]:
    """Convert the session message history to Anthropic message format.

    The current message is already the last entry in message_history
    (app_service adds it before calling handle_turn). So:
    - history_entries = message_history[:-1]
    - current_entry   = message_history[-1]
    """
    if not message_history:
        return []

    history_entries = message_history[:-1]
    current_entry = message_history[-1]

    messages: list[dict] = []
    for entry in history_entries:
        role = entry.get("role", "")
        # session_manager stores 'text' key, not 'content'
        content = entry.get("text") or entry.get("content", "")
        if role == "operator":
            messages.append({"role": "user", "content": content})
        elif role == "assistant":
            messages.append({"role": "assistant", "content": content})

    # Add the current turn as the final user message
    current_content = current_entry.get("text") or current_entry.get("content", "")
    messages.append({"role": "user", "content": current_content})
    return messages


def _classify_approval_response(text: str) -> bool | None:
    """Return True for approval, False for rejection, None if ambiguous."""
    normalized = text.lower().strip().strip(".,!?")
    words = set(normalized.split())
    for phrase in _APPROVAL_PHRASES:
        if phrase in normalized:
            return True
    for phrase in _REJECTION_PHRASES:
        if phrase in normalized:
            return False
    if words & _APPROVAL_WORDS:
        return True
    if words & _REJECTION_WORDS:
        return False
    return None


class PurposeBuiltOrchestrator(OrchestratorTurnHandler):
    """Invoke Claude directly via the Anthropic SDK for one Telegram turn."""

    def __init__(
        self,
        session_manager: SessionManager | None = None,
        approval_manager: ApprovalManager | None = None,
    ) -> None:
        self._session_manager = session_manager
        self._approval_manager = approval_manager
        self._client = anthropic.Anthropic()

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def handle_turn(
        self,
        session: SessionRecord,
        update: TelegramUpdate,
        pending_approval: ApprovalRecord | None = None,
    ) -> TelegramResponse:
        """Run one orchestrator turn, routing to the appropriate specialist."""
        operator_message = update.text or ""
        snapshot = get_workflow_snapshot(session)
        stage = snapshot.stage

        # Approval interpretation takes priority when session is waiting
        if stage is WorkflowStage.WAITING_FOR_APPROVAL and pending_approval is not None:
            return self._handle_approval_response(session, update, pending_approval, operator_message)

        # Route to specialist agents
        if stage is WorkflowStage.DISCOVERY:
            return self._run_discovery_agent(session, update, operator_message)

        if stage is WorkflowStage.STRATEGY:
            return self._run_strategy_agent(session, update)

        if stage is WorkflowStage.ACCOUNT_PLANNING:
            return self._run_account_manager_agent(session, update)

        # INTAKE, COMPLETE, or unknown stages — orchestrator handles directly
        return self._run_orchestrator_turn(session, update, pending_approval)

    # ------------------------------------------------------------------
    # Direct orchestrator Claude call (INTAKE / fallback)
    # ------------------------------------------------------------------

    def _run_orchestrator_turn(
        self,
        session: SessionRecord,
        update: TelegramUpdate,
        pending_approval: ApprovalRecord | None,
    ) -> TelegramResponse:
        discovery_mode = should_run_discovery(session, pending_approval)

        orchestrator_prompt = _load_prompt("orchestrator.md")
        shared_runtime_prompt = _load_prompt("shared_runtime.md")
        runtime_context = build_runtime_context(session, pending_approval, discovery_mode=discovery_mode)

        message_history = session.workflow_state.get("message_history", [])
        messages = _build_messages(message_history)
        if not messages:
            messages = [{"role": "user", "content": update.text or ""}]

        system: list[dict] = [
            {"type": "text", "text": orchestrator_prompt},
            {"type": "text", "text": shared_runtime_prompt},
            {"type": "text", "text": runtime_context},
        ]

        model = _resolve_model()
        logger.info("Orchestrator calling Anthropic API model=%s, messages=%d", model, len(messages))

        api_response = self._client.messages.create(
            model=model,
            max_tokens=4096,
            system=system,
            messages=messages,
        )

        final_output_text = "".join(
            block.text for block in api_response.content if hasattr(block, "text")
        ).strip()

        if not final_output_text:
            logger.warning("Anthropic API turn completed without textual output.")
            final_output_text = "I finished the turn, but there was no text response to send back yet."

        message_history.append({"role": "assistant", "content": final_output_text})
        session.workflow_state["message_history"] = message_history

        response_text = final_output_text

        if discovery_mode and self._session_manager is not None and self._approval_manager is not None:
            discovery_payload = parse_discovery_shortlist(final_output_text)
            if discovery_payload is not None:
                persist_discovery_shortlist(
                    session_manager=self._session_manager,
                    approval_manager=self._approval_manager,
                    session=session,
                    shortlist_payload=discovery_payload,
                )
                response_text = strip_discovery_json_block(final_output_text)

        return TelegramResponse.single(update.chat_id, response_text)

    # ------------------------------------------------------------------
    # Specialist agent delegation helpers
    # ------------------------------------------------------------------

    def _run_discovery_agent(
        self,
        session: SessionRecord,
        update: TelegramUpdate,
        operator_message: str,
    ) -> TelegramResponse:
        from agents.discovery.agent import DiscoveryAgent

        agent = DiscoveryAgent(
            session_manager=self._session_manager,
            approval_manager=self._approval_manager,
        )
        operator_text, _artifact, _approval = agent.run(session, operator_message)
        self._append_assistant_reply(session, operator_text)
        return TelegramResponse.single(update.chat_id, operator_text)

    def _run_strategy_agent(
        self,
        session: SessionRecord,
        update: TelegramUpdate,
    ) -> TelegramResponse:
        from agents.strategy.agent import StrategyAgent

        agent = StrategyAgent(
            session_manager=self._session_manager,
            approval_manager=self._approval_manager,
        )
        operator_text, _artifact = agent.run(session)

        # Advance stage to ACCOUNT_PLANNING so the next turn routes to AccountManagerAgent
        if self._session_manager is not None:
            self._session_manager.replace_workflow_snapshot(
                session,
                WorkflowSnapshot(
                    stage=WorkflowStage.ACCOUNT_PLANNING,
                    summary="Strategy playbook produced. Ready for account assignment planning.",
                ),
            )

        self._append_assistant_reply(session, operator_text)
        return TelegramResponse.single(update.chat_id, operator_text)

    def _run_account_manager_agent(
        self,
        session: SessionRecord,
        update: TelegramUpdate,
    ) -> TelegramResponse:
        from agents.account_manager.agent import AccountManagerAgent

        agent = AccountManagerAgent(
            session_manager=self._session_manager,
            approval_manager=self._approval_manager,
        )
        operator_text, _artifact, _approval = agent.run(session)
        self._append_assistant_reply(session, operator_text)
        return TelegramResponse.single(update.chat_id, operator_text)

    # ------------------------------------------------------------------
    # Approval interpretation
    # ------------------------------------------------------------------

    def _handle_approval_response(
        self,
        session: SessionRecord,
        update: TelegramUpdate,
        pending_approval: ApprovalRecord,
        operator_message: str,
    ) -> TelegramResponse:
        """Interpret operator approval/rejection; advance or revert workflow."""
        is_approved = _classify_approval_response(operator_message)

        if is_approved is None:
            # Ambiguous message — let the orchestrator's Claude call interpret it
            return self._run_orchestrator_turn(session, update, pending_approval)

        category = pending_approval.category

        if is_approved:
            return self._handle_approved(session, update, pending_approval, category, operator_message)
        else:
            return self._handle_rejected(session, update, pending_approval, category, operator_message)

    def _handle_approved(
        self,
        session: SessionRecord,
        update: TelegramUpdate,
        pending_approval: ApprovalRecord,
        category: str,
        operator_message: str,
    ) -> TelegramResponse:
        if self._approval_manager is not None:
            self._approval_manager.resolve(pending_approval, ApprovalStatus.APPROVED, note=operator_message)
        session.pending_approval_id = None
        session.status = SessionStatus.ACTIVE

        if category == "community_shortlist":
            # Advance to STRATEGY and run strategy agent inline
            if self._session_manager is not None:
                self._session_manager.replace_workflow_snapshot(
                    session,
                    WorkflowSnapshot(
                        stage=WorkflowStage.STRATEGY,
                        summary="Community shortlist approved. Generating strategy playbook.",
                    ),
                )
                self._session_manager.save_session(session)
            return self._run_strategy_agent(session, update)

        if category == "account_assignment_plan":
            # Advance to COMPLETE
            if self._session_manager is not None:
                self._session_manager.replace_workflow_snapshot(
                    session,
                    WorkflowSnapshot(
                        stage=WorkflowStage.COMPLETE,
                        summary="Account assignment plan approved. Campaign ready for execution.",
                    ),
                )
                self._session_manager.save_session(session)
            response_text = (
                "Campaign plan approved! The account assignment plan is ready for execution. "
                "When execution capabilities are available, posting will begin according to the schedule."
            )
            self._append_assistant_reply(session, response_text)
            return TelegramResponse.single(update.chat_id, response_text)

        # Unknown category — fall back to orchestrator
        return self._run_orchestrator_turn(session, update, pending_approval)

    def _handle_rejected(
        self,
        session: SessionRecord,
        update: TelegramUpdate,
        pending_approval: ApprovalRecord,
        category: str,
        operator_message: str,
    ) -> TelegramResponse:
        if self._approval_manager is not None:
            self._approval_manager.resolve(pending_approval, ApprovalStatus.REJECTED, note=operator_message)
        session.pending_approval_id = None
        session.status = SessionStatus.ACTIVE

        if category == "community_shortlist":
            # Revert to DISCOVERY for a revised shortlist
            if self._session_manager is not None:
                self._session_manager.replace_workflow_snapshot(
                    session,
                    WorkflowSnapshot(
                        stage=WorkflowStage.DISCOVERY,
                        summary="Community shortlist rejected. Revising based on operator feedback.",
                    ),
                )
                self._session_manager.save_session(session)
            return self._run_discovery_agent(session, update, operator_message)

        if category == "account_assignment_plan":
            # Revert to ACCOUNT_PLANNING for a revised plan
            if self._session_manager is not None:
                self._session_manager.replace_workflow_snapshot(
                    session,
                    WorkflowSnapshot(
                        stage=WorkflowStage.ACCOUNT_PLANNING,
                        summary="Account assignment plan rejected. Revising based on operator feedback.",
                    ),
                )
                self._session_manager.save_session(session)
            return self._run_account_manager_agent(session, update)

        # Unknown category — fall back to orchestrator without approval context
        if self._session_manager is not None:
            self._session_manager.save_session(session)
        return self._run_orchestrator_turn(session, update, None)

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def _append_assistant_reply(self, session: SessionRecord, text: str) -> None:
        """Store assistant reply in message history and persist the session."""
        message_history = session.workflow_state.setdefault("message_history", [])
        message_history.append({"role": "assistant", "content": text})
        if self._session_manager is not None:
            self._session_manager.save_session(session)
