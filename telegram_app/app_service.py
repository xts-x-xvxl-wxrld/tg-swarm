"""Thin Telegram app service that routes session turns to the orchestrator."""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol
from uuid import uuid4

from telegram_app.auth import AuthManager
from telegram_app.approvals import ApprovalManager
from telegram_app.campaign_assets import CampaignAssetIntakeCoordinator
from telegram_app.campaigns import CampaignManager
from telegram_app.capabilities import AccountCapability
from telegram_app.continuous_ops import ContinuousOpsManager
from telegram_app.intake import StructuredIntakeCoordinator, get_campaign_brief_artifact
from telegram_app.monitoring import (
    NullRuntimeEventLogger,
    RuntimeEventLogger,
    RuntimeTraceContext,
    build_trace_context,
)
from telegram_app.models import ApprovalRecord, SessionRecord
from telegram_app.operator_notifications import OperatorInterventionManager
from telegram_app.sessions import SessionManager
from telegram_app.transport.telegram_responses import TelegramMessage, TelegramResponse
from telegram_app.transport.telegram_updates import TelegramUpdate


class OrchestratorTurnHandler(Protocol):
    """Interface for the orchestrator-facing turn handler."""

    def handle_turn(
        self,
        session: SessionRecord,
        update: TelegramUpdate,
        pending_approval: ApprovalRecord | None = None,
        trace_context: RuntimeTraceContext | None = None,
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
        asset_intake_coordinator: CampaignAssetIntakeCoordinator | None = None,
        auth_manager: AuthManager | None = None,
        account_capability: AccountCapability | None = None,
        campaign_manager: CampaignManager | None = None,
        intervention_manager: OperatorInterventionManager | None = None,
        continuous_ops_manager: ContinuousOpsManager | None = None,
        monitor: RuntimeEventLogger | None = None,
    ) -> None:
        self._session_manager = session_manager
        self._approval_manager = approval_manager
        self._orchestrator = orchestrator
        self._intake_coordinator = intake_coordinator or StructuredIntakeCoordinator(session_manager)
        self._asset_intake_coordinator = asset_intake_coordinator or CampaignAssetIntakeCoordinator(session_manager)
        self._auth_manager = auth_manager
        self._account_capability = account_capability
        self._campaign_manager = campaign_manager
        self._intervention_manager = intervention_manager
        self._continuous_ops_manager = continuous_ops_manager
        self._monitor = monitor or NullRuntimeEventLogger()

    @property
    def monitor(self) -> RuntimeEventLogger:
        """Expose the runtime monitor for delivery paths outside the app service."""
        return self._monitor

    def handle_update(self, update: TelegramUpdate) -> TelegramResponse:
        """Route one normalized Telegram update into the orchestrator control path."""
        trace_context = build_trace_context(str(uuid4()), update=update)
        session: SessionRecord | None = None

        self._monitor.record_event(
            component="app_service",
            event_type="turn_received",
            trace_context=trace_context,
            update=update,
            payload={"route_hint": update.command or "workflow_turn"},
        )

        try:
            if update.command == "/start":
                self._monitor.record_event(
                    component="app_service",
                    event_type="turn_routed",
                    trace_context=trace_context,
                    update=update,
                    payload={"route": "start"},
                )
                response = self._handle_start(update)
                return self._finalize_response(response, trace_context=trace_context)

            if update.command == "/addaccount" and self._auth_manager is not None:
                self._monitor.record_event(
                    component="app_service",
                    event_type="turn_routed",
                    trace_context=trace_context,
                    update=update,
                    payload={"route": "auth_start"},
                )
                response = self._auth_manager.start(update)
                return self._finalize_response(response, trace_context=trace_context)

            if update.command == "/cancelauth" and self._auth_manager is not None:
                self._monitor.record_event(
                    component="app_service",
                    event_type="turn_routed",
                    trace_context=trace_context,
                    update=update,
                    payload={"route": "auth_cancel"},
                )
                response = self._auth_manager.cancel(update)
                return self._finalize_response(response, trace_context=trace_context)

            if self._auth_manager is not None and self._auth_manager.get_active_for_operator(update.user_id) is not None:
                self._monitor.record_event(
                    component="app_service",
                    event_type="turn_routed",
                    trace_context=trace_context,
                    update=update,
                    payload={"route": "auth_continue"},
                )
                response = self._auth_manager.handle_update(update)
                return self._finalize_response(response, trace_context=trace_context)

            if update.command == "/accounts":
                self._monitor.record_event(
                    component="app_service",
                    event_type="turn_routed",
                    trace_context=trace_context,
                    update=update,
                    payload={"route": "accounts_inventory"},
                )
                response = self._handle_accounts(update)
                return self._finalize_response(response, trace_context=trace_context)

            session = self._resolve_session(update)
            self._ensure_session_campaign(session)
            update_for_turn = self._normalize_update_text(self._prepare_turn_update(update))
            intake_message = update_for_turn.text
            asset_result = self._asset_intake_coordinator.ingest_operator_update(session, update_for_turn)
            direct_asset_note = ""
            if asset_result.labeling_note and not update_for_turn.attachments:
                intake_message = ""
                direct_asset_note = asset_result.labeling_note
            if not update_for_turn.text and asset_result.operator_message:
                update_for_turn = replace(update_for_turn, text=asset_result.operator_message)
            trace_context = trace_context.with_session(session)
            starting_stage = self._session_manager.get_workflow_snapshot(session).stage.value
            trace_context = trace_context.with_stage(starting_stage)

            self._monitor.record_event(
                component="app_service",
                event_type="session_resolved",
                trace_context=trace_context,
                session=session,
                update=update_for_turn,
                payload={"started_new_session": update.command == "/new"},
            )

            if self._is_intervention_show_request(update_for_turn):
                response = self._build_intervention_report_response(update.chat_id, session)
                return self._finalize_response(response, trace_context=trace_context, session=session)

            if self._is_intervention_ack_request(update_for_turn):
                response = self._acknowledge_interventions(update.chat_id, session)
                return self._finalize_response(response, trace_context=trace_context, session=session)

            if update.command == "/new" and not update_for_turn.text and not update_for_turn.attachments:
                response = TelegramResponse.single(
                    update.chat_id,
                    "New session started. What would you like to work on?",
                )
                return self._finalize_response(response, trace_context=trace_context, session=session)

            self._session_manager.record_operator_message(session, update_for_turn.text)
            pending_approval = None
            if session.pending_approval_id is not None:
                pending_approval = self._approval_manager.get(session.pending_approval_id)
                if pending_approval is not None and pending_approval.resolved_at is not None:
                    pending_approval = None
            self._monitor.record_event(
                component="app_service",
                event_type="turn_context_loaded",
                trace_context=trace_context,
                session=session,
                approval=pending_approval,
                update=update_for_turn,
                payload={"pending_approval_present": pending_approval is not None},
            )
            if direct_asset_note:
                if self._campaign_manager is not None:
                    self._campaign_manager.sync_session_memory(session)
                self._refresh_continuous_ops(session)
                self._session_manager.save_session(session)
                response = TelegramResponse.single(update.chat_id, direct_asset_note)
                return self._finalize_response(response, trace_context=trace_context, session=session)

            intake_stage_before = self._session_manager.get_workflow_snapshot(session).stage.value
            self._intake_coordinator.ingest_operator_turn(
                session=session,
                message=intake_message,
                pending_approval=pending_approval,
                source_message_id=update_for_turn.message_id,
            )
            intake_stage_after = self._session_manager.get_workflow_snapshot(session).stage.value
            self._record_stage_transition(
                trace_context=trace_context,
                session=session,
                source="intake",
                before_stage=intake_stage_before,
                after_stage=intake_stage_after,
            )

            self._sync_session_campaign_goal(session)
            if self._campaign_manager is not None:
                self._campaign_manager.sync_session_memory(session)
            self._refresh_continuous_ops(session)
            trace_context = trace_context.with_stage(intake_stage_after)
            response = self._orchestrator.handle_turn(
                session=session,
                update=update_for_turn,
                pending_approval=pending_approval,
                trace_context=trace_context,
            )
            if self._campaign_manager is not None:
                self._campaign_manager.sync_session_memory(session)
            self._refresh_continuous_ops(session)
            self._session_manager.save_session(session)

            final_stage = self._session_manager.get_workflow_snapshot(session).stage.value
            self._record_stage_transition(
                trace_context=trace_context,
                session=session,
                source="orchestrator",
                before_stage=intake_stage_after,
                after_stage=final_stage,
            )
            return self._finalize_response(
                response,
                trace_context=trace_context.with_stage(final_stage),
                session=session,
            )
        except Exception as exc:
            self._monitor.record_event(
                component="app_service",
                event_type="turn_failed",
                trace_context=trace_context.with_session(session),
                session=session,
                update=update,
                payload={"error": str(exc), "error_type": type(exc).__name__},
            )
            raise

    def _resolve_session(self, update: TelegramUpdate) -> SessionRecord:
        """Return the active session for a turn, starting a new one when needed."""
        if update.command == "/new":
            return self._session_manager.start_session(update.user_id)

        session = self._session_manager.get_active_session(update.user_id)
        if session is not None:
            return session
        return self._session_manager.start_session(update.user_id)

    def _ensure_session_campaign(self, session: SessionRecord) -> None:
        """Backfill or create the durable campaign attached to this session."""
        if self._campaign_manager is None:
            return

        campaign = self._campaign_manager.ensure_campaign(
            session.operator_id,
            campaign_id=session.campaign_id,
            workspace_path=session.campaign_workspace_path,
        )
        if session.campaign_id == campaign.campaign_id and session.campaign_workspace_path == campaign.workspace_path:
            self._campaign_manager.hydrate_session(session)
            return

        self._session_manager.attach_campaign(
            session,
            campaign_id=campaign.campaign_id,
            campaign_workspace_path=campaign.workspace_path,
            canonical_memory_files=campaign.canonical_files,
            agent_memory_files=campaign.agent_memory_files,
        )
        self._campaign_manager.hydrate_session(session)

    def _sync_session_campaign_goal(self, session: SessionRecord) -> None:
        """Promote the current intake objective into campaign metadata."""
        if self._campaign_manager is None or not session.campaign_id:
            return

        campaign_brief = get_campaign_brief_artifact(session)
        if campaign_brief is None:
            return

        primary_goal = str(campaign_brief.data.get("objective", "")).strip()
        if not primary_goal:
            return

        self._campaign_manager.update_primary_goal(session.campaign_id, primary_goal)

    def _refresh_continuous_ops(self, session: SessionRecord) -> None:
        """Keep the campaign-owned continuous-ops summary fresh during turns."""
        if self._continuous_ops_manager is None:
            return
        self._continuous_ops_manager.refresh_for_session(session)

    def _build_intervention_report_response(
        self,
        chat_id: str,
        session: SessionRecord,
    ) -> TelegramResponse:
        """Return the current unresolved intervention summary for the attached campaign."""
        if self._intervention_manager is None or not session.campaign_id:
            return TelegramResponse.single(chat_id, "Operator intervention reporting is not available in this runtime yet.")
        self._refresh_continuous_ops(session)
        interventions = self._intervention_manager.list_open_for_campaign(
            session.campaign_id,
            include_acknowledged=True,
        )
        text = self._intervention_manager.build_alert_message(
            session.campaign_id,
            interventions,
            include_footer=False,
        )
        self._intervention_manager.mark_delivered(
            session.campaign_id,
            [intervention.intervention_id for intervention in interventions],
        )
        response = TelegramResponse.single(chat_id, text)
        response.metadata["skip_intervention_append"] = True
        return response

    def _acknowledge_interventions(
        self,
        chat_id: str,
        session: SessionRecord,
    ) -> TelegramResponse:
        """Acknowledge all currently open interventions for the attached campaign."""
        if self._intervention_manager is None or not session.campaign_id:
            return TelegramResponse.single(chat_id, "Operator intervention acknowledgements are not available in this runtime yet.")
        acknowledged = self._intervention_manager.acknowledge_all_for_campaign(session.campaign_id)
        if acknowledged < 1:
            response = TelegramResponse.single(chat_id, "There are no open operator interventions to acknowledge right now.")
            response.metadata["skip_intervention_append"] = True
            return response
        response = TelegramResponse.single(
            chat_id,
            f"Acknowledged {acknowledged} operator intervention(s). I will keep them quiet until something changes.",
        )
        response.metadata["skip_intervention_append"] = True
        return response

    def _prepare_turn_update(self, update: TelegramUpdate) -> TelegramUpdate:
        """Normalize `/new` turns so optional inline goal text becomes the message body."""
        if update.command != "/new":
            return update

        command_text, _, remainder = update.text.partition(" ")
        if command_text != "/new":
            return update

        return replace(update, text=remainder.strip(), command=None)

    def _normalize_update_text(self, update: TelegramUpdate) -> TelegramUpdate:
        """Convert common escaped newline sequences into real line breaks."""
        text = update.text
        if "\\n" not in text and "\\r\\n" not in text:
            return update

        normalized_text = text.replace("\\r\\n", "\n").replace("\\n", "\n")
        return replace(update, text=normalized_text)

    def _handle_start(self, update: TelegramUpdate) -> TelegramResponse:
        """Return the welcome message for first contact with the bot."""
        response = TelegramResponse.single(
            update.chat_id,
            "Hi. I am TelegramSwarm. Send /new to start a session, /accounts to inspect Telegram accounts, then tell me what you want to work on.",
        )
        return response

    def _handle_accounts(self, update: TelegramUpdate) -> TelegramResponse:
        """Return a read-only operational view of onboarded Telegram accounts."""
        if self._account_capability is None:
            return TelegramResponse.single(update.chat_id, "Telegram account inventory is not available in this runtime.")

        result = self._account_capability.list_accounts()
        if not result.success:
            return TelegramResponse.single(
                update.chat_id,
                f"I could not load the Telegram account inventory yet: {result.error}",
            )

        accounts = result.data.get("accounts", [])
        if not isinstance(accounts, list) or not accounts:
            return TelegramResponse.single(update.chat_id, "No Telegram accounts are onboarded yet. Use /addaccount to add one.")

        lines = ["Telegram account inventory:"]
        for account in accounts:
            if not isinstance(account, dict):
                continue
            account_id = str(account.get("account_id", "unknown"))
            health = str(account.get("health", "unknown"))
            join_count = account.get("join_count_24h", 0)
            rate_limit_until = str(account.get("rate_limit_until", "")).strip() or "none"
            last_active = str(account.get("last_active", "")).strip() or "unknown"
            warmup_day = account.get("warmup_day")
            warmup_stage = str(account.get("warmup_stage", "")).strip() or "unknown"
            metadata = account.get("metadata", {})
            recent_rate_limit = "none"
            if isinstance(metadata, dict):
                recent_rate_limit_payload = metadata.get("recent_rate_limit", {})
                if isinstance(recent_rate_limit_payload, dict):
                    recent_rate_limit = str(recent_rate_limit_payload.get("recorded_at", "")).strip() or "none"
            lines.append(
                f"- `{account_id}` | health: {health} | warmup: day {warmup_day or '?'} ({warmup_stage}) | joins24h: {join_count} | rate_limit_until: {rate_limit_until} | recent_rate_limit: {recent_rate_limit} | last_active: {last_active}"
            )
        return TelegramResponse.single(update.chat_id, "\n".join(lines))

    def _finalize_response(
        self,
        response: TelegramResponse,
        *,
        trace_context: RuntimeTraceContext,
        session: SessionRecord | None = None,
    ) -> TelegramResponse:
        response.metadata["trace_id"] = trace_context.trace_id
        if session is not None and not response.metadata.get("skip_intervention_append"):
            self._append_intervention_messages(response, session)
        if session is not None and not self._response_already_recorded(session, response):
            self._session_manager.record_app_response(session, response)
        self._monitor.record_event(
            component="app_service",
            event_type="response_prepared",
            trace_context=trace_context.with_session(session),
            session=session,
            payload={
                "chat_id": response.chat_id,
                "message_count": len(response.messages),
                "messages": [message.text for message in response.messages],
            },
        )
        return response

    def _append_intervention_messages(
        self,
        response: TelegramResponse,
        session: SessionRecord,
    ) -> None:
        """Append newly surfaced operator interventions to the outbound response."""
        if self._intervention_manager is None or not session.campaign_id:
            return

        deliverable = self._intervention_manager.list_deliverable_for_campaign(session.campaign_id)
        if not deliverable:
            return

        response.messages.append(
            TelegramMessage(
                text=self._intervention_manager.build_alert_message(
                    session.campaign_id,
                    deliverable[:3],
                )
            )
        )
        self._intervention_manager.mark_delivered(
            session.campaign_id,
            [record.intervention_id for record in deliverable[:3]],
        )

    def _record_stage_transition(
        self,
        *,
        trace_context: RuntimeTraceContext,
        session: SessionRecord,
        source: str,
        before_stage: str,
        after_stage: str,
    ) -> None:
        if before_stage == after_stage:
            return
        self._monitor.record_event(
            component="app_service",
            event_type="workflow_stage_changed",
            trace_context=trace_context.with_stage(after_stage),
            session=session,
            payload={
                "source": source,
                "before_stage": before_stage,
                "after_stage": after_stage,
            },
        )

    def _response_already_recorded(
        self,
        session: SessionRecord,
        response: TelegramResponse,
    ) -> bool:
        history = session.workflow_state.get("message_history", [])
        if not isinstance(history, list):
            return False

        assistant_messages = [message.text for message in response.messages]
        if len(history) < len(assistant_messages):
            return False

        recent_entries = history[-len(assistant_messages) :]
        for entry, message_text in zip(recent_entries, assistant_messages, strict=False):
            if not isinstance(entry, dict):
                return False
            if entry.get("role") != "assistant":
                return False
            recorded_text = entry.get("text") or entry.get("content", "")
            if recorded_text != message_text:
                return False
        return True

    def _is_intervention_show_request(self, update: TelegramUpdate) -> bool:
        if update.command == "/alerts":
            return True
        normalized = update.text.lower().strip()
        return normalized in {"alerts", "show alerts", "show alert", "show interventions"}

    def _is_intervention_ack_request(self, update: TelegramUpdate) -> bool:
        if update.command == "/ackalerts":
            return True
        normalized = update.text.lower().strip()
        return normalized in {"ack alerts", "acknowledge alerts", "dismiss alerts"}
