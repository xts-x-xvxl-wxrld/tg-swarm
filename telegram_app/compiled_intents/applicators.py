"""Narrow deterministic applicators for accepted compiled intents."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from telegram_app.campaign_memory.operational_notes import NEXT_ACTIONS_DESTINATION
from telegram_app.campaigns import CampaignManager
from telegram_app.compiled_intents.models import CompiledIntentRecord
from telegram_app.external_conversations import ConversationBeliefState, ExternalConversationManager
from telegram_app.live_execution import LiveActionRecord, LiveActionType, LiveExecutionService
from telegram_app.live_execution.policy import LiveActionPolicyDecisionType
from telegram_app.live_ops import LiveOpsIntent, LiveOpsIntentKind, LiveOpsScope, LiveOpsService
from telegram_app.models import ScheduleStatus, WorkItemPriority, WorkItemStatus
from telegram_app.prepared_execution import PreparedExecutionService
from telegram_app.scheduling import ScheduleManager
from telegram_app.work_items import WorkItemManager


class CompiledIntentApplicationError(RuntimeError):
    """Raised when a compiled intent cannot be applied safely."""


class CompiledIntentApplicator:
    """Route accepted compiled intents into existing runtime managers."""

    def __init__(
        self,
        *,
        schedule_manager: ScheduleManager | None = None,
        work_item_manager: WorkItemManager | None = None,
        campaign_manager: CampaignManager | None = None,
        conversation_manager: ExternalConversationManager | None = None,
        live_ops_service: LiveOpsService | None = None,
        live_execution_service: LiveExecutionService | None = None,
        prepared_execution_service: PreparedExecutionService | None = None,
    ) -> None:
        self._schedule_manager = schedule_manager
        self._work_item_manager = work_item_manager
        self._campaign_manager = campaign_manager
        self._conversation_manager = conversation_manager
        self._live_ops_service = live_ops_service
        self._live_execution_service = live_execution_service
        self._prepared_execution_service = prepared_execution_service

    def apply(self, intent: CompiledIntentRecord) -> str:
        """Apply one accepted compiled intent and return a human-readable result."""
        if intent.kind == "schedule.create":
            return self._create_schedule(intent)
        if intent.kind == "schedule.pause":
            return self._change_schedule_state(intent, status=ScheduleStatus.PAUSED)
        if intent.kind == "schedule.resume":
            return self._change_schedule_state(intent, status=ScheduleStatus.ACTIVE)
        if intent.kind == "work.propose":
            return self._ensure_work_item(intent, status=WorkItemStatus.PENDING, verb="Proposed")
        if intent.kind == "work.refresh":
            return self._ensure_work_item(intent, status=WorkItemStatus.IN_PROGRESS, verb="Refreshed")
        if intent.kind == "memory.note":
            return self._append_memory_note(intent)
        if intent.kind == "review.request":
            return self._mark_review_requested(intent)
        if intent.kind == "prepared_execution.invalidate_stale":
            return self._invalidate_prepared_execution(intent)
        if intent.kind == "conversation.update_belief_state":
            return self._update_conversation_belief_state(intent)
        if intent.kind == "engagement.next_move":
            return self._record_engagement_next_move(intent)
        if intent.kind == "live_action.enqueue_low_risk":
            return self._enqueue_low_risk_live_action(intent)
        if intent.kind == "live_action.enqueue_operator_send":
            return self._enqueue_operator_send_live_action(intent)
        if intent.kind.startswith("campaign_control."):
            return self._apply_live_ops_control(intent)
        raise CompiledIntentApplicationError(
            f"Compiled intent kind `{intent.kind}` does not have an applicator yet."
        )

    def _create_schedule(self, intent: CompiledIntentRecord) -> str:
        if self._schedule_manager is None:
            raise CompiledIntentApplicationError("Recurring schedule changes are not available in this runtime yet.")

        payload = intent.payload
        raw_priority = str(payload.get("priority", WorkItemPriority.MEDIUM.value)).strip().lower()
        priority = WorkItemPriority._value2member_map_.get(raw_priority, WorkItemPriority.MEDIUM)
        raw_constraints = payload.get("constraints", [])
        schedule = self._schedule_manager.create_interval_schedule(
            intent.campaign_id,
            owner_role=str(payload.get("owner_role", "")).strip(),
            work_type=str(payload.get("work_type", "")).strip(),
            goal=str(payload.get("goal", "")).strip(),
            interval_minutes=int(payload.get("interval_minutes", 0) or 0),
            constraints=_string_list(raw_constraints),
            priority=priority,
            evaluation_metric=str(payload.get("evaluation_metric", "")).strip(),
            minimum_value=_optional_int(payload.get("minimum_value")),
            pause_after_consecutive_misses=_optional_int(payload.get("pause_after_consecutive_misses")),
        )
        cadence = _humanize_interval_minutes(schedule.interval_minutes)
        return (
            f"Saved a recurring `{schedule.work_type}` schedule for the `{schedule.owner_role}` role {cadence}. "
            f"Next run is {schedule.next_run_at.isoformat()}."
        )

    def _change_schedule_state(
        self,
        intent: CompiledIntentRecord,
        *,
        status: ScheduleStatus,
    ) -> str:
        if self._schedule_manager is None:
            raise CompiledIntentApplicationError("Recurring schedule changes are not available in this runtime yet.")

        schedule = self._resolve_schedule_target(intent.campaign_id, intent.payload, status=status)
        if schedule is None:
            raise CompiledIntentApplicationError("I could not find the requested recurring schedule to update.")

        updated = self._schedule_manager.update_status(
            intent.campaign_id,
            schedule.schedule_id,
            status=status,
            reset_next_run_at=status is ScheduleStatus.ACTIVE,
        )
        if updated is None:
            raise CompiledIntentApplicationError("I could not update the requested recurring schedule.")
        if status is ScheduleStatus.ACTIVE:
            return (
                f"Resumed the recurring `{updated.work_type}` schedule. "
                f"Next run is {updated.next_run_at.isoformat()}."
            )
        return f"Paused the recurring `{updated.work_type}` schedule."

    def _ensure_work_item(
        self,
        intent: CompiledIntentRecord,
        *,
        status: WorkItemStatus,
        verb: str,
    ) -> str:
        if self._work_item_manager is None:
            raise CompiledIntentApplicationError("Work-item changes are not available in this runtime yet.")

        payload = intent.payload
        resolved_status = _work_item_status(payload.get("status"), default=status)
        raw_priority = str(payload.get("priority", WorkItemPriority.MEDIUM.value)).strip().lower()
        priority = WorkItemPriority._value2member_map_.get(raw_priority, WorkItemPriority.MEDIUM)
        due_at = _optional_datetime(payload.get("due_at"))
        work_item = self._work_item_manager.ensure_work_item(
            intent.campaign_id,
            owner_role=str(payload.get("owner_role", "")).strip(),
            work_type=str(payload.get("work_type", "")).strip(),
            goal=str(payload.get("goal", "")).strip(),
            constraints=_string_list(payload.get("constraints", [])),
            priority=priority,
            due_at=due_at,
            related_memory_refs=_string_list(payload.get("related_memory_refs", [])),
            trigger_source=str(payload.get("trigger_source", "")).strip() or "compiled_intent",
            refresh_reason=str(payload.get("refresh_reason", "")).strip() or intent.summary,
            context_refs=_string_list(payload.get("context_refs", [])),
            schedule_id=str(payload.get("schedule_id", "")).strip() or None,
            status=resolved_status,
        )
        if work_item.status is not resolved_status:
            updated_work_item = self._work_item_manager.update_status(
                intent.campaign_id,
                work_item.work_item_id,
                status=resolved_status,
                trigger_source=str(payload.get("trigger_source", "")).strip() or None,
                refresh_reason=str(payload.get("refresh_reason", "")).strip() or None,
                context_refs=_string_list(payload.get("context_refs", [])),
            )
            if updated_work_item is not None:
                work_item = updated_work_item
        return f"{verb} `{work_item.work_type}` work for the `{work_item.owner_role}` role."

    def _append_memory_note(self, intent: CompiledIntentRecord) -> str:
        if self._campaign_manager is None:
            raise CompiledIntentApplicationError("Campaign memory updates are not available in this runtime yet.")

        payload = intent.payload
        destination = str(payload.get("destination", "")).strip() or NEXT_ACTIONS_DESTINATION
        line = str(payload.get("line", "")).strip()
        campaign = self._campaign_manager.get(intent.campaign_id)
        if campaign is None:
            raise CompiledIntentApplicationError("I could not find the campaign workspace for that memory note.")

        self._campaign_manager.append_operational_note(
            intent.campaign_id,
            destination=destination,
            line=line,
            category=str(payload.get("category", "")).strip() or "compiled_intent",
            dedupe_key=str(payload.get("dedupe_key", "")).strip() or f"compiled-intent:{intent.intent_id}",
            recorded_at=datetime.now(UTC),
        )
        return f"Saved a campaign memory note to `{destination}`."

    def _mark_review_requested(self, intent: CompiledIntentRecord) -> str:
        if self._work_item_manager is None:
            raise CompiledIntentApplicationError("Review-request updates are not available in this runtime yet.")

        payload = intent.payload
        work_item = self._resolve_review_request_target(intent.campaign_id, payload)
        if work_item is None:
            raise CompiledIntentApplicationError("I could not find the requested work item to mark for review.")

        summary = str(payload.get("summary", "")).strip() or intent.summary
        updated = self._work_item_manager.update_status(
            intent.campaign_id,
            work_item.work_item_id,
            status=WorkItemStatus.REVIEW_PENDING,
            result_summary=summary,
            related_memory_refs=_string_list(payload.get("related_memory_refs", [])),
            context_refs=_string_list(payload.get("context_refs", [])),
        )
        if updated is None:
            raise CompiledIntentApplicationError("I could not update the requested work item for review.")
        return f"Marked `{updated.work_type}` work as ready for operator review."

    def _update_conversation_belief_state(self, intent: CompiledIntentRecord) -> str:
        if self._conversation_manager is None:
            raise CompiledIntentApplicationError("Conversation belief-state updates are not available in this runtime yet.")

        payload = intent.payload
        conversation_id = str(payload.get("conversation_id", "")).strip()
        raw_belief_state = payload.get("belief_state", {})
        if not conversation_id or not isinstance(raw_belief_state, dict):
            raise CompiledIntentApplicationError("The belief-state update payload was incomplete.")

        belief_state = ConversationBeliefState.from_dict(raw_belief_state)
        summary = str(payload.get("summary", "")).strip() or belief_state.last_meaningful_shift
        updated = self._conversation_manager.update_belief_state(
            intent.campaign_id,
            conversation_id,
            belief_state=belief_state,
            summary=summary,
        )
        if updated is None:
            raise CompiledIntentApplicationError("I could not find the requested conversation to update.")
        return f"Updated belief state for conversation `{conversation_id}`."

    def _invalidate_prepared_execution(self, intent: CompiledIntentRecord) -> str:
        if self._prepared_execution_service is None:
            raise CompiledIntentApplicationError(
                "Prepared-execution invalidation is not available in this runtime yet."
            )

        invalidation = self._prepared_execution_service.invalidate_stale_prepared_state_for_campaign(intent.campaign_id)
        if not invalidation.changed:
            return ""

        cancelled_count = len(invalidation.cancelled_action_ids)
        return (
            "The previously prepared execution state no longer matches this revised plan, so I invalidated the "
            "older unstarted batch and cancelled "
            f"{cancelled_count} queued action(s). Approve this revision and say `activate` when you want me to "
            "prepare the latest version."
        )

    def _record_engagement_next_move(self, intent: CompiledIntentRecord) -> str:
        conversation_id = str(intent.payload.get("conversation_id", "")).strip()
        decision = str(intent.payload.get("decision", "")).strip() or "next_move"
        if conversation_id:
            return f"Recorded the promoted-thread `{decision}` proposal for conversation `{conversation_id}`."
        return f"Recorded the promoted-thread `{decision}` proposal."

    def _enqueue_low_risk_live_action(self, intent: CompiledIntentRecord) -> str:
        if self._live_execution_service is None:
            raise CompiledIntentApplicationError("Low-risk live execution is not available in this runtime yet.")

        candidate = self._build_low_risk_candidate(intent)
        policy_decision = self._live_execution_service.evaluate_policy(candidate)
        if policy_decision.decision is LiveActionPolicyDecisionType.BLOCKED:
            raise CompiledIntentApplicationError(policy_decision.summary)

        next_attempt_at = None
        if (
            policy_decision.decision is LiveActionPolicyDecisionType.COOLDOWN
            and policy_decision.cooldown_until is not None
        ):
            next_attempt_at = policy_decision.cooldown_until

        action = self._live_execution_service.enqueue_action(
            intent.campaign_id,
            candidate.account_id,
            action_type=candidate.action_type,
            payload=candidate.payload,
            conversation_id=candidate.conversation_id,
            idempotency_key=str(intent.payload.get("idempotency_key", "")).strip(),
            source_plan_artifact_id=str(intent.payload.get("source_plan_artifact_id", "")).strip(),
            next_attempt_at=next_attempt_at,
        )
        if next_attempt_at is not None:
            return (
                f"Queued low-risk action `{action.action_type.value}` for `{action.account_id}` and deferred it until "
                f"{next_attempt_at.isoformat()}."
            )
        return f"Queued low-risk action `{action.action_type.value}` for `{action.account_id}`."

    def _enqueue_operator_send_live_action(self, intent: CompiledIntentRecord) -> str:
        if self._live_execution_service is None:
            raise CompiledIntentApplicationError("Operator-approved live sends are not available in this runtime yet.")

        candidate = self._build_operator_send_candidate(intent)
        policy_decision = self._live_execution_service.evaluate_policy(candidate)
        if policy_decision.decision is LiveActionPolicyDecisionType.BLOCKED:
            raise CompiledIntentApplicationError(policy_decision.summary)

        next_attempt_at = None
        if (
            policy_decision.decision is LiveActionPolicyDecisionType.COOLDOWN
            and policy_decision.cooldown_until is not None
        ):
            next_attempt_at = policy_decision.cooldown_until

        action = self._live_execution_service.enqueue_action(
            intent.campaign_id,
            candidate.account_id,
            action_type=candidate.action_type,
            payload=candidate.payload,
            conversation_id=candidate.conversation_id,
            idempotency_key=str(intent.payload.get("idempotency_key", "")).strip() or f"compiled-intent:{intent.intent_id}",
            source_plan_artifact_id=str(intent.payload.get("source_plan_artifact_id", "")).strip(),
            next_attempt_at=next_attempt_at,
        )
        if next_attempt_at is not None:
            return (
                f"Queued operator-approved send `{action.action_type.value}` for `{action.account_id}` and deferred it "
                f"until {next_attempt_at.isoformat()}."
            )
        return f"Queued operator-approved send `{action.action_type.value}` for `{action.account_id}`."

    def _build_low_risk_candidate(self, intent: CompiledIntentRecord) -> LiveActionRecord:
        payload = intent.payload
        raw_action_type = str(payload.get("action_type", "")).strip().lower()
        action_type = LiveActionType._value2member_map_.get(raw_action_type)
        if action_type not in {
            LiveActionType.JOIN_COMMUNITY,
            LiveActionType.MARK_READ,
            LiveActionType.LEAVE_DIALOG,
        }:
            raise CompiledIntentApplicationError("Only join, mark-read, and leave-dialog low-risk actions are supported.")

        account_id = str(payload.get("account_id", "")).strip()
        if not account_id:
            raise CompiledIntentApplicationError("Low-risk live actions must include `payload.account_id`.")

        conversation_id = str(payload.get("conversation_id", "")).strip()
        action_payload = self._build_low_risk_action_payload(action_type, payload)
        return LiveActionRecord(
            action_id=str(uuid4()),
            campaign_id=intent.campaign_id,
            account_id=account_id,
            action_type=action_type,
            payload=action_payload,
            conversation_id=conversation_id,
        )

    def _build_operator_send_candidate(self, intent: CompiledIntentRecord) -> LiveActionRecord:
        payload = intent.payload
        raw_action_type = str(payload.get("action_type", "")).strip().lower()
        action_type = _normalize_operator_send_action_type(raw_action_type)
        if action_type not in {
            LiveActionType.SEND_GROUP_MESSAGE,
            LiveActionType.SEND_GROUP_REPLY,
            LiveActionType.SEND_DM_REPLY,
        }:
            raise CompiledIntentApplicationError(
                "Operator-approved sends must use `send_group_message`, `send_group_reply`, or `send_dm_reply`."
            )

        account_id = str(payload.get("account_id", "")).strip()
        if not account_id:
            raise CompiledIntentApplicationError("Operator-approved sends must include `payload.account_id`.")

        conversation_id = self._operator_send_conversation_id(action_type, payload)
        action_payload = self._build_operator_send_action_payload(
            intent,
            action_type=action_type,
            conversation_id=conversation_id,
        )
        return LiveActionRecord(
            action_id=str(uuid4()),
            campaign_id=intent.campaign_id,
            account_id=account_id,
            action_type=action_type,
            payload=action_payload,
            conversation_id=conversation_id,
        )

    def _build_low_risk_action_payload(
        self,
        action_type: LiveActionType,
        payload: dict[str, Any],
    ) -> dict[str, object]:
        if action_type is LiveActionType.JOIN_COMMUNITY:
            community_id = str(payload.get("community_id", "")).strip() or str(payload.get("chat_id", "")).strip()
            if not community_id:
                raise CompiledIntentApplicationError("Join actions must include `payload.community_id`.")
            return {"community_id": community_id}

        if action_type is LiveActionType.MARK_READ:
            chat_id = str(payload.get("chat_id", "")).strip()
            if not chat_id:
                raise CompiledIntentApplicationError("Mark-read actions must include `payload.chat_id`.")
            message_id = str(payload.get("message_id", "")).strip()
            result: dict[str, object] = {"chat_id": chat_id}
            if message_id:
                result["message_id"] = message_id
            return result

        peer_id = str(payload.get("peer_id", "")).strip() or str(payload.get("chat_id", "")).strip()
        if not peer_id:
            raise CompiledIntentApplicationError("Leave-dialog actions must include `payload.peer_id` or `payload.chat_id`.")
        return {"peer_id": peer_id}

    def _build_operator_send_action_payload(
        self,
        intent: CompiledIntentRecord,
        *,
        action_type: LiveActionType,
        conversation_id: str,
    ) -> dict[str, object]:
        payload = intent.payload
        chat_id = str(payload.get("chat_id", "")).strip()
        text = str(payload.get("text", ""))
        if not chat_id or not text.strip():
            raise CompiledIntentApplicationError(
                "Operator-approved sends must include both `payload.chat_id` and `payload.text`."
            )

        action_payload: dict[str, object] = {
            "chat_id": chat_id,
            "text": text,
            "approval_context": self._build_operator_send_approval_context(
                intent,
                action_type=action_type,
                conversation_id=conversation_id,
            ),
        }
        reply_to_message_id = str(payload.get("reply_to_message_id", "")).strip()
        if action_type in {LiveActionType.SEND_GROUP_REPLY, LiveActionType.SEND_DM_REPLY}:
            if not conversation_id and not reply_to_message_id:
                raise CompiledIntentApplicationError(
                    "Operator-approved replies must include `payload.conversation_id` or `payload.reply_to_message_id`."
                )
            if reply_to_message_id:
                action_payload["reply_to_message_id"] = reply_to_message_id

        raw_asset_refs = payload.get("asset_refs", [])
        if isinstance(raw_asset_refs, list):
            asset_refs = [str(value).strip() for value in raw_asset_refs if str(value).strip()]
            if asset_refs:
                action_payload["asset_refs"] = asset_refs
        return action_payload

    def _operator_send_conversation_id(
        self,
        action_type: LiveActionType,
        payload: dict[str, Any],
    ) -> str:
        if action_type is LiveActionType.SEND_GROUP_MESSAGE:
            return ""
        return str(payload.get("conversation_id", "")).strip()

    def _build_operator_send_approval_context(
        self,
        intent: CompiledIntentRecord,
        *,
        action_type: LiveActionType,
        conversation_id: str,
    ) -> dict[str, object]:
        approved_by = str(intent.payload.get("operator_id", "")).strip() or "operator_via_orchestrator"
        approval_context: dict[str, object] = {
            "approved": True,
            "approval_mode": "operator",
            "approval_source": "compiled_intent_orchestrator",
            "approved_by": approved_by,
            "campaign_id": intent.campaign_id,
            "intent_id": intent.intent_id,
            "authorized_action_type": action_type.value,
            "authorized_at": datetime.now(UTC).isoformat(),
            "summary": intent.summary,
        }
        if conversation_id:
            approval_context["conversation_id"] = conversation_id
        return approval_context

    def _apply_live_ops_control(self, intent: CompiledIntentRecord) -> str:
        if self._live_ops_service is None:
            raise CompiledIntentApplicationError("Live-ops controls are not available in this runtime yet.")

        payload = intent.payload
        raw_scope = str(payload.get("scope", "")).strip().lower()
        scope = LiveOpsScope._value2member_map_.get(raw_scope, LiveOpsScope.CAMPAIGN)
        raw_text = str(payload.get("raw_text", "")).strip()
        if intent.kind == "campaign_control.update_safeguard":
            raw_text = str(payload.get("instruction", "")).strip() or raw_text
        live_ops_intent = LiveOpsIntent(
            kind=_intent_kind_from_compiled_kind(intent.kind),
            scope=scope,
            raw_text=raw_text,
            campaign_id=intent.campaign_id,
            account_id=str(payload.get("account_id", "")).strip(),
            conversation_id=str(payload.get("conversation_id", "")).strip(),
            review_id=str(payload.get("review_id", "")).strip(),
            posture_field=str(payload.get("posture_field", "")).strip(),
            requested_mode=str(payload.get("requested_mode", "")).strip(),
        )
        operator_id = str(payload.get("operator_id", "")).strip()
        return self._live_ops_service.handle_campaign_intent(
            intent.campaign_id,
            live_ops_intent,
            operator_id=operator_id,
        )

    def _resolve_schedule_target(
        self,
        campaign_id: str,
        payload: dict[str, Any],
        *,
        status: ScheduleStatus,
    ):
        if self._schedule_manager is None:
            return None

        schedule_id = str(payload.get("schedule_id", "")).strip()
        if schedule_id:
            return self._schedule_manager.get(campaign_id, schedule_id)

        work_type = str(payload.get("work_type", "")).strip() or None
        owner_role = str(payload.get("owner_role", "")).strip() or None
        desired_status = ScheduleStatus.ACTIVE if status is ScheduleStatus.PAUSED else ScheduleStatus.PAUSED
        return self._schedule_manager.find_latest(
            campaign_id,
            work_type=work_type,
            owner_role=owner_role,
            statuses={desired_status},
        )

    def _resolve_review_request_target(
        self,
        campaign_id: str,
        payload: dict[str, Any],
    ):
        if self._work_item_manager is None:
            return None

        work_item_id = str(payload.get("work_item_id", "")).strip()
        if work_item_id:
            return self._work_item_manager.get(campaign_id, work_item_id)

        work_type = str(payload.get("work_type", "")).strip() or None
        owner_role = str(payload.get("owner_role", "")).strip() or None
        return self._work_item_manager.find_latest(
            campaign_id,
            work_type=work_type,
            owner_role=owner_role,
            statuses={
                WorkItemStatus.PENDING,
                WorkItemStatus.IN_PROGRESS,
                WorkItemStatus.REVIEW_PENDING,
                WorkItemStatus.ESCALATED,
            },
        )


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _optional_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return datetime.fromisoformat(value)


def _work_item_status(value: object, *, default: WorkItemStatus) -> WorkItemStatus:
    if not isinstance(value, str) or not value.strip():
        return default
    return WorkItemStatus._value2member_map_.get(value.strip().lower(), default)


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _humanize_interval_minutes(interval_minutes: int) -> str:
    if interval_minutes % 10080 == 0:
        weeks = interval_minutes // 10080
        return f"every {weeks} week{'s' if weeks != 1 else ''}"
    if interval_minutes % 1440 == 0:
        days = interval_minutes // 1440
        return f"every {days} day{'s' if days != 1 else ''}"
    if interval_minutes % 60 == 0:
        hours = interval_minutes // 60
        return f"every {hours} hour{'s' if hours != 1 else ''}"
    return f"every {interval_minutes} minute{'s' if interval_minutes != 1 else ''}"


def _intent_kind_from_compiled_kind(kind: str) -> LiveOpsIntentKind:
    mapping = {
        "campaign_control.approve_review": LiveOpsIntentKind.APPROVE_REVIEW,
        "campaign_control.dismiss_review": LiveOpsIntentKind.DISMISS_REVIEW,
        "campaign_control.pause_scope": LiveOpsIntentKind.PAUSE_SCOPE,
        "campaign_control.resume_scope": LiveOpsIntentKind.RESUME_SCOPE,
        "campaign_control.set_posture": LiveOpsIntentKind.SET_POSTURE,
        "campaign_control.update_voice": LiveOpsIntentKind.UPDATE_VOICE,
        "campaign_control.update_safeguard": LiveOpsIntentKind.UPDATE_SAFEGUARD,
    }
    live_ops_kind = mapping.get(kind)
    if live_ops_kind is None:
        raise CompiledIntentApplicationError(f"Compiled intent kind `{kind}` is not a supported live-ops control.")
    return live_ops_kind


def _normalize_operator_send_action_type(raw_action_type: str) -> LiveActionType | None:
    normalized = raw_action_type.strip().lower()
    if normalized == "send_message":
        normalized = LiveActionType.SEND_GROUP_MESSAGE.value
    return LiveActionType._value2member_map_.get(normalized)
