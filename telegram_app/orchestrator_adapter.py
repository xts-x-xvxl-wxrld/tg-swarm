"""Adapters that bridge Telegram runtime turns into the agency orchestrator."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from telegram_app.approvals import ApprovalManager
from telegram_app.app_service import OrchestratorTurnHandler
from telegram_app.discovery import (
    build_discovery_runtime_instructions,
    parse_discovery_shortlist,
    persist_discovery_shortlist,
    should_run_discovery,
    strip_discovery_json_block,
)
from telegram_app.intake import get_campaign_brief_artifact, get_workflow_snapshot
from telegram_app.models import ApprovalRecord, SessionRecord
from telegram_app.sessions import SessionManager
from telegram_app.transport import TelegramResponse, TelegramUpdate

logger = logging.getLogger(__name__)


class AgencyOrchestratorAdapter(OrchestratorTurnHandler):
    """Invoke the agency orchestrator for one Telegram turn."""

    def __init__(
        self,
        agency_factory: Callable[..., Any],
        session_manager: SessionManager | None = None,
        approval_manager: ApprovalManager | None = None,
        recipient_agent: str = "Orchestrator",
    ) -> None:
        self._agency_factory = agency_factory
        self._session_manager = session_manager
        self._approval_manager = approval_manager
        self._recipient_agent = recipient_agent

    def handle_turn(
        self,
        session: SessionRecord,
        update: TelegramUpdate,
        pending_approval: ApprovalRecord | None = None,
    ) -> TelegramResponse:
        """Run one orchestrator turn using the session's stored thread history."""
        discovery_mode = should_run_discovery(session, pending_approval)
        agency_history = self._get_agency_history(session)
        agency = self._agency_factory(load_threads_callback=lambda: agency_history)
        run_result = agency.get_response_sync(
            message=update.text,
            recipient_agent=self._recipient_agent,
            additional_instructions=self._build_runtime_instructions(
                session,
                pending_approval,
                discovery_mode=discovery_mode,
            ),
        )
        session.workflow_state["agency_history"] = run_result.to_input_list()
        final_output_text = self._extract_response_text(run_result.final_output)
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

        return TelegramResponse.single(
            update.chat_id,
            response_text,
        )

    def _get_agency_history(self, session: SessionRecord) -> list[object]:
        history = session.workflow_state.get("agency_history", [])
        if not isinstance(history, list):
            return []
        return list(history)

    def _build_runtime_instructions(
        self,
        session: SessionRecord,
        pending_approval: ApprovalRecord | None,
        discovery_mode: bool = False,
    ) -> str:
        lines = [
            "Telegram runtime context:",
            f"- session_id: {session.session_id}",
            f"- operator_id: {session.operator_id}",
            f"- session_status: {session.status}",
        ]
        workflow_snapshot = get_workflow_snapshot(session)
        lines.extend(
            [
                f"- workflow_stage: {workflow_snapshot.stage}",
                f"- workflow_summary: {workflow_snapshot.summary}",
                (
                    "- workflow_data: "
                    + json.dumps(workflow_snapshot.data, ensure_ascii=True, sort_keys=True)
                ),
            ]
        )

        campaign_brief = get_campaign_brief_artifact(session)
        if campaign_brief is not None:
            lines.extend(
                [
                    "- campaign_brief_present: true",
                    f"- campaign_brief_summary: {campaign_brief.summary}",
                    (
                        "- campaign_brief_data: "
                        + json.dumps(_compact_dict(campaign_brief.data), ensure_ascii=True, sort_keys=True)
                    ),
                ]
            )
        else:
            lines.append("- campaign_brief_present: false")

        if pending_approval is not None:
            lines.extend(
                [
                    "- pending_approval_present: true",
                    f"- pending_approval_category: {pending_approval.category}",
                    f"- pending_approval_prompt: {pending_approval.prompt}",
                    (
                        "- pending_approval_context: "
                        + json.dumps(pending_approval.context, ensure_ascii=True, sort_keys=True)
                    ),
                    (
                        "- Interpret the latest operator message in context."
                        " It may be an approval response, a clarification, or a changed request."
                    ),
                ]
            )
        else:
            lines.append("- pending_approval_present: false")

        if discovery_mode:
            discovery_instructions = build_discovery_runtime_instructions(session)
            if discovery_instructions:
                lines.append(discovery_instructions)
        return "\n".join(lines)

    def _extract_response_text(self, final_output: object) -> str:
        if isinstance(final_output, str):
            text = final_output.strip()
            if text:
                return text
        if final_output is None:
            logger.warning("Agency turn completed without textual output.")
            return "I finished the turn, but there was no text response to send back yet."
        return str(final_output)


def _compact_dict(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if value not in ("", [], {}, None)
    }
