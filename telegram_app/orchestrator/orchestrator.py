"""Purpose-built orchestrator that calls Claude directly via the Anthropic SDK."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import logging
import os
from pathlib import Path
import string

import anthropic

from telegram_app.capabilities import (
    AccountCapability,
    CommunityCapability,
    MembershipCapability,
    MessagingCapability,
)
from telegram_app.app_service import OrchestratorTurnHandler
from telegram_app.approvals import ApprovalManager
from telegram_app.campaigns import CampaignManager
from telegram_app.discovery import (
    parse_discovery_shortlist,
    persist_discovery_shortlist,
    should_run_discovery,
    strip_discovery_json_block,
)
from telegram_app.intake import get_campaign_brief_artifact, get_workflow_snapshot
from telegram_app.monitoring import NullRuntimeEventLogger, RuntimeEventLogger, RuntimeTraceContext
from telegram_app.models import (
    ApprovalRecord,
    ApprovalStatus,
    ScheduleRecord,
    ScheduleStatus,
    SessionRecord,
    SessionStatus,
    WorkItemPriority,
    WorkItemRecord,
    WorkItemStatus,
    WorkflowArtifact,
    WorkflowArtifactKind,
    WorkflowSnapshot,
    WorkflowStage,
)
from telegram_app.orchestrator.context_builder import build_runtime_context
from telegram_app.scheduling import ScheduleManager
from telegram_app.sessions import SessionManager
from telegram_app.transport import TelegramResponse, TelegramUpdate
from telegram_app.workflow_validation import parse_marked_json_block, validate_schedule_action
from telegram_app.work_items import WorkItemManager

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
# telegram_app/orchestrator/orchestrator.py
# parent       = telegram_app/orchestrator/
# parent.parent = telegram_app/
# parent.parent.parent = tg-swarm/  <- repo root

_APPROVAL_PHRASES = ("go ahead", "sounds good", "looks good", "let's go", "move on", "move forward")
_REJECTION_PHRASES = ("not quite", "not good", "try again", "start over", "not right")
_REVISION_REQUEST_PHRASES = (
    "search a little more",
    "search more",
    "look a little more",
    "look for more",
    "find more",
    "keep searching",
    "search a bit more",
    "adjust the criteria",
    "change the criteria",
)
_APPROVAL_WORDS = frozenset(
    {"yes", "approve", "approved", "ok", "okay", "confirmed", "confirm", "proceed", "go", "sure", "perfect", "great", "continue"}
)
_REJECTION_WORDS = frozenset({"no", "reject", "rejected", "change", "revise", "revision", "redo", "modify", "different", "nope", "nah"})
SHORTLIST_APPROVAL_CATEGORY = "community_shortlist"
STRATEGY_APPROVAL_CATEGORY = "strategy_playbook"
ACCOUNT_PLAN_APPROVAL_CATEGORY = "account_assignment_plan"
DISCOVERY_WORK_TYPE = "discovery"
STRATEGY_WORK_TYPE = "strategy"
ACCOUNT_PLANNING_WORK_TYPE = "account_planning"
WORK_TYPE_TO_STAGE = {
    DISCOVERY_WORK_TYPE: WorkflowStage.DISCOVERY,
    STRATEGY_WORK_TYPE: WorkflowStage.STRATEGY,
    ACCOUNT_PLANNING_WORK_TYPE: WorkflowStage.ACCOUNT_PLANNING,
}
STAGE_TO_WORK_TYPE = {stage: work_type for work_type, stage in WORK_TYPE_TO_STAGE.items()}
WORK_TYPE_TO_OWNER_ROLE = {
    DISCOVERY_WORK_TYPE: "discovery",
    STRATEGY_WORK_TYPE: "strategy",
    ACCOUNT_PLANNING_WORK_TYPE: "account_manager",
}
WORK_TYPE_TO_DEFAULT_GOAL = {
    DISCOVERY_WORK_TYPE: "Produce or refresh a shortlist of Telegram communities that match the current campaign brief.",
    STRATEGY_WORK_TYPE: "Turn the approved community shortlist into a campaign strategy playbook.",
    ACCOUNT_PLANNING_WORK_TYPE: "Turn the approved strategy playbook into an account assignment plan.",
}
_VALIDATED_DISCOVERY_STATES = frozenset({"live_confirmed", "search_confirmed"})
SCHEDULE_ACTION_JSON_MARKER = "SCHEDULE_ACTION_JSON"


@dataclass(slots=True)
class ScheduledExecutionOutcome:
    """Normalized outcome for one schedule-triggered specialist run."""

    result_summary: str
    metric_value: int | None = None
    related_memory_refs: list[str] = field(default_factory=list)
    status: WorkItemStatus = WorkItemStatus.REVIEW_PENDING


@dataclass(slots=True)
class SpecialistRoute:
    """Normalized work-family route for the current turn."""

    work_type: str
    work_item: WorkItemRecord | None = None
    review_pending: bool = False


def _load_prompt(name: str) -> str:
    """Load a prompt from the prompts/ directory at the repo root."""
    path = REPO_ROOT / "prompts" / name
    return path.read_text(encoding="utf-8")


def _resolve_model() -> str:
    """Resolve the Anthropic model to use, falling back to claude-sonnet-4-6."""
    model = os.getenv("DEFAULT_MODEL", "claude-sonnet-4-6").strip()
    if "/" in model:
        model = model.split("/", 1)[1]
    if not model.startswith("claude-"):
        model = "claude-sonnet-4-6"
    return model


def _build_messages(
    message_history: list[dict],
) -> list[dict]:
    """Convert the session message history to Anthropic message format."""
    if not message_history:
        return []

    history_entries = _dedupe_message_history(message_history[:-1])[-12:]
    current_entry = message_history[-1]

    messages: list[dict] = []
    for entry in history_entries:
        role = entry.get("role", "")
        content = entry.get("text") or entry.get("content", "")
        if role == "operator":
            messages.append({"role": "user", "content": content})
        elif role == "assistant":
            messages.append({"role": "assistant", "content": content})

    current_content = current_entry.get("text") or current_entry.get("content", "")
    messages.append({"role": "user", "content": current_content})
    return messages


def _dedupe_message_history(message_history: list[dict]) -> list[dict]:
    deduped: list[dict] = []
    for entry in message_history:
        if deduped and deduped[-1].get("role") == entry.get("role"):
            previous_content = deduped[-1].get("text") or deduped[-1].get("content", "")
            current_content = entry.get("text") or entry.get("content", "")
            if previous_content == current_content:
                continue
        deduped.append(entry)
    return deduped


def _classify_approval_response(text: str) -> bool | None:
    """Return True for approval, False for revision/rejection, None if ambiguous."""
    normalized = text.lower().strip().strip(".,!?")
    words = set(normalized.translate(str.maketrans("", "", string.punctuation)).split())
    contains_approval_signal = any(phrase in normalized for phrase in _APPROVAL_PHRASES) or bool(words & _APPROVAL_WORDS)
    contains_rejection_signal = any(phrase in normalized for phrase in _REJECTION_PHRASES) or bool(words & _REJECTION_WORDS)
    contains_revision_request = any(phrase in normalized for phrase in _REVISION_REQUEST_PHRASES)

    if contains_revision_request:
        return False

    if contains_approval_signal and contains_rejection_signal:
        return False

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
        community_capability: CommunityCapability | None = None,
        account_capability: AccountCapability | None = None,
        membership_capability: MembershipCapability | None = None,
        messaging_capability: MessagingCapability | None = None,
        work_item_manager: WorkItemManager | None = None,
        schedule_manager: ScheduleManager | None = None,
        campaign_manager: CampaignManager | None = None,
        monitor: RuntimeEventLogger | None = None,
        allow_live_sends: bool = True,
    ) -> None:
        self._session_manager = session_manager
        self._approval_manager = approval_manager
        self._community_capability = community_capability
        self._account_capability = account_capability
        self._membership_capability = membership_capability
        self._messaging_capability = messaging_capability
        self._work_item_manager = work_item_manager
        self._schedule_manager = schedule_manager
        self._campaign_manager = campaign_manager
        self._monitor = monitor or NullRuntimeEventLogger()
        self._allow_live_sends = allow_live_sends
        self._client = anthropic.Anthropic()

    def handle_turn(
        self,
        session: SessionRecord,
        update: TelegramUpdate,
        pending_approval: ApprovalRecord | None = None,
        trace_context: RuntimeTraceContext | None = None,
    ) -> TelegramResponse:
        """Run one orchestrator turn, routing to the appropriate specialist."""
        operator_message = update.text or ""
        if self._should_handle_schedule_authoring(operator_message):
            return self._run_orchestrator_turn(session, update, pending_approval)
        route = self._resolve_specialist_route(session, pending_approval)

        if route is not None and route.work_type == DISCOVERY_WORK_TYPE:
            if route.review_pending:
                return self._handle_discovery_review_turn(
                    session,
                    update,
                    operator_message,
                    trace_context=trace_context,
                )
            return self._run_discovery_agent(
                session,
                update,
                operator_message,
                work_item=route.work_item,
                trace_context=trace_context,
            )

        if route is not None and route.work_type == STRATEGY_WORK_TYPE:
            if route.review_pending:
                return self._handle_strategy_review_turn(
                    session,
                    update,
                    operator_message,
                    trace_context=trace_context,
                )
            return self._run_strategy_agent(
                session,
                update,
                operator_message=operator_message,
                work_item=route.work_item,
                trace_context=trace_context,
            )

        if route is not None and route.work_type == ACCOUNT_PLANNING_WORK_TYPE:
            if route.review_pending:
                return self._handle_account_plan_review_turn(session, update, operator_message)
            return self._run_account_manager_agent(
                session,
                update,
                operator_message=operator_message,
                work_item=route.work_item,
                trace_context=trace_context,
            )

        return self._run_orchestrator_turn(session, update, pending_approval)

    def _run_orchestrator_turn(
        self,
        session: SessionRecord,
        update: TelegramUpdate,
        pending_approval: ApprovalRecord | None,
    ) -> TelegramResponse:
        discovery_mode = should_run_discovery(session, pending_approval)
        active_work_items = self._list_active_work_items(session)
        active_schedules = self._list_active_schedules(session)

        orchestrator_prompt = _load_prompt("orchestrator.md")
        shared_runtime_prompt = _load_prompt("shared_runtime.md")
        runtime_context = build_runtime_context(
            session,
            pending_approval,
            active_work_items=active_work_items,
            active_schedules=active_schedules,
            discovery_mode=discovery_mode,
        )

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

        if discovery_mode and self._session_manager is not None:
            discovery_payload = parse_discovery_shortlist(final_output_text)
            if discovery_payload is not None:
                persist_discovery_shortlist(
                    session_manager=self._session_manager,
                    approval_manager=self._approval_manager,
                    session=session,
                    shortlist_payload=discovery_payload,
                )
                response_text = strip_discovery_json_block(final_output_text)
        response_text = self._apply_schedule_action_from_output(
            session,
            final_output_text=final_output_text,
            response_text=response_text,
        )

        return TelegramResponse.single(update.chat_id, response_text)

    def _run_discovery_agent(
        self,
        session: SessionRecord,
        update: TelegramUpdate,
        operator_message: str,
        work_item: WorkItemRecord | None = None,
        trace_context: RuntimeTraceContext | None = None,
    ) -> TelegramResponse:
        from agents.discovery.agent import DiscoveryAgent

        work_item = work_item or self._ensure_work_item_for_type(session, DISCOVERY_WORK_TYPE)
        agent = DiscoveryAgent(
            session_manager=self._session_manager,
            approval_manager=self._approval_manager,
            community_capability=self._community_capability,
            messaging_capability=self._messaging_capability,
            monitor=self._monitor,
        )
        operator_text, _artifact, _approval = agent.run(
            session,
            self._build_specialist_operator_message(work_item, operator_message),
            trace_context=trace_context,
        )
        self._mark_review_pending(
            session,
            work_item,
            result_summary="Community shortlist ready for operator review.",
            related_memory_refs=self._related_refs_for_session_artifact(
                session, WorkflowArtifactKind.COMMUNITY_SHORTLIST
            ),
        )
        self._append_assistant_reply(session, operator_text)
        return TelegramResponse.single(update.chat_id, operator_text)

    def _run_strategy_agent(
        self,
        session: SessionRecord,
        update: TelegramUpdate,
        operator_message: str = "",
        work_item: WorkItemRecord | None = None,
        trace_context: RuntimeTraceContext | None = None,
    ) -> TelegramResponse:
        from agents.strategy.agent import StrategyAgent

        work_item = work_item or self._ensure_work_item_for_type(session, STRATEGY_WORK_TYPE)
        agent = StrategyAgent(
            session_manager=self._session_manager,
            community_capability=self._community_capability,
            monitor=self._monitor,
        )
        operator_text, artifact = agent.run(
            session,
            operator_message=self._build_specialist_operator_message(work_item, operator_message),
            trace_context=trace_context,
        )

        if artifact is not None and self._session_manager is not None:
            self._set_workflow_stage(
                session,
                WorkflowStage.STRATEGY,
                "Strategy playbook ready for operator review.",
                data={
                    "strategy_playbook_artifact_id": artifact.artifact_id,
                    "community_count": len(artifact.data.get("communities", [])),
                },
            )
            self._mark_review_pending(
                session,
                work_item,
                result_summary="Strategy playbook ready for operator review.",
                related_memory_refs=[f"artifact:{artifact.artifact_id}"],
            )

        self._append_assistant_reply(session, operator_text)
        return TelegramResponse.single(update.chat_id, operator_text)

    def _run_account_manager_agent(
        self,
        session: SessionRecord,
        update: TelegramUpdate,
        operator_message: str = "",
        work_item: WorkItemRecord | None = None,
        trace_context: RuntimeTraceContext | None = None,
    ) -> TelegramResponse:
        from agents.account_manager.agent import AccountManagerAgent

        work_item = work_item or self._ensure_work_item_for_type(session, ACCOUNT_PLANNING_WORK_TYPE)
        agent = AccountManagerAgent(
            session_manager=self._session_manager,
            approval_manager=self._approval_manager,
            account_capability=self._account_capability,
            monitor=self._monitor,
        )
        operator_text, artifact, _approval = agent.run(
            session,
            operator_message=self._build_specialist_operator_message(work_item, operator_message),
            trace_context=trace_context,
        )
        if artifact is not None and self._session_manager is not None:
            self._set_workflow_stage(
                session,
                WorkflowStage.ACCOUNT_PLANNING,
                "Account assignment plan ready for operator review.",
                data={
                    "account_assignment_plan_artifact_id": artifact.artifact_id,
                    "community_count": len(artifact.data.get("assignments", [])),
                },
            )
            self._mark_review_pending(
                session,
                work_item,
                result_summary="Account assignment plan ready for operator review.",
                related_memory_refs=[f"artifact:{artifact.artifact_id}"],
            )
        self._append_assistant_reply(session, operator_text)
        return TelegramResponse.single(update.chat_id, operator_text)

    def _handle_discovery_review_turn(
        self,
        session: SessionRecord,
        update: TelegramUpdate,
        operator_message: str,
        trace_context: RuntimeTraceContext | None = None,
    ) -> TelegramResponse:
        decision = _classify_approval_response(operator_message)
        if decision is True:
            self._complete_stage_work_item(
                session,
                DISCOVERY_WORK_TYPE,
                "Community shortlist accepted in chat.",
            )
            self._set_workflow_stage(
                session,
                WorkflowStage.STRATEGY,
                "Community shortlist accepted in chat. Generating strategy playbook.",
            )
            return self._run_strategy_agent(session, update, trace_context=trace_context)
        if decision is False:
            self._reopen_stage_work_item(
                session,
                DISCOVERY_WORK_TYPE,
                "Refreshing the community shortlist after operator feedback.",
            )
            return self._run_discovery_agent(session, update, operator_message, trace_context=trace_context)
        return self._reply_with_stage_prompt(
            session,
            update,
            "I have a shortlist ready. Tell me what to change, or say `move to strategy` when you want me to continue.",
        )

    def _handle_strategy_review_turn(
        self,
        session: SessionRecord,
        update: TelegramUpdate,
        operator_message: str,
        trace_context: RuntimeTraceContext | None = None,
    ) -> TelegramResponse:
        decision = _classify_approval_response(operator_message)
        if decision is True:
            self._complete_stage_work_item(
                session,
                STRATEGY_WORK_TYPE,
                "Strategy playbook accepted in chat.",
            )
            self._set_workflow_stage(
                session,
                WorkflowStage.ACCOUNT_PLANNING,
                "Strategy accepted in chat. Generating the account assignment plan.",
            )
            return self._run_account_manager_agent(session, update, trace_context=trace_context)
        if decision is False:
            self._reopen_stage_work_item(
                session,
                STRATEGY_WORK_TYPE,
                "Refreshing the strategy playbook after operator feedback.",
            )
            return self._run_strategy_agent(
                session,
                update,
                operator_message=operator_message,
                trace_context=trace_context,
            )
        return self._reply_with_stage_prompt(
            session,
            update,
            "I have a strategy draft ready. Tell me what to change, or say `continue` when you want the account plan.",
        )

    def _handle_account_plan_review_turn(
        self,
        session: SessionRecord,
        update: TelegramUpdate,
        operator_message: str,
    ) -> TelegramResponse:
        decision = _classify_approval_response(operator_message)
        if decision is True:
            self._complete_stage_work_item(
                session,
                ACCOUNT_PLANNING_WORK_TYPE,
                "Account assignment plan accepted in chat.",
            )
            self._set_workflow_stage(
                session,
                WorkflowStage.COMPLETE,
                "Account assignment plan accepted in chat.",
            )
            return self._reply_with_stage_prompt(
                session,
                update,
                "The account assignment plan is approved in chat and ready for the next execution step when you want it.",
            )
        if decision is False:
            self._reopen_stage_work_item(
                session,
                ACCOUNT_PLANNING_WORK_TYPE,
                "Refreshing the account assignment plan after operator feedback.",
            )
            return self._run_account_manager_agent(
                session,
                update,
                operator_message=operator_message,
            )
        return self._reply_with_stage_prompt(
            session,
            update,
            "I have an account plan ready. Tell me what to change, or say `approve` when you want to lock it in.",
        )

    def _resolve_specialist_route(
        self,
        session: SessionRecord,
        pending_approval: ApprovalRecord | None,
    ) -> SpecialistRoute | None:
        stage = get_workflow_snapshot(session).stage
        released_stage = self._release_legacy_approval_gate(session, stage, pending_approval)
        primary_work_item = self._get_primary_work_item(session)
        if primary_work_item is not None:
            return SpecialistRoute(
                work_type=primary_work_item.work_type,
                work_item=primary_work_item,
                review_pending=primary_work_item.status is WorkItemStatus.REVIEW_PENDING,
            )
        return self._build_compatibility_route(session, released_stage)

    def _build_compatibility_route(
        self,
        session: SessionRecord,
        stage: WorkflowStage,
    ) -> SpecialistRoute | None:
        work_type = STAGE_TO_WORK_TYPE.get(stage)
        if work_type is None:
            return None

        review_pending = self._has_artifact(session, _work_type_to_artifact_kind(work_type))
        work_item = self._ensure_work_item_for_type(
            session,
            work_type,
            status=WorkItemStatus.REVIEW_PENDING if review_pending else WorkItemStatus.IN_PROGRESS,
        )
        return SpecialistRoute(
            work_type=work_type,
            work_item=work_item,
            review_pending=review_pending,
        )

    def _release_legacy_approval_gate(
        self,
        session: SessionRecord,
        stage: WorkflowStage,
        pending_approval: ApprovalRecord | None,
    ) -> WorkflowStage:
        if stage is not WorkflowStage.WAITING_FOR_APPROVAL or pending_approval is None:
            return stage

        replacement_stage = {
            SHORTLIST_APPROVAL_CATEGORY: WorkflowStage.DISCOVERY,
            STRATEGY_APPROVAL_CATEGORY: WorkflowStage.STRATEGY,
            ACCOUNT_PLAN_APPROVAL_CATEGORY: WorkflowStage.ACCOUNT_PLANNING,
        }.get(pending_approval.category, WorkflowStage.INTAKE)
        replacement_summary = {
            WorkflowStage.DISCOVERY: "Community shortlist ready for conversational review.",
            WorkflowStage.STRATEGY: "Strategy playbook ready for conversational review.",
            WorkflowStage.ACCOUNT_PLANNING: "Account assignment plan ready for conversational review.",
            WorkflowStage.INTAKE: "Workflow returned to conversational orchestration.",
        }[replacement_stage]

        if self._approval_manager is not None and pending_approval.status is ApprovalStatus.PENDING:
            self._approval_manager.resolve(
                pending_approval,
                ApprovalStatus.CANCELLED,
                note="Legacy planning approval released back into conversational review.",
            )
        session.pending_approval_id = None
        session.status = SessionStatus.ACTIVE
        self._set_workflow_stage(session, replacement_stage, replacement_summary)
        return replacement_stage

    def _has_artifact(self, session: SessionRecord, kind: WorkflowArtifactKind) -> bool:
        if self._session_manager is None:
            artifacts = session.workflow_state.get("workflow_artifacts", [])
            if not isinstance(artifacts, list):
                return False
            return any(
                isinstance(payload, dict) and payload.get("kind") == kind.value
                for payload in artifacts
            )
        return self._session_manager.get_latest_artifact_of_kind(session, kind) is not None

    def _set_workflow_stage(
        self,
        session: SessionRecord,
        stage: WorkflowStage,
        summary: str,
        *,
        data: dict[str, object] | None = None,
    ) -> None:
        if self._session_manager is None:
            return
        existing_snapshot = self._session_manager.get_workflow_snapshot(session)
        next_data = dict(existing_snapshot.data)
        next_data.update(data or {})
        if session.campaign_id:
            next_data["campaign_id"] = session.campaign_id
        if session.campaign_workspace_path:
            next_data["campaign_workspace_path"] = session.campaign_workspace_path
        primary_work_item = self._get_primary_work_item(session)
        if primary_work_item is not None:
            next_data["primary_work_item_id"] = primary_work_item.work_item_id
            next_data["primary_work_item_type"] = primary_work_item.work_type
        self._session_manager.replace_workflow_snapshot(
            session,
            WorkflowSnapshot(stage=stage, summary=summary, data=next_data),
        )
        self._session_manager.save_session(session)

    def _reply_with_stage_prompt(
        self,
        session: SessionRecord,
        update: TelegramUpdate,
        text: str,
    ) -> TelegramResponse:
        self._append_assistant_reply(session, text)
        return TelegramResponse.single(update.chat_id, text)

    def _append_assistant_reply(self, session: SessionRecord, text: str) -> None:
        """Store assistant reply in message history and persist the session."""
        message_history = session.workflow_state.setdefault("message_history", [])
        message_history.append({"role": "assistant", "content": text})
        if self._session_manager is not None:
            self._session_manager.save_session(session)

    def handle_scheduled_work(
        self,
        schedule: ScheduleRecord,
        *,
        now: datetime | None = None,
    ) -> WorkItemRecord | None:
        """Create or refresh and execute campaign work directly from a due schedule."""
        if self._work_item_manager is None or self._schedule_manager is None:
            return None
        work_item = self._work_item_manager.ensure_work_item(
            schedule.campaign_id,
            owner_role=schedule.owner_role,
            work_type=schedule.work_type,
            goal=schedule.goal,
            constraints=schedule.constraints,
            priority=schedule.priority,
            due_at=schedule.next_run_at,
            schedule_id=schedule.schedule_id,
            status=WorkItemStatus.IN_PROGRESS,
        )
        session = self._build_scheduled_session(schedule)
        if session is None:
            escalation_reason = "Scheduled work could not resolve campaign-native context."
            self._work_item_manager.update_status(
                schedule.campaign_id,
                work_item.work_item_id,
                status=WorkItemStatus.ESCALATED,
                escalation_reason=escalation_reason,
            )
            self._schedule_manager.record_outcome(
                schedule.campaign_id,
                schedule.schedule_id,
                ran_at=now,
                error=escalation_reason,
            )
            return self._work_item_manager.get(schedule.campaign_id, work_item.work_item_id)

        try:
            outcome = self._execute_scheduled_stage(session, schedule)
        except Exception as exc:
            escalation_reason = f"Scheduled {schedule.work_type} run failed: {exc}"
            self._work_item_manager.update_status(
                schedule.campaign_id,
                work_item.work_item_id,
                status=WorkItemStatus.ESCALATED,
                escalation_reason=escalation_reason,
            )
            self._schedule_manager.record_outcome(
                schedule.campaign_id,
                schedule.schedule_id,
                ran_at=now,
                error=escalation_reason,
            )
            return self._work_item_manager.get(schedule.campaign_id, work_item.work_item_id)

        self._apply_scheduled_work_outcome(schedule, work_item, outcome, ran_at=now)
        return self._work_item_manager.get(schedule.campaign_id, work_item.work_item_id)

    def _apply_scheduled_work_outcome(
        self,
        schedule: ScheduleRecord,
        work_item: WorkItemRecord,
        outcome: ScheduledExecutionOutcome,
        *,
        ran_at: datetime | None = None,
    ) -> None:
        if self._work_item_manager is None or self._schedule_manager is None:
            return

        if outcome.status is WorkItemStatus.ESCALATED:
            self._work_item_manager.update_status(
                schedule.campaign_id,
                work_item.work_item_id,
                status=WorkItemStatus.ESCALATED,
                result_summary=outcome.result_summary,
                escalation_reason=outcome.result_summary,
                related_memory_refs=outcome.related_memory_refs,
            )
        else:
            self._work_item_manager.update_status(
                schedule.campaign_id,
                work_item.work_item_id,
                status=outcome.status,
                result_summary=outcome.result_summary,
                related_memory_refs=outcome.related_memory_refs,
            )

        updated_schedule = self._schedule_manager.record_outcome(
            schedule.campaign_id,
            schedule.schedule_id,
            ran_at=ran_at,
            metric_value=outcome.metric_value,
            outcome_summary=outcome.result_summary,
        )
        if (
            updated_schedule is None
            or updated_schedule.status.value != "paused"
            or updated_schedule.pause_after_consecutive_misses is None
        ):
            return

        pause_reason = self._build_schedule_pause_reason(updated_schedule)
        self._work_item_manager.update_status(
            schedule.campaign_id,
            work_item.work_item_id,
            status=WorkItemStatus.ESCALATED,
            result_summary=outcome.result_summary,
            escalation_reason=pause_reason,
            related_memory_refs=outcome.related_memory_refs,
        )

    def _execute_scheduled_stage(
        self,
        session: SessionRecord,
        schedule: ScheduleRecord,
    ) -> ScheduledExecutionOutcome:
        if schedule.work_type == DISCOVERY_WORK_TYPE:
            return self._run_scheduled_discovery(session, schedule)
        if schedule.work_type == STRATEGY_WORK_TYPE:
            return self._run_scheduled_strategy(session, schedule)
        if schedule.work_type == ACCOUNT_PLANNING_WORK_TYPE:
            return self._run_scheduled_account_planning(session, schedule)
        return ScheduledExecutionOutcome(
            result_summary=f"Scheduled work type `{schedule.work_type}` is not yet executable.",
            status=WorkItemStatus.ESCALATED,
        )

    def _run_scheduled_discovery(
        self,
        session: SessionRecord,
        schedule: ScheduleRecord,
    ) -> ScheduledExecutionOutcome:
        from agents.discovery.agent import DiscoveryAgent

        trace_context = RuntimeTraceContext(
            trace_id=f"schedule:{schedule.schedule_id}",
            user_id=session.operator_id,
            session_id=session.session_id,
        ).with_session(session)
        agent = DiscoveryAgent(
            session_manager=None,
            approval_manager=None,
            community_capability=self._community_capability,
            messaging_capability=self._messaging_capability,
            monitor=self._monitor,
        )
        operator_text, artifact, _approval = agent.run(
            session,
            operator_message=schedule.goal,
            trace_context=trace_context,
        )
        self._append_assistant_reply(session, f"[Scheduled discovery] {operator_text}")
        if artifact is None:
            return ScheduledExecutionOutcome(
                result_summary="Scheduled discovery refresh did not persist a shortlist artifact.",
                metric_value=0,
                status=WorkItemStatus.ESCALATED,
            )
        self._persist_scheduled_artifact(
            session,
            artifact,
            stage=WorkflowStage.DISCOVERY,
            summary="Scheduled discovery shortlist ready for review.",
        )
        metric_value = self._count_validated_communities(artifact.data)
        result_summary = f"Scheduled discovery refresh updated the shortlist with {metric_value} validated communities."
        return ScheduledExecutionOutcome(
            result_summary=result_summary,
            metric_value=metric_value,
            related_memory_refs=[f"artifact:{artifact.artifact_id}"],
        )

    def _run_scheduled_strategy(
        self,
        session: SessionRecord,
        schedule: ScheduleRecord,
    ) -> ScheduledExecutionOutcome:
        from agents.strategy.agent import StrategyAgent

        trace_context = RuntimeTraceContext(
            trace_id=f"schedule:{schedule.schedule_id}",
            user_id=session.operator_id,
            session_id=session.session_id,
        ).with_session(session)
        agent = StrategyAgent(
            session_manager=None,
            community_capability=self._community_capability,
            monitor=self._monitor,
        )
        operator_text, artifact = agent.run(
            session,
            operator_message=schedule.goal,
            trace_context=trace_context,
        )
        self._append_assistant_reply(session, f"[Scheduled strategy] {operator_text}")
        if artifact is None:
            return ScheduledExecutionOutcome(
                result_summary="Scheduled strategy review did not persist a playbook artifact.",
                metric_value=0,
                status=WorkItemStatus.ESCALATED,
            )
        self._persist_scheduled_artifact(
            session,
            artifact,
            stage=WorkflowStage.STRATEGY,
            summary="Scheduled strategy playbook ready for operator review.",
        )
        return ScheduledExecutionOutcome(
            result_summary="Scheduled strategy review refreshed the playbook.",
            metric_value=1,
            related_memory_refs=[f"artifact:{artifact.artifact_id}"],
        )

    def _run_scheduled_account_planning(
        self,
        session: SessionRecord,
        schedule: ScheduleRecord,
    ) -> ScheduledExecutionOutcome:
        from agents.account_manager.agent import AccountManagerAgent

        trace_context = RuntimeTraceContext(
            trace_id=f"schedule:{schedule.schedule_id}",
            user_id=session.operator_id,
            session_id=session.session_id,
        ).with_session(session)
        agent = AccountManagerAgent(
            session_manager=None,
            approval_manager=None,
            account_capability=self._account_capability,
            monitor=self._monitor,
        )
        operator_text, artifact, _approval = agent.run(
            session,
            operator_message=schedule.goal,
            trace_context=trace_context,
        )
        self._append_assistant_reply(session, f"[Scheduled account planning] {operator_text}")
        if artifact is None:
            return ScheduledExecutionOutcome(
                result_summary="Scheduled account-planning review did not persist an assignment artifact.",
                metric_value=0,
                status=WorkItemStatus.ESCALATED,
            )
        self._persist_scheduled_artifact(
            session,
            artifact,
            stage=WorkflowStage.ACCOUNT_PLANNING,
            summary="Scheduled account assignment plan ready for operator review.",
        )
        return ScheduledExecutionOutcome(
            result_summary="Scheduled account-planning review refreshed the assignment plan.",
            metric_value=1,
            related_memory_refs=[f"artifact:{artifact.artifact_id}"],
        )

    def _build_scheduled_session(self, schedule: ScheduleRecord) -> SessionRecord | None:
        if self._campaign_manager is not None:
            return self._campaign_manager.build_background_session(
                schedule.campaign_id,
                stage=WORK_TYPE_TO_STAGE.get(schedule.work_type, WorkflowStage.DISCOVERY),
                summary=f"Scheduled {schedule.work_type} run is using campaign-native context.",
            )
        if self._session_manager is None:
            return None
        return self._session_manager.get_latest_session_for_campaign(schedule.campaign_id)

    def _persist_scheduled_artifact(
        self,
        session: SessionRecord,
        artifact: WorkflowArtifact,
        *,
        stage: WorkflowStage,
        summary: str,
    ) -> None:
        if self._campaign_manager is None or not session.campaign_id:
            return
        self._campaign_manager.persist_generated_artifact(
            session.campaign_id,
            artifact,
            stage=stage,
            summary=summary,
        )

    def _count_validated_communities(self, artifact_data: dict[str, object]) -> int:
        communities = artifact_data.get("communities", [])
        if not isinstance(communities, list):
            return 0
        return sum(
            1
            for community in communities
            if isinstance(community, dict)
            and str(community.get("verification_state", "")).strip() in _VALIDATED_DISCOVERY_STATES
        )

    def _build_schedule_pause_reason(self, schedule: ScheduleRecord) -> str:
        if schedule.evaluation_metric and schedule.minimum_value is not None:
            return (
                f"Paused schedule after {schedule.consecutive_miss_count} consecutive misses for "
                f"`{schedule.evaluation_metric}` below the minimum of {schedule.minimum_value}."
            )
        return f"Paused schedule after {schedule.consecutive_miss_count} consecutive failed runs."

    def _ensure_work_item_for_type(
        self,
        session: SessionRecord,
        work_type: str,
        *,
        status: WorkItemStatus = WorkItemStatus.IN_PROGRESS,
    ) -> WorkItemRecord | None:
        if self._work_item_manager is None or not session.campaign_id:
            return None
        owner_role = WORK_TYPE_TO_OWNER_ROLE.get(work_type)
        if owner_role is None:
            return None
        return self._work_item_manager.ensure_work_item(
            session.campaign_id,
            owner_role=owner_role,
            work_type=work_type,
            goal=self._build_stage_goal(session, work_type),
            constraints=self._build_stage_constraints(session),
            priority=WorkItemPriority.HIGH,
            related_memory_refs=self._related_refs_for_work_type(session, work_type),
            status=status,
        )

    def _mark_review_pending(
        self,
        session: SessionRecord,
        work_item: WorkItemRecord | None,
        *,
        result_summary: str,
        related_memory_refs: list[str] | None = None,
    ) -> None:
        if self._work_item_manager is None or work_item is None or not session.campaign_id:
            return
        self._work_item_manager.update_status(
            session.campaign_id,
            work_item.work_item_id,
            status=WorkItemStatus.REVIEW_PENDING,
            result_summary=result_summary,
            related_memory_refs=related_memory_refs,
        )

    def _complete_stage_work_item(
        self,
        session: SessionRecord,
        work_type: str,
        result_summary: str,
    ) -> None:
        primary_work_item = self._get_work_item_for_type(session, work_type)
        if self._work_item_manager is None or primary_work_item is None or not session.campaign_id:
            return
        self._work_item_manager.update_status(
            session.campaign_id,
            primary_work_item.work_item_id,
            status=WorkItemStatus.COMPLETED,
            result_summary=result_summary,
        )

    def _reopen_stage_work_item(
        self,
        session: SessionRecord,
        work_type: str,
        result_summary: str,
    ) -> None:
        primary_work_item = self._get_work_item_for_type(session, work_type)
        if self._work_item_manager is None or primary_work_item is None or not session.campaign_id:
            return
        self._work_item_manager.update_status(
            session.campaign_id,
            primary_work_item.work_item_id,
            status=WorkItemStatus.IN_PROGRESS,
            result_summary=result_summary,
        )

    def _get_primary_work_item(self, session: SessionRecord) -> WorkItemRecord | None:
        if self._work_item_manager is None or not session.campaign_id:
            return None
        return self._work_item_manager.get_primary_open_item(session.campaign_id)

    def _get_work_item_for_type(
        self,
        session: SessionRecord,
        work_type: str,
    ) -> WorkItemRecord | None:
        if self._work_item_manager is None or not session.campaign_id:
            return None
        matching_items = [
            work_item
            for work_item in self._work_item_manager.list_for_campaign(session.campaign_id)
            if work_item.work_type == work_type
        ]
        if not matching_items:
            return None
        return max(matching_items, key=lambda work_item: work_item.updated_at)

    def _list_active_work_items(self, session: SessionRecord) -> list[WorkItemRecord]:
        if self._work_item_manager is None or not session.campaign_id:
            return []
        return self._work_item_manager.list_open_for_campaign(session.campaign_id)

    def _list_active_schedules(self, session: SessionRecord) -> list[ScheduleRecord]:
        if self._schedule_manager is None or not session.campaign_id:
            return []
        return [
            schedule
            for schedule in self._schedule_manager.list_for_campaign(session.campaign_id)
            if schedule.status.value == "active"
        ]

    def _build_stage_goal(self, session: SessionRecord, work_type: str) -> str:
        campaign_brief = get_campaign_brief_artifact(session)
        default_goal = WORK_TYPE_TO_DEFAULT_GOAL[work_type]
        if campaign_brief is None:
            return default_goal
        objective = str(campaign_brief.data.get("objective", "")).strip()
        if not objective:
            return default_goal
        if work_type == DISCOVERY_WORK_TYPE:
            return f"{default_goal} Objective: {objective}"
        return f"{default_goal} Campaign objective: {objective}"

    def _build_stage_constraints(self, session: SessionRecord) -> list[str]:
        campaign_brief = get_campaign_brief_artifact(session)
        if campaign_brief is None:
            return []
        constraints: list[str] = []
        target_audience = str(campaign_brief.data.get("target_audience", "")).strip()
        geography = str(campaign_brief.data.get("geography", "")).strip()
        if target_audience:
            constraints.append(f"Target audience: {target_audience}")
        if geography:
            constraints.append(f"Geography: {geography}")
        raw_constraints = campaign_brief.data.get("constraints", [])
        if isinstance(raw_constraints, list):
            constraints.extend(
                str(value).strip()
                for value in raw_constraints
                if str(value).strip()
            )
        return constraints

    def _related_refs_for_work_type(
        self,
        session: SessionRecord,
        work_type: str,
    ) -> list[str]:
        refs = self._related_refs_for_session_artifact(session, WorkflowArtifactKind.CAMPAIGN_BRIEF)
        if work_type == STRATEGY_WORK_TYPE:
            refs.extend(self._related_refs_for_session_artifact(session, WorkflowArtifactKind.COMMUNITY_SHORTLIST))
        if work_type == ACCOUNT_PLANNING_WORK_TYPE:
            refs.extend(self._related_refs_for_session_artifact(session, WorkflowArtifactKind.STRATEGY_PLAYBOOK))
        return refs

    def _build_specialist_operator_message(
        self,
        work_item: WorkItemRecord | None,
        operator_message: str,
    ) -> str:
        normalized_message = operator_message.strip()
        if work_item is None:
            return normalized_message

        lines = [f"Primary work item goal: {work_item.goal}"]
        if work_item.constraints:
            lines.append("Work item constraints:")
            lines.extend(f"- {constraint}" for constraint in work_item.constraints if constraint.strip())
        if work_item.result_summary:
            lines.append(f"Current work item summary: {work_item.result_summary}")
        if normalized_message:
            lines.append(f"Operator follow-up: {normalized_message}")
        return "\n".join(lines).strip()

    def _related_refs_for_session_artifact(
        self,
        session: SessionRecord,
        kind: WorkflowArtifactKind,
    ) -> list[str]:
        if self._session_manager is None:
            return []
        artifact = self._session_manager.get_latest_artifact_of_kind(session, kind)
        if artifact is None:
            return []
        return [f"artifact:{artifact.artifact_id}"]

    def _apply_schedule_action_from_output(
        self,
        session: SessionRecord,
        *,
        final_output_text: str,
        response_text: str,
    ) -> str:
        payload = parse_marked_json_block(final_output_text, SCHEDULE_ACTION_JSON_MARKER)
        if payload is None:
            return response_text

        stripped_response = self._strip_marked_json_block(response_text, SCHEDULE_ACTION_JSON_MARKER)
        validation_error = validate_schedule_action(payload)
        if validation_error is not None:
            return self._append_runtime_note(
                stripped_response,
                "I did not save the recurring schedule because the structured schedule action was incomplete. "
                + validation_error,
            )

        summary = self._apply_schedule_action(session, payload)
        return self._append_runtime_note(stripped_response, summary)

    def _apply_schedule_action(
        self,
        session: SessionRecord,
        payload: dict[str, object],
    ) -> str:
        if self._schedule_manager is None or not session.campaign_id:
            return "Recurring schedule changes are not available in this runtime yet."

        action = str(payload.get("action", "")).strip().lower()
        schedule_payload = payload.get("schedule", {})
        if not isinstance(schedule_payload, dict):
            return "I did not save the recurring schedule because the action payload was malformed."

        if action == "create":
            return self._create_schedule_from_payload(session, schedule_payload)
        if action == "pause":
            return self._change_schedule_state(
                session,
                schedule_payload,
                status="paused",
            )
        if action == "resume":
            return self._change_schedule_state(
                session,
                schedule_payload,
                status="active",
            )
        return "I did not save the recurring schedule because the action was unsupported."

    def _create_schedule_from_payload(
        self,
        session: SessionRecord,
        schedule_payload: dict[str, object],
    ) -> str:
        if self._schedule_manager is None or not session.campaign_id:
            return "Recurring schedule creation is not available in this runtime yet."

        raw_priority = str(schedule_payload.get("priority", WorkItemPriority.MEDIUM.value)).strip().lower()
        priority = WorkItemPriority._value2member_map_.get(raw_priority, WorkItemPriority.MEDIUM)
        constraints = schedule_payload.get("constraints", [])
        schedule = self._schedule_manager.create_interval_schedule(
            session.campaign_id,
            owner_role=str(schedule_payload.get("owner_role", "")).strip(),
            work_type=str(schedule_payload.get("work_type", "")).strip(),
            goal=str(schedule_payload.get("goal", "")).strip(),
            interval_minutes=int(schedule_payload.get("interval_minutes", 0) or 0),
            constraints=[
                str(value).strip()
                for value in constraints
                if isinstance(constraints, list) and str(value).strip()
            ],
            priority=priority,
            evaluation_metric=str(schedule_payload.get("evaluation_metric", "")).strip(),
            minimum_value=_optional_int(schedule_payload.get("minimum_value")),
            pause_after_consecutive_misses=_optional_int(schedule_payload.get("pause_after_consecutive_misses")),
        )
        cadence = self._humanize_interval_minutes(schedule.interval_minutes)
        return (
            f"Saved a recurring `{schedule.work_type}` schedule for the `{schedule.owner_role}` role {cadence}. "
            f"Next run is {schedule.next_run_at.isoformat()}."
        )

    def _change_schedule_state(
        self,
        session: SessionRecord,
        schedule_payload: dict[str, object],
        *,
        status: str,
    ) -> str:
        if self._schedule_manager is None or not session.campaign_id:
            return "Recurring schedule changes are not available in this runtime yet."

        schedule = self._resolve_schedule_target(session.campaign_id, schedule_payload, status=status)
        if schedule is None:
            return "I could not find the requested recurring schedule to update."

        updated = self._schedule_manager.update_status(
            session.campaign_id,
            schedule.schedule_id,
            status=_schedule_status_from_value(status),
            reset_next_run_at=status == "active",
        )
        if updated is None:
            return "I could not update the requested recurring schedule."
        if status == "active":
            return (
                f"Resumed the recurring `{updated.work_type}` schedule. "
                f"Next run is {updated.next_run_at.isoformat()}."
            )
        return f"Paused the recurring `{updated.work_type}` schedule."

    def _resolve_schedule_target(
        self,
        campaign_id: str,
        schedule_payload: dict[str, object],
        *,
        status: str,
    ) -> ScheduleRecord | None:
        if self._schedule_manager is None:
            return None

        schedule_id = str(schedule_payload.get("schedule_id", "")).strip()
        if schedule_id:
            return self._schedule_manager.get(campaign_id, schedule_id)

        work_type = str(schedule_payload.get("work_type", "")).strip()
        owner_role = str(schedule_payload.get("owner_role", "")).strip() or None
        desired_statuses = {
            "paused": {"active"},
            "active": {"paused"},
        }[status]
        return self._schedule_manager.find_latest(
            campaign_id,
            work_type=work_type or None,
            owner_role=owner_role,
            statuses={_schedule_status_from_value(value) for value in desired_statuses},
        )

    def _append_runtime_note(self, response_text: str, note: str) -> str:
        cleaned_response = response_text.strip()
        cleaned_note = note.strip()
        if not cleaned_response:
            return cleaned_note
        return f"{cleaned_response}\n\n{cleaned_note}"

    def _strip_marked_json_block(self, output: str, marker: str) -> str:
        if marker not in output:
            return output.strip()
        operator_text, _, _ = output.partition(marker)
        return operator_text.strip()

    def _humanize_interval_minutes(self, interval_minutes: int) -> str:
        if interval_minutes % (60 * 24 * 7) == 0:
            weeks = interval_minutes // (60 * 24 * 7)
            return f"every {weeks} week{'s' if weeks != 1 else ''}"
        if interval_minutes % (60 * 24) == 0:
            days = interval_minutes // (60 * 24)
            return f"every {days} day{'s' if days != 1 else ''}"
        if interval_minutes % 60 == 0:
            hours = interval_minutes // 60
            return f"every {hours} hour{'s' if hours != 1 else ''}"
        return f"every {interval_minutes} minute{'s' if interval_minutes != 1 else ''}"

    def _should_handle_schedule_authoring(self, operator_message: str) -> bool:
        normalized = operator_message.lower().strip()
        if not normalized:
            return False

        if "pause" in normalized and ("schedule" in normalized or "weekly" in normalized or "daily" in normalized):
            return True
        if "resume" in normalized and ("schedule" in normalized or "weekly" in normalized or "daily" in normalized):
            return True

        cadence_tokens = ("daily", "weekly", "hourly", "monthly", "recurring", "every ")
        action_tokens = ("refresh", "review", "rerun", "re-run", "check", "monitor", "follow up", "follow-up")
        return any(token in normalized for token in cadence_tokens) and any(
            token in normalized for token in action_tokens
        )


def _work_type_to_artifact_kind(work_type: str) -> WorkflowArtifactKind:
    return {
        DISCOVERY_WORK_TYPE: WorkflowArtifactKind.COMMUNITY_SHORTLIST,
        STRATEGY_WORK_TYPE: WorkflowArtifactKind.STRATEGY_PLAYBOOK,
        ACCOUNT_PLANNING_WORK_TYPE: WorkflowArtifactKind.ACCOUNT_ASSIGNMENT_PLAN,
    }[work_type]


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _schedule_status_from_value(value: str):
    return ScheduleStatus._value2member_map_[value]
