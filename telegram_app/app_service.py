"""Thin Telegram app service that routes session turns to the orchestrator."""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from telegram_app.approvals import ApprovalManager
from telegram_app.intake import StructuredIntakeCoordinator
from telegram_app.models import ApprovalRecord, SessionRecord
from telegram_app.sessions import SessionManager
from telegram_app.transport.telegram_responses import TelegramResponse
from telegram_app.transport.telegram_updates import TelegramUpdate


class OrchestratorTurnHandler(Protocol):
    """Interface for the orchestrator-facing turn handler."""

    def handle_turn(
        self,
        session: SessionRecord,
        update: TelegramUpdate,
        pending_approval: ApprovalRecord | None = None,
    ) -> TelegramResponse:
        """Handle one operator turn and return outbound Telegram messages."""


class TelegramAppService:
    """Transport/session adapter that keeps orchestration decisions out of the runtime."""

    def __init__(
        self,
        session_manager: SessionManager,
        approval_manager: ApprovalManager,
        orchestrator: OrchestratorTurnHandler,
        intake_coordinator: StructuredIntakeCoordinator | None = None,
    ) -> None:
        self._session_manager = session_manager
        self._approval_manager = approval_manager
        self._orchestrator = orchestrator
        self._intake_coordinator = intake_coordinator or StructuredIntakeCoordinator(session_manager)

    def handle_update(self, update: TelegramUpdate) -> TelegramResponse:
        """Route one normalized Telegram update into the orchestrator control path."""
        if update.command == "/start":
            return self._handle_start(update)

        session = self._resolve_session(update)
        update_for_turn = self._prepare_turn_update(update)

        if update.command == "/new" and not update_for_turn.text:
            response = TelegramResponse.single(
                update.chat_id,
                "New session started. What would you like to work on?",
            )
            self._session_manager.record_app_response(session, response)
            return response

        self._session_manager.record_operator_message(session, update_for_turn.text)
        pending_approval = self._approval_manager.get_pending_for_session(session.session_id)
        self._intake_coordinator.ingest_operator_turn(
            session=session,
            message=update_for_turn.text,
            pending_approval=pending_approval,
        )
        response = self._orchestrator.handle_turn(
            session=session,
            update=update_for_turn,
            pending_approval=pending_approval,
        )
        self._session_manager.save_session(session)
        self._session_manager.record_app_response(session, response)
        return response

    def _resolve_session(self, update: TelegramUpdate) -> SessionRecord:
        """Return the active session for a turn, starting a new one when needed."""
        if update.command == "/new":
            return self._session_manager.start_session(update.user_id)

        session = self._session_manager.get_active_session(update.user_id)
        if session is not None:
            return session
        return self._session_manager.start_session(update.user_id)

    def _prepare_turn_update(self, update: TelegramUpdate) -> TelegramUpdate:
        """Normalize `/new` turns so optional inline goal text becomes the message body."""
        if update.command != "/new":
            return update

        command_text, _, remainder = update.text.partition(" ")
        if command_text != "/new":
            return update

        return replace(update, text=remainder.strip(), command=None)

    def _handle_start(self, update: TelegramUpdate) -> TelegramResponse:
        """Return the welcome message for first contact with the bot."""
        response = TelegramResponse.single(
            update.chat_id,
            "Hi. I am TelegramSwarm. Send /new to start a session, then tell me what you want to work on.",
        )
        return response
