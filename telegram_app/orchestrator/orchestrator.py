"""Purpose-built orchestrator that calls Claude directly via the Anthropic SDK."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import logging
from pathlib import Path
import string

import anthropic

from telegram_app.agent_runtime import AgentRuntimeBroker
from telegram_app.campaign_memory.operational_notes import NEXT_ACTIONS_DESTINATION
from telegram_app.campaign_context import (
    CAMPAIGN_CONTEXT_TITLE,
    build_campaign_context_summary,
    get_campaign_context_artifact,
    merge_campaign_context_data,
    promote_campaign_context_revision,
    resolve_campaign_context_revision,
)
from telegram_app.campaign_setup import get_campaign_setup_state, setup_is_confirmed
from telegram_app.campaign_signals import (
    OBSERVATION_OWNER_ROLE,
    OBSERVATION_WORK_TYPE,
    CampaignSignalRecord,
    CampaignSignalManager,
    ObservationOperatorAttention,
    ObservationRecommendedNextStep,
    ObservationReviewResult,
    ObservationSuggestedWorkItemChange,
    ObservationWorkItemChangeAction,
    ObservationWorkItemType,
    ObservationWorkRefresher,
)
from telegram_app.capabilities import (
    AccountCapability,
    CommunityCapability,
    MembershipCapability,
    MessagingCapability,
)
from telegram_app.compiled_intents import (
    CompiledIntentApplicator,
    CompiledIntentApplicationError,
    CompiledIntentStatus,
    CompiledIntentStore,
    compile_campaign_context_update,
    compile_live_ops_intents,
    compile_memory_note,
    compile_output_proposals,
    compile_prepared_execution_invalidation,
    compile_review_request,
    compile_schedule_action,
    compile_specialist_proposals,
    compile_work_intent,
    validate_compiled_intent,
)
from telegram_app.app_service import OrchestratorTurnHandler
from telegram_app.approvals import ApprovalManager
from telegram_app.campaigns import CampaignManager
from telegram_app.continuous_ops import ContinuousOpsManager
from telegram_app.discovery import (
    parse_discovery_shortlist,
    persist_discovery_shortlist,
    should_run_discovery,
    strip_discovery_json_block,
)
from telegram_app.intake import get_campaign_brief_artifact, get_workflow_snapshot
from telegram_app.llm import TelegramCapabilityToolbox, resolve_model
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
from telegram_app.orchestrator.reasoning_surfaces import reasoning_surface_for_work_type
from telegram_app.prepared_execution import PreparedExecutionService
from telegram_app.live_ops import LiveOpsIntentKind, LiveOpsService
from telegram_app.scheduling import ScheduleManager
from telegram_app.sessions import SessionManager
from telegram_app.transport import TelegramResponse, TelegramUpdate
from telegram_app.workflow_validation import (
    OUTPUT_PROPOSALS_JSON_MARKER,
    parse_output_proposal_list,
    strip_marked_block,
    validate_schedule_action,
)
from telegram_app.work_items import WorkItemManager

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
# telegram_app/orchestrator/orchestrator.py
# parent       = telegram_app/orchestrator/
# parent.parent = telegram_app/
# parent.parent.parent = tg-swarm/  <- repo root

_APPROVAL_PHRASES = ("go ahead", "sounds good", "looks good", "let's go", "move on", "move forward")
_REJECTION_PHRASES = ("not quite", "not good", "try again", "start over", "not right")
_ACTIVATION_PHRASES = ("start execution", "launch execution", "activate plan", "activate execution")
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
_REVISION_FEEDBACK_PHRASES = _REVISION_REQUEST_PHRASES + (
    "tighten",
    "loosen",
    "adjust",
    "change",
    "revise",
    "refresh",
    "update",
    "remove",
    "add",
    "avoid",
    "keep",
    "focus on",
    "lean into",
    "make it",
    "make this",
    "less ",
    "more ",
)
_APPROVAL_WORDS = frozenset(
    {"yes", "approve", "approved", "ok", "okay", "confirmed", "confirm", "proceed", "sure", "continue"}
)
_REJECTION_WORDS = frozenset({"no", "reject", "rejected", "revise", "revision", "redo", "modify", "different", "nope", "nah"})
SHORTLIST_APPROVAL_CATEGORY = "community_shortlist"
STRATEGY_APPROVAL_CATEGORY = "strategy_playbook"
ACCOUNT_PLAN_APPROVAL_CATEGORY = "account_assignment_plan"
DISCOVERY_WORK_TYPE = "discovery"
STRATEGY_WORK_TYPE = "strategy"
ACCOUNT_PLANNING_WORK_TYPE = "account_planning"
OPEN_WORK_ITEM_STATUSES = {
    WorkItemStatus.PENDING,
    WorkItemStatus.IN_PROGRESS,
    WorkItemStatus.REVIEW_PENDING,
    WorkItemStatus.ESCALATED,
}
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
    OBSERVATION_WORK_TYPE: OBSERVATION_OWNER_ROLE,
}
WORK_TYPE_TO_DEFAULT_GOAL = {
    DISCOVERY_WORK_TYPE: "Produce or refresh a shortlist of Telegram communities that match the current campaign brief.",
    STRATEGY_WORK_TYPE: "Turn the approved community shortlist into a campaign strategy playbook.",
    ACCOUNT_PLANNING_WORK_TYPE: "Turn the approved strategy playbook into an account assignment plan.",
    OBSERVATION_WORK_TYPE: "Review unresolved campaign signals that may require planning or posture changes.",
}
_VALIDATED_DISCOVERY_STATES = frozenset({"live_confirmed", "search_confirmed"})
OBSERVATION_SIGNAL_DIGEST_LIMIT = 8


@dataclass(slots=True)
class ScheduledExecutionOutcome:
    """Normalized outcome for one schedule-triggered specialist run."""

    result_summary: str
    metric_value: int | None = None
    related_memory_refs: list[str] = field(default_factory=list)
    status: WorkItemStatus = WorkItemStatus.REVIEW_PENDING


@dataclass(slots=True)
class ReasoningSurfaceRoute:
    """Normalized work-family route for the current turn."""

    work_type: str
    reasoning_surface: str
    work_item: WorkItemRecord | None = None
    review_pending: bool = False


@dataclass(slots=True)
class FollowOnDecision:
    """Deterministic next-step decision after a planning review is accepted."""

    work_type: str
    work_item: WorkItemRecord | None = None
    action: str = "run"
    summary: str = ""


@dataclass(slots=True)
class ObservationExecutionOutcome:
    """Result of one bounded observation execution path."""

    work_item: WorkItemRecord | None
    operator_text: str = ""


def _load_prompt(name: str) -> str:
    """Load a prompt from the prompts/ directory at the repo root."""
    path = REPO_ROOT / "prompts" / name
    return path.read_text(encoding="utf-8")


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


def _is_activation_request(text: str) -> bool:
    """Return whether the operator is explicitly trying to activate execution."""
    import re

    normalized = text.lower().strip().strip(".,!?")
    if not normalized:
        return False
    if normalized.endswith("?"):
        return False
    if re.match(r"^(please\s+)?(activate|launch)\b", normalized):
        return True
    return any(
        re.match(rf"^(please\s+)?{phrase}\b", normalized)
        for phrase in _ACTIVATION_PHRASES
    )


def _looks_like_revision_feedback(text: str) -> bool:
    """Return whether review-turn text is asking for a revision instead of a routing reply."""
    normalized = text.lower().strip()
    if not normalized:
        return False
    if normalized.endswith("?") and not any(phrase in normalized for phrase in _REVISION_FEEDBACK_PHRASES):
        return False
    return any(phrase in normalized for phrase in _REVISION_FEEDBACK_PHRASES)


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
        signal_manager: CampaignSignalManager | None = None,
        continuous_ops_manager: ContinuousOpsManager | None = None,
        prepared_execution_service: PreparedExecutionService | None = None,
        live_ops_service: LiveOpsService | None = None,
        compiled_intent_store: CompiledIntentStore | None = None,
        compiled_intent_applicator: CompiledIntentApplicator | None = None,
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
        self._signal_manager = signal_manager
        self._continuous_ops_manager = continuous_ops_manager
        self._prepared_execution_service = prepared_execution_service
        self._live_ops_service = live_ops_service
        self._compiled_intent_store = compiled_intent_store
        self._compiled_intent_applicator = compiled_intent_applicator
        self._monitor = monitor or NullRuntimeEventLogger()
        self._allow_live_sends = allow_live_sends
        self._client = anthropic.Anthropic()
        self._toolbox = TelegramCapabilityToolbox(
            account_capability=account_capability,
            community_capability=community_capability,
            membership_capability=membership_capability,
            messaging_capability=messaging_capability,
        )
        self._agent_runtime_broker = AgentRuntimeBroker(
            work_item_manager=work_item_manager,
            schedule_manager=schedule_manager,
            compiled_intent_store=compiled_intent_store,
            account_capability=account_capability,
            community_capability=community_capability,
            membership_capability=membership_capability,
            messaging_capability=messaging_capability,
        )
        self._observation_work_refresher = (
            ObservationWorkRefresher(signal_manager, work_item_manager)
            if signal_manager is not None and work_item_manager is not None
            else None
        )

    def handle_turn(
        self,
        session: SessionRecord,
        update: TelegramUpdate,
        pending_approval: ApprovalRecord | None = None,
        trace_context: RuntimeTraceContext | None = None,
    ) -> TelegramResponse:
        """Run one orchestrator turn, selecting the best reasoning surface for the turn."""
        operator_message = update.text or ""
        if _is_activation_request(operator_message):
            return self._handle_plan_activation_turn(session, update)
        route = self._resolve_reasoning_surface_route(session, pending_approval)
        direct_control_response = self._handle_direct_operator_control(
            session,
            update,
            operator_message=operator_message,
            route=route,
            pending_approval=pending_approval,
        )
        if direct_control_response is not None:
            return direct_control_response
        self._promote_general_operator_context(
            session,
            operator_message,
            source_message_id=update.message_id,
        )

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

        if route is not None and route.work_type == OBSERVATION_WORK_TYPE:
            return self._run_operator_observation_turn(
                session,
                update,
                operator_message=operator_message,
                work_item=route.work_item,
            )

        return self._run_orchestrator_turn(session, update, pending_approval)

    def _live_ops_conflicts_with_planning_review(
        self,
        intent_kind: LiveOpsIntentKind,
        route: ReasoningSurfaceRoute | None,
        operator_message: str,
    ) -> bool:
        if route is None or not route.review_pending:
            return False
        if intent_kind not in {LiveOpsIntentKind.UPDATE_VOICE, LiveOpsIntentKind.UPDATE_SAFEGUARD}:
            return False
        return _looks_like_revision_feedback(operator_message)

    def _handle_direct_operator_control(
        self,
        session: SessionRecord,
        update: TelegramUpdate,
        *,
        operator_message: str,
        route: ReasoningSurfaceRoute | None,
        pending_approval: ApprovalRecord | None,
    ) -> TelegramResponse | None:
        live_ops_intents = (
            self._live_ops_service.detect_intents(operator_message)
            if self._live_ops_service is not None
            else []
        )
        compileable_live_ops_intents = [
            intent
            for intent in live_ops_intents
            if self._is_compileable_live_ops_intent(intent.kind)
        ]
        direct_schedule_intent = self._compile_direct_schedule_intent(session, operator_message)

        if not compileable_live_ops_intents and direct_schedule_intent is None:
            if live_ops_intents:
                response_text = self._live_ops_service.handle_intent(
                    session,
                    live_ops_intents[0],
                    operator_id=session.operator_id,
                )
                return TelegramResponse.single(update.chat_id, response_text)
            if self._should_handle_schedule_authoring(operator_message):
                return self._run_orchestrator_turn(session, update, pending_approval)
            return None

        if any(
            self._live_ops_conflicts_with_planning_review(intent.kind, route, operator_message)
            for intent in compileable_live_ops_intents
        ):
            return TelegramResponse.single(
                update.chat_id,
                "Do you want me to apply that as a live reply control for the campaign, or revise the current planning draft?",
            )

        if self._compiled_intent_store is None or self._compiled_intent_applicator is None:
            self._promote_general_operator_context(
                session,
                operator_message,
                source_message_id=update.message_id,
            )
            if direct_schedule_intent is not None:
                return self._run_orchestrator_turn(session, update, pending_approval)
            response_text = "\n\n".join(
                self._live_ops_service.handle_intent(
                    session,
                    intent,
                    operator_id=session.operator_id,
                )
                for intent in compileable_live_ops_intents
            )
            return TelegramResponse.single(update.chat_id, response_text)

        self._promote_general_operator_context(
            session,
            operator_message,
            source_message_id=update.message_id,
        )

        compiled_intents = []
        if session.campaign_id and compileable_live_ops_intents:
            compiled_intents.extend(
                compile_live_ops_intents(
                    session.campaign_id,
                    compileable_live_ops_intents,
                    source_role="orchestrator",
                    operator_id=session.operator_id,
                    grounding_refs=self._build_control_grounding_refs(session),
                )
            )
        if direct_schedule_intent is not None:
            compiled_intents.append(direct_schedule_intent)

        if not compiled_intents:
            return None

        response_lines: list[str] = []
        for compiled_intent in compiled_intents:
            result = self._apply_persisted_compiled_intent(session, compiled_intent)
            response_lines.append(result)

        self._refresh_continuous_ops(session=session)
        response_text = "\n\n".join(line for line in response_lines if line.strip())
        return TelegramResponse.single(update.chat_id, response_text)

    def _is_compileable_live_ops_intent(self, intent_kind: LiveOpsIntentKind) -> bool:
        return intent_kind in {
            LiveOpsIntentKind.APPROVE_REVIEW,
            LiveOpsIntentKind.DISMISS_REVIEW,
            LiveOpsIntentKind.PAUSE_SCOPE,
            LiveOpsIntentKind.RESUME_SCOPE,
            LiveOpsIntentKind.SET_POSTURE,
            LiveOpsIntentKind.UPDATE_VOICE,
            LiveOpsIntentKind.UPDATE_SAFEGUARD,
        }

    def _compile_direct_schedule_intent(
        self,
        session: SessionRecord,
        operator_message: str,
    ):
        if not session.campaign_id or not self._should_handle_schedule_authoring(operator_message):
            return None

        normalized = operator_message.lower().strip()
        action = ""
        if "pause" in normalized:
            action = "pause"
        elif "resume" in normalized:
            action = "resume"
        else:
            action = "create"

        work_type = self._infer_schedule_work_type(operator_message, action=action, session=session)
        if not work_type:
            return None

        schedule_payload: dict[str, object] = {"work_type": work_type}
        owner_role = WORK_TYPE_TO_OWNER_ROLE.get(work_type, "")
        if owner_role:
            schedule_payload["owner_role"] = owner_role

        if action == "create":
            interval_minutes = self._extract_schedule_interval_minutes(normalized)
            if interval_minutes is None:
                return None
            schedule_payload.update(
                {
                    "goal": self._build_stage_goal(session, work_type),
                    "interval_minutes": interval_minutes,
                    "constraints": self._build_stage_constraints(session),
                    "priority": self._extract_schedule_priority(normalized).value,
                }
            )

        return compile_schedule_action(
            session.campaign_id,
            {"action": action, "schedule": schedule_payload},
            source_role="orchestrator",
            grounding_refs=self._build_schedule_grounding_refs(session),
        )

    def _infer_schedule_work_type(
        self,
        operator_message: str,
        *,
        action: str,
        session: SessionRecord,
    ) -> str:
        normalized = operator_message.lower()
        for token, work_type in (
            ("account planning", ACCOUNT_PLANNING_WORK_TYPE),
            ("account plan", ACCOUNT_PLANNING_WORK_TYPE),
            ("assignment plan", ACCOUNT_PLANNING_WORK_TYPE),
            ("strategy", STRATEGY_WORK_TYPE),
            ("playbook", STRATEGY_WORK_TYPE),
            ("observation", OBSERVATION_WORK_TYPE),
            ("signal review", OBSERVATION_WORK_TYPE),
            ("discovery", DISCOVERY_WORK_TYPE),
            ("shortlist", DISCOVERY_WORK_TYPE),
        ):
            if token in normalized:
                return work_type

        if not session.campaign_id or self._schedule_manager is None or action not in {"pause", "resume"}:
            return ""

        target_status = {ScheduleStatus.ACTIVE} if action == "pause" else {ScheduleStatus.PAUSED}
        schedules = [
            schedule
            for schedule in self._schedule_manager.list_for_campaign(session.campaign_id)
            if schedule.status in target_status
        ]
        if len(schedules) == 1:
            return schedules[0].work_type
        return ""

    def _extract_schedule_interval_minutes(self, normalized_message: str) -> int | None:
        every_match = self._match_every_interval(normalized_message)
        if every_match is not None:
            return every_match
        if "hourly" in normalized_message:
            return 60
        if "daily" in normalized_message:
            return 1440
        if "weekly" in normalized_message:
            return 10080
        if "monthly" in normalized_message:
            return 43200
        return None

    def _match_every_interval(self, normalized_message: str) -> int | None:
        import re

        match = re.search(r"\bevery\s+(\d+)\s+(minute|minutes|hour|hours|day|days|week|weeks)\b", normalized_message)
        if match is None:
            return None
        value = int(match.group(1))
        unit = match.group(2)
        multipliers = {
            "minute": 1,
            "minutes": 1,
            "hour": 60,
            "hours": 60,
            "day": 1440,
            "days": 1440,
            "week": 10080,
            "weeks": 10080,
        }
        return value * multipliers[unit]

    def _extract_schedule_priority(self, normalized_message: str) -> WorkItemPriority:
        if "low priority" in normalized_message:
            return WorkItemPriority.LOW
        if "medium priority" in normalized_message:
            return WorkItemPriority.MEDIUM
        return WorkItemPriority.HIGH

    def _build_control_grounding_refs(self, session: SessionRecord) -> list[str]:
        refs = self._build_schedule_grounding_refs(session)
        campaign_context = get_campaign_context_artifact(session)
        if campaign_context is not None:
            refs.append(f"artifact:{campaign_context.artifact_id}")
        return refs

    def _apply_persisted_compiled_intent(
        self,
        session: SessionRecord,
        compiled_intent,
    ) -> str:
        if self._compiled_intent_store is None:
            return "Compiled-intent persistence is not available in this runtime yet."

        self._enrich_compiled_intent_with_runtime_context(session, compiled_intent)
        self._compiled_intent_store.save(compiled_intent)
        validation_error = validate_compiled_intent(compiled_intent)
        if validation_error is not None:
            compiled_intent.mark_rejected(validation_error)
            self._compiled_intent_store.save(compiled_intent)
            return "I did not apply that control because the compiled intent was invalid. " + validation_error

        compiled_intent.mark_accepted()
        self._compiled_intent_store.save(compiled_intent)
        try:
            if compiled_intent.kind == "campaign_control.update_context":
                result = self._apply_campaign_context_compiled_intent(session, compiled_intent)
            else:
                if self._compiled_intent_applicator is None:
                    raise CompiledIntentApplicationError(
                        "Compiled-intent application is not available in this runtime yet."
                    )
                result = self._compiled_intent_applicator.apply(compiled_intent)
        except CompiledIntentApplicationError as exc:
            compiled_intent.mark_blocked(str(exc))
            self._compiled_intent_store.save(compiled_intent)
            return compiled_intent.blocked_reason

        compiled_intent.mark_applied(result)
        self._compiled_intent_store.save(compiled_intent)
        return result

    def _enrich_compiled_intent_with_runtime_context(self, session: SessionRecord, compiled_intent) -> None:
        if compiled_intent.kind != "live_action.enqueue_operator_send":
            return
        if not isinstance(compiled_intent.payload, dict):
            return
        operator_id = str(compiled_intent.payload.get("operator_id", "")).strip()
        if operator_id:
            return
        compiled_intent.payload["operator_id"] = session.operator_id

    def _apply_campaign_context_compiled_intent(self, session: SessionRecord, compiled_intent) -> str:
        self._update_campaign_context_artifact(session, compiled_intent.payload)
        return "Updated the durable campaign context."

    def _persist_compiled_proposal(self, compiled_intent) -> None:
        if self._compiled_intent_store is None:
            return
        self._compiled_intent_store.save(compiled_intent)
        validation_error = validate_compiled_intent(compiled_intent)
        if validation_error is not None:
            compiled_intent.mark_rejected(validation_error)
            self._compiled_intent_store.save(compiled_intent)
            return
        compiled_intent.mark_accepted()
        self._compiled_intent_store.save(compiled_intent)

    def _persist_specialist_advisory_proposals(
        self,
        session: SessionRecord,
        *,
        work_type: str,
        source_role: str,
        operator_text: str,
        artifact: WorkflowArtifact | None,
        raw_proposals: list[dict[str, object]] | None = None,
    ) -> None:
        if artifact is None or self._compiled_intent_store is None or not session.campaign_id:
            return

        proposal_payloads = [
            dict(proposal)
            for proposal in raw_proposals or []
            if isinstance(proposal, dict)
        ]
        if not proposal_payloads:
            proposal_payloads = self._default_specialist_proposal_payloads(
                work_type=work_type,
                operator_text=operator_text,
                artifact=artifact,
            )

        compiled_proposals = compile_specialist_proposals(
            session.campaign_id,
            proposal_payloads,
            source_role=source_role,
            grounding_refs=[
                *self._build_control_grounding_refs(session),
                *self._related_refs_for_work_type(session, work_type),
            ],
        )
        for compiled_proposal in compiled_proposals:
            self._persist_compiled_proposal(compiled_proposal)

    def _latest_compiled_intent(
        self,
        session: SessionRecord,
        *,
        kind: str,
        payload_key: str,
        payload_value: str,
    ):
        if self._compiled_intent_store is None or not session.campaign_id:
            return None

        accepted_statuses = {CompiledIntentStatus.ACCEPTED, CompiledIntentStatus.APPLIED}
        intents = sorted(
            self._compiled_intent_store.list_for_campaign(session.campaign_id),
            key=lambda intent: intent.updated_at,
            reverse=True,
        )
        for intent in intents:
            if intent.kind != kind or intent.status not in accepted_statuses:
                continue
            if str(intent.payload.get(payload_key, "")).strip() != payload_value:
                continue
            return intent
        return None

    def _latest_review_posture(self, session: SessionRecord, work_type: str):
        return self._latest_compiled_intent(
            session,
            kind="planning.review_posture",
            payload_key="work_type",
            payload_value=work_type,
        )

    def _latest_follow_on_recommendation(self, session: SessionRecord, work_type: str):
        return self._latest_compiled_intent(
            session,
            kind="planning.follow_on_recommendation",
            payload_key="current_work_type",
            payload_value=work_type,
        )

    def _latest_execution_state_impact(self, session: SessionRecord, work_type: str):
        return self._latest_compiled_intent(
            session,
            kind="planning.execution_state_impact",
            payload_key="work_type",
            payload_value=work_type,
        )

    def _follow_on_work_type_from_recommendation(
        self,
        recommendation,
        *,
        completed_work_type: str,
    ) -> str | None:
        if recommendation is not None:
            recommended_action = str(recommendation.payload.get("recommended_action", "")).strip()
            if recommended_action == "hold":
                return None
            recommended_work_type = str(recommendation.payload.get("recommended_next_work_type", "")).strip()
            if recommended_work_type:
                return recommended_work_type
        return self._fallback_follow_on_work_type(completed_work_type)

    def _fallback_follow_on_work_type(self, work_type: str) -> str | None:
        return {
            DISCOVERY_WORK_TYPE: STRATEGY_WORK_TYPE,
            STRATEGY_WORK_TYPE: ACCOUNT_PLANNING_WORK_TYPE,
        }.get(work_type)

    def _default_specialist_proposal_payloads(
        self,
        *,
        work_type: str,
        operator_text: str,
        artifact: WorkflowArtifact | None,
    ) -> list[dict[str, object]]:
        artifact_kind = artifact.kind.value if artifact is not None else _work_type_to_artifact_kind(work_type).value
        artifact_id = artifact.artifact_id if artifact is not None else ""
        proposals: list[dict[str, object]] = [
            {
                "kind": "planning.review_posture",
                "summary": f"{self._work_type_label(work_type)} output is ready for operator review.",
                "payload": {
                    "work_type": work_type,
                    "artifact_kind": artifact_kind,
                    "artifact_id": artifact_id,
                    "review_state": "ready_for_review",
                    "review_summary": operator_text.strip() or f"{self._work_type_label(work_type)} output is ready.",
                    "operator_prompt": self._fallback_review_prompt_for_work_type(work_type),
                },
                "confidence": 1.0,
            }
        ]

        follow_on_work_type = self._fallback_follow_on_work_type(work_type)
        if follow_on_work_type is not None:
            proposals.append(
                {
                    "kind": "planning.follow_on_recommendation",
                    "summary": (
                        f"Recommend {self._work_type_label(follow_on_work_type).lower()} after "
                        f"{self._work_type_label(work_type).lower()} review."
                    ),
                    "payload": {
                        "current_work_type": work_type,
                        "recommended_next_work_type": follow_on_work_type,
                        "recommended_action": "refresh_if_stale",
                        "reason": f"{self._work_type_label(work_type)} is one bounded planning surface inside a longer-lived loop.",
                    },
                    "confidence": 0.9,
                }
            )
        elif work_type == ACCOUNT_PLANNING_WORK_TYPE:
            proposals.append(
                {
                    "kind": "planning.execution_state_impact",
                    "summary": "Record the execution-state impact of the latest account-plan revision.",
                    "payload": {
                        "work_type": work_type,
                        "recommended_action": "invalidate_prepared_execution_if_present",
                        "activation_phrase": "activate",
                        "reason": "Prepared execution should stay deterministic and match the latest approved account-plan revision.",
                    },
                    "confidence": 0.95,
                }
            )
        return proposals

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
            agent_runtime_broker=self._agent_runtime_broker,
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

        model = resolve_model()
        logger.info("Orchestrator calling Anthropic API model=%s, messages=%d", model, len(messages))

        completion = self._toolbox.run_completion(
            client=self._client,
            model=model,
            max_tokens=4096,
            system=system,
            messages=messages,
        )

        final_output_text = completion.final_output

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
        self._refresh_continuous_ops(session=session)

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
            account_capability=self._account_capability,
            community_capability=self._community_capability,
            membership_capability=self._membership_capability,
            messaging_capability=self._messaging_capability,
            monitor=self._monitor,
            runtime_broker=self._agent_runtime_broker,
        )
        operator_text, artifact, _approval = agent.run(
            session,
            self._build_specialist_operator_message(work_item, operator_message),
            trace_context=trace_context,
        )
        self._persist_specialist_advisory_proposals(
            session,
            work_type=DISCOVERY_WORK_TYPE,
            source_role="discovery",
            operator_text=operator_text,
            artifact=artifact,
            raw_proposals=getattr(agent, "last_proposal_payloads", []),
        )
        self._mark_review_pending(
            session,
            work_item,
            result_summary="Community shortlist ready for operator review.",
            related_memory_refs=self._related_refs_for_session_artifact(
                session, WorkflowArtifactKind.COMMUNITY_SHORTLIST
            ),
        )
        operator_text = self._append_capability_notice(operator_text)
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
            account_capability=self._account_capability,
            community_capability=self._community_capability,
            membership_capability=self._membership_capability,
            messaging_capability=self._messaging_capability,
            monitor=self._monitor,
            runtime_broker=self._agent_runtime_broker,
        )
        operator_text, artifact = agent.run(
            session,
            operator_message=self._build_specialist_operator_message(work_item, operator_message),
            trace_context=trace_context,
        )
        self._persist_specialist_advisory_proposals(
            session,
            work_type=STRATEGY_WORK_TYPE,
            source_role="strategy",
            operator_text=operator_text,
            artifact=artifact,
            raw_proposals=getattr(agent, "last_proposal_payloads", []),
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

        operator_text = self._append_capability_notice(operator_text)
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
            community_capability=self._community_capability,
            membership_capability=self._membership_capability,
            messaging_capability=self._messaging_capability,
            monitor=self._monitor,
            runtime_broker=self._agent_runtime_broker,
        )
        operator_text, artifact, _approval = agent.run(
            session,
            operator_message=self._build_specialist_operator_message(work_item, operator_message),
            trace_context=trace_context,
        )
        self._persist_specialist_advisory_proposals(
            session,
            work_type=ACCOUNT_PLANNING_WORK_TYPE,
            source_role="account_manager",
            operator_text=operator_text,
            artifact=artifact,
            raw_proposals=getattr(agent, "last_proposal_payloads", []),
        )
        if artifact is not None and self._session_manager is not None:
            invalidation_summary = self._invalidate_prepared_execution_for_latest_plan(session)
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
            if invalidation_summary:
                operator_text = self._append_runtime_note(operator_text, invalidation_summary)
        operator_text = self._append_capability_notice(operator_text)
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
            self._resolve_campaign_context_revision(session, DISCOVERY_WORK_TYPE, accepted=True)
            return self._continue_planning_after_review_approval(
                session,
                update,
                approved_work_type=DISCOVERY_WORK_TYPE,
                approved_summary="Community shortlist accepted in chat.",
                follow_on_summary="Community shortlist accepted in chat. Refreshing strategy planning.",
                trace_context=trace_context,
            )
        if decision is False or _looks_like_revision_feedback(operator_message):
            self._promote_campaign_context_revision(
                session,
                DISCOVERY_WORK_TYPE,
                operator_message,
                source_message_id=update.message_id,
            )
            self._reopen_stage_work_item(
                session,
                DISCOVERY_WORK_TYPE,
                "Refreshing the community shortlist after operator feedback.",
            )
            return self._run_discovery_agent(session, update, operator_message, trace_context=trace_context)
        return self._reply_with_stage_prompt(
            session,
            update,
            self._review_prompt_for_work_type(session, DISCOVERY_WORK_TYPE),
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
            self._resolve_campaign_context_revision(session, STRATEGY_WORK_TYPE, accepted=True)
            return self._continue_planning_after_review_approval(
                session,
                update,
                approved_work_type=STRATEGY_WORK_TYPE,
                approved_summary="Strategy playbook accepted in chat.",
                follow_on_summary="Strategy accepted in chat. Refreshing account planning.",
                trace_context=trace_context,
            )
        if decision is False or _looks_like_revision_feedback(operator_message):
            self._promote_campaign_context_revision(
                session,
                STRATEGY_WORK_TYPE,
                operator_message,
                source_message_id=update.message_id,
            )
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
            self._review_prompt_for_work_type(session, STRATEGY_WORK_TYPE),
        )

    def _handle_account_plan_review_turn(
        self,
        session: SessionRecord,
        update: TelegramUpdate,
        operator_message: str,
    ) -> TelegramResponse:
        decision = _classify_approval_response(operator_message)
        if decision is True:
            self._resolve_campaign_context_revision(session, ACCOUNT_PLANNING_WORK_TYPE, accepted=True)
            self._complete_stage_work_item(
                session,
                ACCOUNT_PLANNING_WORK_TYPE,
                "Account assignment plan accepted in chat.",
            )
            self._set_workflow_stage(
                session,
                WorkflowStage.ACCOUNT_PLANNING,
                "Account assignment plan approved in chat. The campaign remains active for execution and future planning refreshes.",
            )
            return self._reply_with_stage_prompt(
                session,
                update,
                self._approval_completion_prompt(session, ACCOUNT_PLANNING_WORK_TYPE),
            )
        if decision is False or _looks_like_revision_feedback(operator_message):
            self._promote_campaign_context_revision(
                session,
                ACCOUNT_PLANNING_WORK_TYPE,
                operator_message,
                source_message_id=update.message_id,
            )
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
            self._review_prompt_for_work_type(session, ACCOUNT_PLANNING_WORK_TYPE),
        )

    def _handle_plan_activation_turn(
        self,
        session: SessionRecord,
        update: TelegramUpdate,
    ) -> TelegramResponse:
        if self._prepared_execution_service is None:
            return self._reply_with_stage_prompt(
                session,
                update,
                "Execution activation is not available in this runtime yet.",
            )
        activation_result = self._prepared_execution_service.activate_latest_plan(
            session,
            queue_immediately=self._allow_live_sends,
        )
        if activation_result.batch is not None:
            self._set_workflow_stage(
                session,
                WorkflowStage.ACCOUNT_PLANNING,
                "Prepared execution is active for the latest approved account plan.",
                data={
                    "account_assignment_plan_artifact_id": activation_result.batch.source_plan_artifact_id,
                    "prepared_execution_batch_id": activation_result.batch.batch_id,
                    "prepared_execution_status": activation_result.batch.status.value,
                    "prepared_execution_queued_count": activation_result.queued_count,
                    "prepared_execution_held_count": activation_result.held_count,
                    "prepared_execution_blocked_count": activation_result.blocked_count,
                },
            )
        self._append_assistant_reply(session, activation_result.message)
        return TelegramResponse.single(update.chat_id, activation_result.message)

    def _continue_planning_after_review_approval(
        self,
        session: SessionRecord,
        update: TelegramUpdate,
        *,
        approved_work_type: str,
        approved_summary: str,
        follow_on_summary: str,
        trace_context: RuntimeTraceContext | None = None,
    ) -> TelegramResponse:
        self._complete_stage_work_item(session, approved_work_type, approved_summary)
        follow_on = self._determine_follow_on_work(session, approved_work_type, follow_on_summary)
        if follow_on is None:
            return self._reply_with_stage_prompt(
                session,
                update,
                "I saved that review outcome. Tell me what you want to refresh next.",
            )
        if follow_on.action == "review_pending":
            self._set_workflow_stage(
                session,
                WORK_TYPE_TO_STAGE[follow_on.work_type],
                follow_on.summary,
            )
            return self._reply_with_stage_prompt(
                session,
                update,
                self._review_prompt_for_work_type(session, follow_on.work_type),
            )
        if follow_on.action == "up_to_date":
            self._set_workflow_stage(
                session,
                WORK_TYPE_TO_STAGE[follow_on.work_type],
                follow_on.summary,
            )
            return self._reply_with_stage_prompt(
                session,
                update,
                self._up_to_date_prompt_for_work_type(session, follow_on.work_type),
            )
        if follow_on.work_type == STRATEGY_WORK_TYPE:
            return self._run_strategy_agent(
                session,
                update,
                work_item=follow_on.work_item,
                trace_context=trace_context,
            )
        if follow_on.work_type == ACCOUNT_PLANNING_WORK_TYPE:
            return self._run_account_manager_agent(
                session,
                update,
                work_item=follow_on.work_item,
                trace_context=trace_context,
            )
        return self._reply_with_stage_prompt(
            session,
            update,
            "I saved that review outcome. Tell me what you want to refresh next.",
        )

    def _determine_follow_on_work(
        self,
        session: SessionRecord,
        completed_work_type: str,
        summary: str,
    ) -> FollowOnDecision | None:
        follow_on_recommendation = self._latest_follow_on_recommendation(session, completed_work_type)
        follow_on_work_type = self._follow_on_work_type_from_recommendation(
            follow_on_recommendation,
            completed_work_type=completed_work_type,
        )
        if follow_on_work_type is None:
            return None
        follow_on_work_item = self._get_work_item_for_type(session, follow_on_work_type)
        needs_refresh = self._follow_on_work_needs_refresh(
            session,
            completed_work_type,
            follow_on_work_type,
        )
        if not needs_refresh and follow_on_work_item is not None and follow_on_work_item.status is WorkItemStatus.REVIEW_PENDING:
            return FollowOnDecision(
                work_type=follow_on_work_type,
                work_item=follow_on_work_item,
                action="review_pending",
                summary=f"{self._work_type_label(follow_on_work_type)} draft is already waiting for review.",
            )
        if not needs_refresh:
            return FollowOnDecision(
                work_type=follow_on_work_type,
                work_item=follow_on_work_item,
                action="up_to_date",
                summary=f"{self._work_type_label(follow_on_work_type)} is already current for the latest approved inputs.",
            )
        follow_on_work_item = self._activate_follow_on_work_item(
            session,
            completed_work_type=completed_work_type,
            follow_on_work_type=follow_on_work_type,
            summary=summary,
        )
        if follow_on_work_item is None:
            return None
        return FollowOnDecision(
            work_type=follow_on_work_type,
            work_item=follow_on_work_item,
            action="run",
            summary=summary,
        )

    def _activate_follow_on_work_item(
        self,
        session: SessionRecord,
        *,
        completed_work_type: str,
        follow_on_work_type: str,
        summary: str,
    ) -> WorkItemRecord | None:
        if (
            self._work_item_manager is None
            or not session.campaign_id
        ):
            return self._ensure_work_item_for_type(
                session,
                follow_on_work_type,
                status=WorkItemStatus.IN_PROGRESS,
                trigger_source="review_acceptance",
                refresh_reason=summary,
            )
        context_refs = self._related_refs_for_work_type(session, follow_on_work_type)
        completed_work_item = self._get_work_item_for_type(session, completed_work_type)
        if completed_work_item is not None:
            context_refs.append(f"work_item:{completed_work_item.work_item_id}")
        follow_on_work_item = self._get_work_item_for_type(session, follow_on_work_type)
        if self._compiled_intent_store is None or self._compiled_intent_applicator is None:
            follow_on_item = self._ensure_work_item_for_type(
                session,
                follow_on_work_type,
                status=WorkItemStatus.IN_PROGRESS,
                trigger_source="review_acceptance",
                refresh_reason=summary,
                context_refs=context_refs,
            )
            if follow_on_item is None:
                return None
            self._work_item_manager.update_status(
                session.campaign_id,
                follow_on_item.work_item_id,
                status=WorkItemStatus.IN_PROGRESS,
                result_summary="",
                trigger_source="review_acceptance",
                refresh_reason=summary,
                context_refs=context_refs,
                related_memory_refs=self._related_refs_for_work_type(session, follow_on_work_type),
            )
            reloaded_item = self._work_item_manager.get(session.campaign_id, follow_on_item.work_item_id)
        else:
            action = "refresh" if follow_on_work_item is not None else "propose"
            compiled_intent = compile_work_intent(
                session.campaign_id,
                action=action,
                work_payload={
                    "owner_role": WORK_TYPE_TO_OWNER_ROLE[follow_on_work_type],
                    "work_type": follow_on_work_type,
                    "goal": self._build_stage_goal(session, follow_on_work_type),
                    "constraints": self._build_stage_constraints(session),
                    "priority": WorkItemPriority.HIGH.value,
                    "related_memory_refs": self._related_refs_for_work_type(session, follow_on_work_type),
                    "context_refs": context_refs,
                    "trigger_source": "review_acceptance",
                    "refresh_reason": summary,
                    "status": WorkItemStatus.IN_PROGRESS.value,
                },
                source_role="orchestrator",
                grounding_refs=self._build_control_grounding_refs(session),
                confidence=1.0,
            )
            if compiled_intent is None:
                return None
            self._apply_persisted_compiled_intent(session, compiled_intent)
            reloaded_item = self._get_work_item_for_type(session, follow_on_work_type)
        if reloaded_item is not None:
            self._set_workflow_stage(
                session,
                WORK_TYPE_TO_STAGE[follow_on_work_type],
                summary,
            )
        return reloaded_item

    def _resolve_reasoning_surface_route(
        self,
        session: SessionRecord,
        pending_approval: ApprovalRecord | None,
    ) -> ReasoningSurfaceRoute | None:
        stage = get_workflow_snapshot(session).stage
        released_stage = self._release_legacy_approval_gate(session, stage, pending_approval)
        if self._setup_requires_orchestrator_turn(session, released_stage):
            return None
        review_pending_planning_item = self._get_review_pending_planning_work_item(session)
        if review_pending_planning_item is not None:
            return self._build_reasoning_surface_route(
                work_type=review_pending_planning_item.work_type,
                work_item=review_pending_planning_item,
                review_pending=True,
            )
        primary_work_item = self._get_primary_work_item(session)
        if primary_work_item is not None:
            return self._build_reasoning_surface_route(
                work_type=primary_work_item.work_type,
                work_item=primary_work_item,
                review_pending=primary_work_item.status is WorkItemStatus.REVIEW_PENDING,
            )
        return self._build_compatibility_route(session, released_stage)

    def _build_compatibility_route(
        self,
        session: SessionRecord,
        stage: WorkflowStage,
    ) -> ReasoningSurfaceRoute | None:
        work_type = STAGE_TO_WORK_TYPE.get(stage)
        if work_type is None:
            return None

        review_pending = self._has_artifact(session, _work_type_to_artifact_kind(work_type))
        work_item = self._ensure_work_item_for_type(
            session,
            work_type,
            status=WorkItemStatus.REVIEW_PENDING if review_pending else WorkItemStatus.IN_PROGRESS,
            trigger_source="compatibility_backfill",
            refresh_reason="Created from compatibility workflow stage state.",
        )
        return self._build_reasoning_surface_route(
            work_type=work_type,
            work_item=work_item,
            review_pending=review_pending,
        )

    def _build_reasoning_surface_route(
        self,
        *,
        work_type: str,
        work_item: WorkItemRecord | None,
        review_pending: bool,
    ) -> ReasoningSurfaceRoute:
        return ReasoningSurfaceRoute(
            work_type=work_type,
            reasoning_surface=reasoning_surface_for_work_type(work_type),
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

    def _promote_general_operator_context(
        self,
        session: SessionRecord,
        operator_message: str,
        *,
        source_message_id: str = "",
    ) -> None:
        normalized_message = operator_message.strip()
        if not normalized_message:
            return
        existing_artifact = get_campaign_context_artifact(session)
        merged_context = merge_campaign_context_data(
            self._campaign_context_data(session),
            message=normalized_message,
            source_message_id=source_message_id,
        )
        if existing_artifact is not None and merged_context == existing_artifact.data:
            return
        if (
            existing_artifact is None
            and build_campaign_context_summary(merged_context) == "No durable campaign-context guidance has been promoted yet."
        ):
            return
        self._persist_campaign_context_update(
            session,
            merged_context,
            summary="Promote durable campaign-context guidance from the latest operator turn.",
            source_role="operator",
        )

    def _promote_campaign_context_revision(
        self,
        session: SessionRecord,
        scope: str,
        operator_message: str,
        *,
        source_message_id: str = "",
    ) -> None:
        normalized_message = operator_message.strip()
        if not normalized_message:
            return
        revised_context = promote_campaign_context_revision(
            self._campaign_context_data(session),
            scope=scope,
            message=normalized_message,
            source_message_id=source_message_id,
        )
        self._persist_campaign_context_update(
            session,
            revised_context,
            summary=f"Promote a `{scope}` revision request into the durable campaign context.",
            source_role="operator",
        )

    def _resolve_campaign_context_revision(
        self,
        session: SessionRecord,
        scope: str,
        *,
        accepted: bool,
    ) -> None:
        resolved_context = resolve_campaign_context_revision(
            self._campaign_context_data(session),
            scope=scope,
            accepted=accepted,
        )
        outcome = "accepted" if accepted else "superseded"
        self._persist_campaign_context_update(
            session,
            resolved_context,
            summary=f"Mark the latest `{scope}` revision as `{outcome}` in durable campaign context.",
            source_role="orchestrator",
        )

    def _campaign_context_data(self, session: SessionRecord) -> dict[str, object] | None:
        artifact = get_campaign_context_artifact(session)
        return artifact.data if artifact is not None else None

    def _persist_campaign_context_update(
        self,
        session: SessionRecord,
        data: dict[str, object] | None,
        *,
        summary: str,
        source_role: str,
    ) -> None:
        if not isinstance(data, dict):
            return
        if self._compiled_intent_store is None or not session.campaign_id:
            self._update_campaign_context_artifact(session, data)
            return
        compiled_intent = compile_campaign_context_update(
            session.campaign_id,
            data,
            summary=summary,
            source_role=source_role,
            grounding_refs=self._build_control_grounding_refs(session),
            confidence=1.0,
        )
        if compiled_intent is None:
            self._update_campaign_context_artifact(session, data)
            return
        self._apply_persisted_compiled_intent(session, compiled_intent)

    def _update_campaign_context_artifact(
        self,
        session: SessionRecord,
        data: dict[str, object] | None,
    ) -> None:
        if self._session_manager is None or not isinstance(data, dict):
            return
        artifact = get_campaign_context_artifact(session)
        if artifact is None:
            artifact = self._session_manager.create_workflow_artifact(
                session=session,
                kind=WorkflowArtifactKind.CAMPAIGN_CONTEXT,
                title=CAMPAIGN_CONTEXT_TITLE,
                summary="Campaign context promotion has not captured durable nuance yet.",
                data=data,
            )
        artifact.data = data
        artifact.summary = build_campaign_context_summary(data)
        self._session_manager.save_workflow_artifact(session, artifact)

    def _run_operator_observation_turn(
        self,
        session: SessionRecord,
        update: TelegramUpdate,
        *,
        operator_message: str,
        work_item: WorkItemRecord | None = None,
    ) -> TelegramResponse:
        if not session.campaign_id:
            return self._run_orchestrator_turn(session, update, pending_approval=None)

        observation_outcome = self._execute_observation_work(
            session.campaign_id,
            trigger_source="operator_turn",
            refresh_reason=(work_item.refresh_reason if work_item is not None else "") or operator_message,
        )
        response_text = observation_outcome.operator_text.strip() or (
            "Observation review did not find anything new to route right now."
        )

        if observation_outcome.work_item is not None:
            self._set_workflow_stage(
                session,
                get_workflow_snapshot(session).stage,
                self._build_observation_stage_summary(observation_outcome.work_item),
                data={
                    "routing_reason": "observation_priority",
                    "last_observation_work_item_id": observation_outcome.work_item.work_item_id,
                    "last_observation_status": observation_outcome.work_item.status.value,
                    "last_observation_result_summary": observation_outcome.work_item.result_summary,
                },
            )

        self._append_assistant_reply(session, response_text)
        return TelegramResponse.single(update.chat_id, response_text)

    def handle_scheduled_work(
        self,
        schedule: ScheduleRecord,
        *,
        now: datetime | None = None,
    ) -> WorkItemRecord | None:
        """Create or refresh and execute campaign work directly from a due schedule."""
        if self._work_item_manager is None or self._schedule_manager is None:
            return None
        if schedule.work_type == OBSERVATION_WORK_TYPE:
            return self._handle_scheduled_observation_work(schedule, now=now)
        work_item = self._work_item_manager.ensure_work_item(
            schedule.campaign_id,
            owner_role=schedule.owner_role,
            work_type=schedule.work_type,
            goal=schedule.goal,
            constraints=schedule.constraints,
            priority=schedule.priority,
            due_at=schedule.next_run_at,
            trigger_source="schedule",
            refresh_reason=f"Recurring schedule `{schedule.schedule_id}` triggered `{schedule.work_type}` work.",
            context_refs=[f"schedule:{schedule.schedule_id}"],
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
            self._refresh_continuous_ops(campaign_id=schedule.campaign_id)
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
            self._refresh_continuous_ops(campaign_id=schedule.campaign_id)
            return self._work_item_manager.get(schedule.campaign_id, work_item.work_item_id)

        self._apply_scheduled_work_outcome(schedule, work_item, outcome, ran_at=now)
        self._refresh_continuous_ops(session=session)
        return self._work_item_manager.get(schedule.campaign_id, work_item.work_item_id)

    def run_pending_observation_work(
        self,
        campaign_id: str,
        *,
        trigger_source: str = "observation_runner",
        refresh_reason: str = "",
    ) -> WorkItemRecord | None:
        """Execute the current observation work item without routing through an operator turn."""
        return self._execute_observation_work(
            campaign_id,
            trigger_source=trigger_source,
            refresh_reason=refresh_reason,
        ).work_item

    def _execute_observation_work(
        self,
        campaign_id: str,
        *,
        trigger_source: str,
        refresh_reason: str = "",
    ) -> ObservationExecutionOutcome:
        """Run the shared bounded observation-review path and return operator-safe text."""
        if (
            self._signal_manager is None
            or self._observation_work_refresher is None
            or self._work_item_manager is None
        ):
            return ObservationExecutionOutcome(None, "")

        work_item = self._find_pending_observation_work_item(campaign_id)
        if work_item is None:
            work_item = self._observation_work_refresher.refresh_for_campaign(
                campaign_id,
                trigger_source=trigger_source,
                refresh_reason=refresh_reason,
            )
        if work_item is None:
            self._refresh_continuous_ops(campaign_id=campaign_id)
            return ObservationExecutionOutcome(None, "")

        selected_signals = self._resolve_observation_signals(campaign_id, work_item)
        if not selected_signals:
            self._work_item_manager.update_status(
                campaign_id,
                work_item.work_item_id,
                status=WorkItemStatus.COMPLETED,
                result_summary="Observation review found no new unresolved campaign signals to review.",
                trigger_source=trigger_source,
                refresh_reason=refresh_reason.strip() or "Observation review found no new unresolved signals.",
                context_refs=[],
            )
            reloaded = self._work_item_manager.get(campaign_id, work_item.work_item_id)
            self._refresh_continuous_ops(campaign_id=campaign_id)
            return ObservationExecutionOutcome(
                reloaded,
                "Observation review found no new unresolved campaign signals to review.",
            )

        observation_session = self._build_observation_session(campaign_id)
        if observation_session is None:
            self._work_item_manager.update_status(
                campaign_id,
                work_item.work_item_id,
                status=WorkItemStatus.ESCALATED,
                result_summary="Observation review could not resolve campaign-native context.",
                escalation_reason="Observation review could not resolve campaign-native context.",
                trigger_source=trigger_source,
                refresh_reason="Observation review could not resolve campaign-native context.",
            )
            reloaded = self._work_item_manager.get(campaign_id, work_item.work_item_id)
            self._refresh_continuous_ops(campaign_id=campaign_id)
            return ObservationExecutionOutcome(
                reloaded,
                "Observation review could not resolve campaign-native context.",
            )

        updated_context_refs = [f"signal:{signal.signal_id}" for signal in selected_signals]
        self._work_item_manager.update_status(
            campaign_id,
            work_item.work_item_id,
            status=WorkItemStatus.IN_PROGRESS,
            trigger_source=trigger_source,
            refresh_reason=refresh_reason.strip() or work_item.refresh_reason,
            context_refs=updated_context_refs,
        )
        refreshed_work_item = self._work_item_manager.get(campaign_id, work_item.work_item_id) or work_item
        review_result, operator_text = self._run_observation_review(
            observation_session,
            refreshed_work_item,
            selected_signals,
            trigger_source=trigger_source,
        )
        if review_result is None:
            self._work_item_manager.update_status(
                campaign_id,
                refreshed_work_item.work_item_id,
                status=WorkItemStatus.ESCALATED,
                result_summary="Observation review did not return a valid structured result.",
                escalation_reason="Observation review did not return a valid structured result.",
                trigger_source=trigger_source,
                refresh_reason="Observation review did not return a valid structured result.",
                context_refs=updated_context_refs,
            )
            reloaded = self._work_item_manager.get(campaign_id, refreshed_work_item.work_item_id)
            self._refresh_continuous_ops(session=observation_session)
            retry_message = operator_text.strip() or (
                "Observation review did not return a valid structured result. "
                "Please ask me to retry observation review."
            )
            return ObservationExecutionOutcome(reloaded, retry_message)

        if operator_text.strip():
            self._append_assistant_reply(observation_session, f"[Observation review] {operator_text.strip()}")

        self._promote_observation_memory_notes(observation_session, review_result)
        follow_on_actions = self._apply_observation_follow_on(observation_session, review_result)
        final_status = self._observation_work_status(review_result)
        summary = review_result.summary
        if follow_on_actions:
            summary = f"{summary} Follow-on: {', '.join(follow_on_actions)}."
        review_context_refs = [f"review:{review_result.review_id}", *updated_context_refs]
        if final_status is WorkItemStatus.REVIEW_PENDING:
            self._mark_review_pending(
                observation_session,
                refreshed_work_item,
                result_summary=summary,
                related_memory_refs=review_context_refs,
            )
        else:
            self._work_item_manager.update_status(
                campaign_id,
                refreshed_work_item.work_item_id,
                status=final_status,
                result_summary=summary,
                trigger_source=trigger_source,
                refresh_reason=review_result.review_reason,
                context_refs=review_context_refs,
                related_memory_refs=[f"review:{review_result.review_id}"],
            )
        reloaded = self._work_item_manager.get(campaign_id, refreshed_work_item.work_item_id)
        self._refresh_continuous_ops(session=observation_session)
        return ObservationExecutionOutcome(reloaded, operator_text.strip() or summary)

    def _handle_scheduled_observation_work(
        self,
        schedule: ScheduleRecord,
        *,
        now: datetime | None = None,
    ) -> WorkItemRecord | None:
        if self._schedule_manager is None:
            return None

        work_item = self.run_pending_observation_work(
            schedule.campaign_id,
            trigger_source="schedule",
            refresh_reason=f"Recurring schedule `{schedule.schedule_id}` triggered `observation` work.",
        )
        if work_item is None:
            self._schedule_manager.record_outcome(
                schedule.campaign_id,
                schedule.schedule_id,
                ran_at=now,
                metric_value=0,
                outcome_summary="Scheduled observation review found no new unresolved signals to review.",
            )
            self._refresh_continuous_ops(campaign_id=schedule.campaign_id)
            return None

        self._schedule_manager.record_outcome(
            schedule.campaign_id,
            schedule.schedule_id,
            ran_at=now,
            metric_value=len([ref for ref in work_item.context_refs if ref.startswith("signal:")]),
            outcome_summary=work_item.result_summary,
        )
        self._refresh_continuous_ops(campaign_id=schedule.campaign_id)
        return work_item

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
                trigger_source="schedule",
                refresh_reason=outcome.result_summary,
                context_refs=[f"schedule:{schedule.schedule_id}"],
            )
        else:
            self._work_item_manager.update_status(
                schedule.campaign_id,
                work_item.work_item_id,
                status=outcome.status,
                result_summary=outcome.result_summary,
                related_memory_refs=outcome.related_memory_refs,
                trigger_source="schedule",
                refresh_reason=outcome.result_summary,
                context_refs=[f"schedule:{schedule.schedule_id}"],
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
            trigger_source="schedule",
            refresh_reason=pause_reason,
            context_refs=[f"schedule:{schedule.schedule_id}"],
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
            account_capability=self._account_capability,
            community_capability=self._community_capability,
            membership_capability=self._membership_capability,
            messaging_capability=self._messaging_capability,
            monitor=self._monitor,
            runtime_broker=self._agent_runtime_broker,
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
            account_capability=self._account_capability,
            community_capability=self._community_capability,
            membership_capability=self._membership_capability,
            messaging_capability=self._messaging_capability,
            monitor=self._monitor,
            runtime_broker=self._agent_runtime_broker,
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
            community_capability=self._community_capability,
            membership_capability=self._membership_capability,
            messaging_capability=self._messaging_capability,
            monitor=self._monitor,
            runtime_broker=self._agent_runtime_broker,
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

    def _find_pending_observation_work_item(self, campaign_id: str) -> WorkItemRecord | None:
        if self._work_item_manager is None:
            return None
        return self._work_item_manager.find_latest(
            campaign_id,
            work_type=OBSERVATION_WORK_TYPE,
            owner_role=OBSERVATION_OWNER_ROLE,
            statuses={WorkItemStatus.PENDING, WorkItemStatus.IN_PROGRESS},
        )

    def _resolve_observation_signals(
        self,
        campaign_id: str,
        work_item: WorkItemRecord,
    ) -> list[CampaignSignalRecord]:
        if self._signal_manager is None:
            return []

        signal_ids = [
            ref.split(":", 1)[1]
            for ref in work_item.context_refs
            if ref.startswith("signal:") and ":" in ref
        ]
        selected_signals = [
            signal
            for signal_id in signal_ids
            if (signal := self._signal_manager.get(campaign_id, signal_id)) is not None
            and signal.review_eligible
            and signal.state.value == "unresolved"
        ]
        if selected_signals:
            return selected_signals[:OBSERVATION_SIGNAL_DIGEST_LIMIT]
        return self._signal_manager.select_review_batch(
            campaign_id,
            limit=OBSERVATION_SIGNAL_DIGEST_LIMIT,
        )

    def _build_observation_session(self, campaign_id: str) -> SessionRecord | None:
        if self._campaign_manager is None:
            return None
        return self._campaign_manager.build_background_session(
            campaign_id,
            stage=self._background_stage_for_campaign(campaign_id),
            summary="Observation review is using campaign-native context.",
        )

    def _background_stage_for_campaign(self, campaign_id: str) -> WorkflowStage:
        if self._campaign_manager is None:
            return WorkflowStage.DISCOVERY
        artifacts = self._campaign_manager.load_compatibility_artifacts(campaign_id)
        artifact_kinds = {artifact.kind for artifact in artifacts}
        if WorkflowArtifactKind.ACCOUNT_ASSIGNMENT_PLAN in artifact_kinds:
            return WorkflowStage.ACCOUNT_PLANNING
        if WorkflowArtifactKind.STRATEGY_PLAYBOOK in artifact_kinds:
            return WorkflowStage.STRATEGY
        if WorkflowArtifactKind.COMMUNITY_SHORTLIST in artifact_kinds:
            return WorkflowStage.DISCOVERY
        return WorkflowStage.INTAKE

    def _run_observation_review(
        self,
        session: SessionRecord,
        work_item: WorkItemRecord,
        selected_signals: list[CampaignSignalRecord],
        *,
        trigger_source: str,
    ) -> tuple[ObservationReviewResult | None, str]:
        if self._signal_manager is None:
            return None, ""

        from agents.observation.agent import ObservationReviewAgent

        signal_digests = [self._build_signal_digest(signal) for signal in selected_signals]
        latest_review = self._signal_manager.get_latest_review_result(session.campaign_id or "")
        trace_context = RuntimeTraceContext(
            trace_id=f"observation:{work_item.work_item_id}",
            user_id=session.operator_id,
            session_id=session.session_id,
        ).with_session(session)
        agent = ObservationReviewAgent(
            monitor=self._monitor,
            runtime_broker=self._agent_runtime_broker,
        )
        operator_text, brief = agent.run(
            session,
            review_reason=work_item.refresh_reason or work_item.goal,
            signal_digests=signal_digests,
            current_planning_work_summary=self._build_observation_planning_summary(session),
            last_review_summary=latest_review.summary if latest_review is not None else "",
            trace_context=trace_context,
        )
        if brief is None:
            return None, operator_text

        review_result = self._signal_manager.complete_review(
            session.campaign_id or "",
            work_item_id=work_item.work_item_id,
            trigger_source=trigger_source,
            review_reason=work_item.refresh_reason or work_item.goal,
            signal_ids=[signal.signal_id for signal in selected_signals],
            brief=brief,
        )
        return review_result, operator_text

    def _build_observation_planning_summary(self, session: SessionRecord) -> list[dict[str, str]]:
        if self._work_item_manager is None or not session.campaign_id:
            return []
        planning_items = [
            item
            for item in self._work_item_manager.list_open_for_campaign(session.campaign_id)
            if item.work_type in {STRATEGY_WORK_TYPE, ACCOUNT_PLANNING_WORK_TYPE}
        ]
        ordered = sorted(planning_items, key=lambda item: item.updated_at, reverse=True)
        return [
            {
                "work_type": item.work_type,
                "status": item.status.value,
                "goal": item.goal,
                "refresh_reason": item.refresh_reason,
                "result_summary": item.result_summary,
            }
            for item in ordered[:3]
        ]

    def _build_signal_digest(self, signal: CampaignSignalRecord) -> dict[str, object]:
        return {
            "signal_id": signal.signal_id,
            "signal_type": signal.signal_type,
            "severity": signal.severity.value,
            "summary": signal.summary,
            "source_kind": signal.source_kind,
            "source_ref": signal.source_ref,
            "account_id": signal.account_id,
            "community_id": signal.community_id,
            "conversation_id": signal.conversation_id,
            "occurrence_count": signal.occurrence_count,
            "first_happened_at": signal.first_happened_at.isoformat(),
            "last_happened_at": signal.last_happened_at.isoformat(),
            "last_reviewed_at": signal.last_reviewed_at.isoformat() if signal.last_reviewed_at else "",
            "context_refs": signal.context_refs[:3],
        }

    def _promote_observation_memory_notes(
        self,
        session: SessionRecord,
        review_result: ObservationReviewResult,
    ) -> None:
        if self._campaign_manager is None:
            return
        for index, line in enumerate(review_result.memory_note_lines[:3], start=1):
            normalized_line = line.strip()
            if not normalized_line:
                continue
            if self._compiled_intent_store is not None and self._compiled_intent_applicator is not None:
                compiled_intent = compile_memory_note(
                    review_result.campaign_id,
                    destination=NEXT_ACTIONS_DESTINATION,
                    line=normalized_line,
                    summary="Save an observation-review memory note.",
                    source_role="observation",
                    category="observation_review",
                    dedupe_key=f"{review_result.review_id}:{index}",
                    grounding_refs=[
                        f"campaign:{review_result.campaign_id}",
                        f"review:{review_result.review_id}",
                    ],
                )
                self._apply_persisted_compiled_intent(session, compiled_intent)
                continue
            self._campaign_manager.append_operational_note(
                review_result.campaign_id,
                destination=NEXT_ACTIONS_DESTINATION,
                line=normalized_line,
                category="observation_review",
                dedupe_key=f"{review_result.review_id}:{index}",
                recorded_at=review_result.created_at,
            )

    def _apply_observation_follow_on(
        self,
        session: SessionRecord,
        review_result: ObservationReviewResult,
    ) -> list[str]:
        actions_taken: list[str] = []
        for work_type in (STRATEGY_WORK_TYPE, ACCOUNT_PLANNING_WORK_TYPE):
            row = self._find_observation_work_item_change(review_result, work_type)
            action = self._resolve_observation_follow_on_action(review_result, work_type, row)
            if action is ObservationWorkItemChangeAction.NONE:
                continue
            if action is ObservationWorkItemChangeAction.CREATE_IF_MISSING and self._has_open_work_item(session, work_type):
                continue
            refreshed_item = self._refresh_work_item_from_observation(session, review_result, work_type)
            if refreshed_item is None:
                continue
            action_label = "refreshed" if action is ObservationWorkItemChangeAction.REFRESH else "created"
            actions_taken.append(f"{action_label} `{work_type}` work")
        return actions_taken

    def _refresh_work_item_from_observation(
        self,
        session: SessionRecord,
        review_result: ObservationReviewResult,
        work_type: str,
    ) -> WorkItemRecord | None:
        context_refs = [f"review:{review_result.review_id}", *self._related_refs_for_work_type(session, work_type)]
        existing_item = self._get_work_item_for_type(session, work_type)
        if self._compiled_intent_store is None or self._compiled_intent_applicator is None or not session.campaign_id:
            return self._ensure_work_item_for_type(
                session,
                work_type,
                status=WorkItemStatus.IN_PROGRESS,
                trigger_source="observation_review",
                refresh_reason=review_result.summary,
                context_refs=context_refs,
            )

        action = "refresh" if existing_item is not None else "propose"
        compiled_intent = compile_work_intent(
            session.campaign_id,
            action=action,
            work_payload={
                "owner_role": WORK_TYPE_TO_OWNER_ROLE[work_type],
                "work_type": work_type,
                "goal": self._build_stage_goal(session, work_type),
                "constraints": self._build_stage_constraints(session),
                "priority": WorkItemPriority.HIGH.value,
                "related_memory_refs": self._related_refs_for_work_type(session, work_type),
                "context_refs": context_refs,
                "trigger_source": "observation_review",
                "refresh_reason": review_result.summary,
                "status": WorkItemStatus.IN_PROGRESS.value,
            },
            source_role="observation",
            grounding_refs=[
                f"campaign:{review_result.campaign_id}",
                f"review:{review_result.review_id}",
            ],
            confidence=1.0,
        )
        if compiled_intent is None:
            return None
        self._apply_persisted_compiled_intent(session, compiled_intent)
        return self._get_work_item_for_type(session, work_type)

    def _find_observation_work_item_change(
        self,
        review_result: ObservationReviewResult,
        work_type: str,
    ) -> ObservationSuggestedWorkItemChange | None:
        desired_work_type = ObservationWorkItemType.STRATEGY
        if work_type == ACCOUNT_PLANNING_WORK_TYPE:
            desired_work_type = ObservationWorkItemType.ACCOUNT_PLANNING
        for change in review_result.suggested_work_item_changes:
            if change.work_type is desired_work_type:
                return change
        return None

    def _resolve_observation_follow_on_action(
        self,
        review_result: ObservationReviewResult,
        work_type: str,
        row: ObservationSuggestedWorkItemChange | None,
    ) -> ObservationWorkItemChangeAction:
        if review_result.recommended_next_step is ObservationRecommendedNextStep.OPERATOR_REVIEW:
            return ObservationWorkItemChangeAction.NONE

        if review_result.recommended_next_step is ObservationRecommendedNextStep.KEEP_CURRENT_PLAN:
            if row is not None and row.action is ObservationWorkItemChangeAction.CREATE_IF_MISSING:
                return ObservationWorkItemChangeAction.CREATE_IF_MISSING
            return ObservationWorkItemChangeAction.NONE

        target_step = ObservationRecommendedNextStep.REFRESH_STRATEGY
        if work_type == ACCOUNT_PLANNING_WORK_TYPE:
            target_step = ObservationRecommendedNextStep.REFRESH_ACCOUNT_PLANNING
        if review_result.recommended_next_step is not target_step:
            return ObservationWorkItemChangeAction.NONE
        if row is None:
            return ObservationWorkItemChangeAction.REFRESH
        if row.action is ObservationWorkItemChangeAction.REFRESH:
            return ObservationWorkItemChangeAction.REFRESH
        if row.action is ObservationWorkItemChangeAction.CREATE_IF_MISSING:
            return ObservationWorkItemChangeAction.CREATE_IF_MISSING
        return ObservationWorkItemChangeAction.NONE

    def _has_open_work_item(self, session: SessionRecord, work_type: str) -> bool:
        if self._work_item_manager is None or not session.campaign_id:
            return False
        return self._work_item_manager.find_latest(
            session.campaign_id,
            work_type=work_type,
            statuses=OPEN_WORK_ITEM_STATUSES,
        ) is not None

    def _observation_work_status(self, review_result: ObservationReviewResult) -> WorkItemStatus:
        if review_result.operator_attention_needed is ObservationOperatorAttention.NONE:
            return WorkItemStatus.COMPLETED
        return WorkItemStatus.REVIEW_PENDING

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
        trigger_source: str = "",
        refresh_reason: str = "",
        context_refs: list[str] | None = None,
    ) -> WorkItemRecord | None:
        if self._work_item_manager is None or not session.campaign_id:
            return None
        owner_role = WORK_TYPE_TO_OWNER_ROLE.get(work_type)
        if owner_role is None:
            return None
        resolved_context_refs = context_refs if context_refs is not None else self._related_refs_for_work_type(session, work_type)
        return self._work_item_manager.ensure_work_item(
            session.campaign_id,
            owner_role=owner_role,
            work_type=work_type,
            goal=self._build_stage_goal(session, work_type),
            constraints=self._build_stage_constraints(session),
            priority=WorkItemPriority.HIGH,
            related_memory_refs=self._related_refs_for_work_type(session, work_type),
            trigger_source=trigger_source,
            refresh_reason=refresh_reason,
            context_refs=resolved_context_refs,
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
        if self._compiled_intent_store is not None and self._compiled_intent_applicator is not None:
            compiled_intent = compile_review_request(
                session.campaign_id,
                review_payload={
                    "work_item_id": work_item.work_item_id,
                    "owner_role": work_item.owner_role,
                    "work_type": work_item.work_type,
                    "summary": result_summary,
                    "related_memory_refs": list(related_memory_refs or []),
                    "context_refs": list(related_memory_refs or []),
                },
                source_role="orchestrator",
                grounding_refs=self._build_control_grounding_refs(session),
            )
            if compiled_intent is not None:
                self._apply_persisted_compiled_intent(session, compiled_intent)
                return
        self._work_item_manager.update_status(
            session.campaign_id,
            work_item.work_item_id,
            status=WorkItemStatus.REVIEW_PENDING,
            result_summary=result_summary,
            related_memory_refs=related_memory_refs,
            context_refs=related_memory_refs,
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
        if self._compiled_intent_store is not None and self._compiled_intent_applicator is not None:
            compiled_intent = compile_work_intent(
                session.campaign_id,
                action="refresh",
                work_payload={
                    "owner_role": primary_work_item.owner_role,
                    "work_type": primary_work_item.work_type,
                    "goal": primary_work_item.goal,
                    "constraints": list(primary_work_item.constraints),
                    "priority": primary_work_item.priority.value,
                    "related_memory_refs": self._related_refs_for_work_type(session, work_type),
                    "context_refs": self._related_refs_for_work_type(session, work_type),
                    "trigger_source": "operator_feedback",
                    "refresh_reason": result_summary,
                    "status": WorkItemStatus.IN_PROGRESS.value,
                },
                source_role="orchestrator",
                grounding_refs=self._build_control_grounding_refs(session),
                confidence=1.0,
            )
            if compiled_intent is not None:
                self._apply_persisted_compiled_intent(session, compiled_intent)
                return
        self._work_item_manager.update_status(
            session.campaign_id,
            primary_work_item.work_item_id,
            status=WorkItemStatus.IN_PROGRESS,
            result_summary=result_summary,
            trigger_source="operator_feedback",
            refresh_reason=result_summary,
            context_refs=self._related_refs_for_work_type(session, work_type),
        )

    def _get_primary_work_item(self, session: SessionRecord) -> WorkItemRecord | None:
        if self._work_item_manager is None or not session.campaign_id:
            return None
        open_items = self._work_item_manager.list_open_for_campaign(session.campaign_id)
        if not open_items:
            return None
        return max(open_items, key=self._work_item_route_key)

    def _setup_requires_orchestrator_turn(
        self,
        session: SessionRecord,
        stage: WorkflowStage,
    ) -> bool:
        if stage is not WorkflowStage.INTAKE:
            return False
        return not setup_is_confirmed(get_campaign_setup_state(session))

    def _get_review_pending_planning_work_item(self, session: SessionRecord) -> WorkItemRecord | None:
        if self._work_item_manager is None or not session.campaign_id:
            return None
        review_pending_items = [
            item
            for item in self._work_item_manager.list_open_for_campaign(session.campaign_id)
            if item.work_type != OBSERVATION_WORK_TYPE and item.status is WorkItemStatus.REVIEW_PENDING
        ]
        if not review_pending_items:
            return None
        return max(review_pending_items, key=self._work_item_route_key)

    def _work_item_route_key(self, item: WorkItemRecord) -> tuple[int, int, datetime]:
        return (
            self._work_item_priority_rank(item.priority),
            self._work_item_status_rank(item.status),
            item.updated_at,
        )

    def _work_item_priority_rank(self, priority: WorkItemPriority) -> int:
        if priority is WorkItemPriority.HIGH:
            return 3
        if priority is WorkItemPriority.MEDIUM:
            return 2
        return 1

    def _work_item_status_rank(self, status: WorkItemStatus) -> int:
        if status is WorkItemStatus.REVIEW_PENDING:
            return 3
        if status is WorkItemStatus.IN_PROGRESS:
            return 2
        if status is WorkItemStatus.PENDING:
            return 1
        return 0

    def _build_observation_stage_summary(self, work_item: WorkItemRecord) -> str:
        if work_item.status is WorkItemStatus.ESCALATED:
            return "Observation review needs attention before planning continues."
        if "no new unresolved campaign signals" in work_item.result_summary.lower():
            return "Observation review found no new unresolved campaign signals."
        return "Observation review updated campaign priorities."

    def _get_work_item_for_type(
        self,
        session: SessionRecord,
        work_type: str,
    ) -> WorkItemRecord | None:
        if self._work_item_manager is None or not session.campaign_id:
            return None
        return self._work_item_manager.find_latest(session.campaign_id, work_type=work_type)

    def _follow_on_work_needs_refresh(
        self,
        session: SessionRecord,
        completed_work_type: str,
        follow_on_work_type: str,
    ) -> bool:
        follow_on_work_item = self._get_work_item_for_type(session, follow_on_work_type)
        if follow_on_work_item is None:
            return True
        if follow_on_work_item.status in {
            WorkItemStatus.PENDING,
            WorkItemStatus.IN_PROGRESS,
            WorkItemStatus.ESCALATED,
        }:
            return True
        prerequisite_artifact = self._get_latest_artifact_for_work_type(session, completed_work_type)
        follow_on_artifact = self._get_latest_artifact_for_work_type(session, follow_on_work_type)
        if prerequisite_artifact is None or follow_on_artifact is None:
            return True
        return follow_on_artifact.updated_at < prerequisite_artifact.updated_at

    def _get_latest_artifact_for_work_type(
        self,
        session: SessionRecord,
        work_type: str,
    ) -> WorkflowArtifact | None:
        if self._session_manager is None:
            return None
        return self._session_manager.get_latest_artifact_of_kind(
            session,
            _work_type_to_artifact_kind(work_type),
        )

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
        if work_item.refresh_reason:
            lines.append(f"Work item refresh reason: {work_item.refresh_reason}")
        if work_item.result_summary:
            lines.append(f"Current work item summary: {work_item.result_summary}")
        if normalized_message:
            lines.append(f"Operator follow-up: {normalized_message}")
        return "\n".join(lines).strip()

    def _review_prompt_for_work_type(self, session: SessionRecord, work_type: str) -> str:
        review_posture = self._latest_review_posture(session, work_type)
        if review_posture is not None:
            operator_prompt = str(review_posture.payload.get("operator_prompt", "")).strip()
            if operator_prompt:
                return operator_prompt
        return self._fallback_review_prompt_for_work_type(work_type)

    def _fallback_review_prompt_for_work_type(self, work_type: str) -> str:
        return {
            DISCOVERY_WORK_TYPE: "I have a shortlist ready. Tell me what to change, or tell me if you want me to move into strategy next.",
            STRATEGY_WORK_TYPE: "I have a strategy draft ready. Tell me what to change, or tell me if you want me to move into account planning next.",
            ACCOUNT_PLANNING_WORK_TYPE: "I have an account plan ready. Tell me what to change, or tell me when you want to lock this revision in.",
        }[work_type]

    def _up_to_date_prompt_for_work_type(self, session: SessionRecord, work_type: str) -> str:
        work_label = self._work_type_label(work_type).lower()
        return (
            f"The current {work_label} already matches the latest approved inputs. "
            f"{self._review_prompt_for_work_type(session, work_type)}"
        )

    def _approval_completion_prompt(self, session: SessionRecord, work_type: str) -> str:
        if work_type != ACCOUNT_PLANNING_WORK_TYPE:
            return "I saved that review outcome. Tell me what you want to refresh next."
        execution_state_impact = self._latest_execution_state_impact(session, work_type)
        activation_phrase = "activate"
        if execution_state_impact is not None:
            resolved_phrase = str(execution_state_impact.payload.get("activation_phrase", "")).strip()
            if resolved_phrase:
                activation_phrase = resolved_phrase
        return (
            "The account assignment plan is approved in chat. "
            f"Say `{activation_phrase}` when you want me to prepare live execution from this revision, "
            "or tell me what to refresh later."
        )

    def _work_type_label(self, work_type: str) -> str:
        return {
            DISCOVERY_WORK_TYPE: "Discovery",
            STRATEGY_WORK_TYPE: "Strategy",
            ACCOUNT_PLANNING_WORK_TYPE: "Account planning",
        }.get(work_type, work_type.replace("_", " ").title())

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

    def _invalidate_prepared_execution_for_latest_plan(self, session: SessionRecord) -> str:
        if self._prepared_execution_service is None:
            return ""
        if self._compiled_intent_store is not None and self._compiled_intent_applicator is not None and session.campaign_id:
            latest_plan = (
                self._session_manager.get_latest_artifact_of_kind(
                    session,
                    WorkflowArtifactKind.ACCOUNT_ASSIGNMENT_PLAN,
                )
                if self._session_manager is not None
                else None
            )
            compiled_intent = compile_prepared_execution_invalidation(
                session.campaign_id,
                invalidation_payload={
                    "reason": "A newer account-plan revision replaced the previously prepared execution state.",
                    "source_plan_artifact_id": latest_plan.artifact_id if latest_plan is not None else "",
                },
                source_role="orchestrator",
                grounding_refs=[
                    *self._build_control_grounding_refs(session),
                    *self._related_refs_for_session_artifact(session, WorkflowArtifactKind.ACCOUNT_ASSIGNMENT_PLAN),
                ],
                confidence=1.0,
            )
            return self._apply_persisted_compiled_intent(session, compiled_intent)
        invalidation = self._prepared_execution_service.invalidate_stale_prepared_state(session)
        if not invalidation.changed:
            return ""
        return (
            "The previously prepared execution state no longer matches this revised plan, so I invalidated the "
            f"older unstarted batch and cancelled {len(invalidation.cancelled_action_ids)} queued action(s). "
            "Approve this revision and say `activate` when you want me to prepare the latest version."
        )

    def _apply_schedule_action_from_output(
        self,
        session: SessionRecord,
        *,
        final_output_text: str,
        response_text: str,
    ) -> str:
        output_proposals = parse_output_proposal_list(final_output_text) or []
        actionable_proposals = [
            proposal
            for proposal in output_proposals
            if str(proposal.get("kind", "")).strip()
            in {
                "schedule.create",
                "schedule.pause",
                "schedule.resume",
                "live_action.enqueue_low_risk",
                "live_action.enqueue_operator_send",
            }
        ]
        if actionable_proposals:
            stripped_response = self._strip_output_proposals_block(response_text)
            if self._compiled_intent_store is not None and self._compiled_intent_applicator is not None and session.campaign_id:
                summaries = []
                compiled_intents = compile_output_proposals(
                    session.campaign_id,
                    actionable_proposals,
                    source_role="orchestrator",
                    grounding_refs=self._build_schedule_grounding_refs(session),
                )
                for compiled_intent in compiled_intents:
                    summaries.append(self._apply_persisted_compiled_intent(session, compiled_intent))
                if not summaries:
                    return stripped_response
                return self._append_runtime_note(
                    stripped_response,
                    "\n\n".join(summary for summary in summaries if summary.strip()),
                )

            legacy_schedule_proposals = [
                proposal
                for proposal in actionable_proposals
                if str(proposal.get("kind", "")).strip() in {"schedule.create", "schedule.pause", "schedule.resume"}
            ]
            if not legacy_schedule_proposals:
                return self._append_runtime_note(
                    stripped_response,
                    "I recognized a runtime action proposal, but compiled-intent execution is not available in this runtime yet.",
                )

            legacy_payload = self._legacy_schedule_action_from_output_proposal(legacy_schedule_proposals[0])
            validation_error = validate_schedule_action(legacy_payload)
            if validation_error is not None:
                return self._append_runtime_note(
                    stripped_response,
                    "I did not save the recurring schedule because the structured schedule action was incomplete. "
                    + validation_error,
                )
            summary = self._apply_schedule_action(session, legacy_payload)
            return self._append_runtime_note(stripped_response, summary)

        return response_text

    def _apply_schedule_action(
        self,
        session: SessionRecord,
        payload: dict[str, object],
    ) -> str:
        if self._compiled_intent_store is not None and self._compiled_intent_applicator is not None and session.campaign_id:
            return self._apply_compiled_schedule_action(session, payload)
        return self._apply_schedule_action_legacy(session, payload)

    def _apply_compiled_schedule_action(
        self,
        session: SessionRecord,
        payload: dict[str, object],
    ) -> str:
        if not session.campaign_id:
            return "Recurring schedule changes are not available in this runtime yet."

        compiled_intent = compile_schedule_action(
            session.campaign_id,
            payload,
            source_role="orchestrator",
            grounding_refs=self._build_schedule_grounding_refs(session),
        )
        if compiled_intent is None:
            return "I did not save the recurring schedule because the action payload was malformed."
        return self._apply_persisted_compiled_intent(session, compiled_intent)

    def _build_schedule_grounding_refs(self, session: SessionRecord) -> list[str]:
        refs = [f"session:{session.session_id}"]
        if session.campaign_id:
            refs.append(f"campaign:{session.campaign_id}")
        current_stage = get_workflow_snapshot(session).stage.value
        refs.append(f"workflow_stage:{current_stage}")
        latest_brief = get_campaign_brief_artifact(session)
        if latest_brief is not None:
            refs.append(f"artifact:{latest_brief.artifact_id}")
        return refs

    def _apply_schedule_action_legacy(
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

    def _append_capability_notice(self, response_text: str) -> str:
        notice = self._build_capability_notice()
        if not notice:
            return response_text
        if notice.lower() in response_text.lower():
            return response_text
        return self._append_runtime_note(response_text, notice)

    def _build_capability_notice(self) -> str:
        capability_summary = self._agent_runtime_broker.build_telegram_capability_summary()
        if not capability_summary or not capability_summary.get("operator_action_required"):
            return ""

        live_readiness = str(capability_summary.get("live_readiness", "")).strip()
        if live_readiness == "stubbed":
            return (
                "Runtime notice: live Telegram capability is still running in stub mode, so any live-search or "
                "live-account evidence is limited. Set `TELEGRAM_CAPABILITY_BACKEND=telethon` and run `/addaccount` "
                "to enable real Telegram reads."
            )
        if live_readiness == "no_accounts":
            return (
                "Runtime notice: the Telethon backend is enabled, but no managed Telegram accounts are onboarded "
                "yet. Run `/addaccount` so discovery, strategy, and execution can use live Telegram data."
            )
        summary = str(capability_summary.get("summary", "")).strip()
        next_step = str(capability_summary.get("next_step", "")).strip()
        return " ".join(part for part in [f"Runtime notice: {summary}" if summary else "", next_step] if part).strip()

    def _strip_output_proposals_block(self, output: str) -> str:
        return strip_marked_block(output, OUTPUT_PROPOSALS_JSON_MARKER)

    def _legacy_schedule_action_from_output_proposal(
        self,
        proposal: dict[str, object],
    ) -> dict[str, object]:
        kind = str(proposal.get("kind", "")).strip()
        schedule_payload = proposal.get("payload")
        action = kind.removeprefix("schedule.")
        return {
            "action": action,
            "schedule": dict(schedule_payload) if isinstance(schedule_payload, dict) else {},
        }

    def _refresh_continuous_ops(
        self,
        *,
        session: SessionRecord | None = None,
        campaign_id: str | None = None,
    ) -> None:
        if self._continuous_ops_manager is None:
            return
        if session is not None and session.campaign_id:
            self._continuous_ops_manager.refresh_for_session(session)
            return
        if campaign_id:
            self._continuous_ops_manager.refresh_for_campaign(campaign_id)

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
