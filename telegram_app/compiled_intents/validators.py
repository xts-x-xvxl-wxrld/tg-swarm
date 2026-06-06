"""Per-kind validation for compiled-intent records."""

from __future__ import annotations

from typing import Any

from telegram_app.compiled_intents.models import CompiledIntentRecord
from telegram_app.live_execution import LiveActionType
from telegram_app.models import WorkItemPriority, WorkItemStatus
from telegram_app.workflow_validation import validate_schedule_action

_SCOPE_VALUES = {"campaign", "account", "conversation", "review"}
_LOW_RISK_ACTION_TYPES = {
    LiveActionType.JOIN_COMMUNITY.value,
    LiveActionType.MARK_READ.value,
    LiveActionType.LEAVE_DIALOG.value,
}
_OPERATOR_SEND_ACTION_ALIASES = {
    "send_message": LiveActionType.SEND_GROUP_MESSAGE.value,
}
_OPERATOR_SEND_ACTION_TYPES = {
    LiveActionType.SEND_GROUP_MESSAGE.value,
    LiveActionType.SEND_GROUP_REPLY.value,
    LiveActionType.SEND_DM_REPLY.value,
}


def validate_compiled_intent(intent: CompiledIntentRecord) -> str | None:
    """Return an error message when a compiled intent is invalid."""
    if not intent.intent_id:
        return "Compiled intents must include `intent_id`."
    if not intent.campaign_id:
        return "Compiled intents must include `campaign_id`."
    if not intent.kind:
        return "Compiled intents must include `kind`."
    if not intent.summary:
        return "Compiled intents must include `summary`."

    return _validate_payload(intent.kind, intent.payload)


def _validate_payload(kind: str, payload: dict[str, Any]) -> str | None:
    if not isinstance(payload, dict):
        return "Compiled intent payload must be an object."

    if kind == "schedule.create":
        return validate_schedule_action({"action": "create", "schedule": payload})
    if kind == "schedule.pause":
        return validate_schedule_action({"action": "pause", "schedule": payload})
    if kind == "schedule.resume":
        return validate_schedule_action({"action": "resume", "schedule": payload})
    if kind in {"work.propose", "work.refresh"}:
        return _validate_work_payload(payload)
    if kind == "memory.note":
        return _validate_memory_note_payload(payload)
    if kind == "review.request":
        return _validate_review_request_payload(payload)
    if kind == "planning.review_posture":
        return _validate_planning_review_posture_payload(payload)
    if kind == "planning.follow_on_recommendation":
        return _validate_planning_follow_on_payload(payload)
    if kind == "planning.execution_state_impact":
        return _validate_planning_execution_state_payload(payload)
    if kind == "prepared_execution.invalidate_stale":
        return _validate_prepared_execution_invalidation_payload(payload)
    if kind == "conversation.update_belief_state":
        return _validate_belief_state_payload(payload)
    if kind == "engagement.next_move":
        return _validate_engagement_next_move_payload(payload)
    if kind == "live_action.enqueue_low_risk":
        return _validate_low_risk_live_action_payload(payload)
    if kind == "live_action.enqueue_operator_send":
        return _validate_operator_send_payload(payload)
    if kind in {"campaign_control.pause_scope", "campaign_control.resume_scope"}:
        return _validate_scope_payload(payload)
    if kind in {"campaign_control.approve_review", "campaign_control.dismiss_review"}:
        return _validate_review_control_payload(payload)
    if kind == "campaign_control.set_posture":
        return _validate_posture_payload(payload)
    if kind == "campaign_control.update_voice":
        return _validate_voice_payload(payload)
    if kind == "campaign_control.update_safeguard":
        return _validate_safeguard_payload(payload)
    if kind == "campaign_control.update_context":
        return _validate_context_payload(payload)
    return None


def _validate_work_payload(payload: dict[str, Any]) -> str | None:
    owner_role = str(payload.get("owner_role", "")).strip()
    work_type = str(payload.get("work_type", "")).strip()
    goal = str(payload.get("goal", "")).strip()
    priority = str(payload.get("priority", "")).strip().lower()
    requested_status = str(payload.get("status", "")).strip().lower()

    if not owner_role:
        return "Work intents must include `owner_role`."
    if not work_type:
        return "Work intents must include `work_type`."
    if not goal:
        return "Work intents must include `goal`."
    if priority and priority not in {member.value for member in WorkItemPriority}:
        return "Work intent `priority` must be `low`, `medium`, or `high` when provided."
    if requested_status and requested_status not in {
        WorkItemStatus.PENDING.value,
        WorkItemStatus.IN_PROGRESS.value,
    }:
        return "Work intent `status` must be `pending` or `in_progress` when provided."

    for field_name in ("constraints", "related_memory_refs", "context_refs"):
        value = payload.get(field_name)
        if value is not None and not isinstance(value, list):
            return f"Work intent `{field_name}` must be a list when provided."
    return None


def _validate_memory_note_payload(payload: dict[str, Any]) -> str | None:
    destination = str(payload.get("destination", "")).strip()
    line = str(payload.get("line", "")).strip()
    if not destination:
        return "Memory-note intents must include `destination`."
    if not line:
        return "Memory-note intents must include `line`."
    return None


def _validate_review_request_payload(payload: dict[str, Any]) -> str | None:
    summary = str(payload.get("summary", "")).strip()
    if not summary:
        return "Review-request intents must include `summary`."
    work_item_id = str(payload.get("work_item_id", "")).strip()
    owner_role = str(payload.get("owner_role", "")).strip()
    work_type = str(payload.get("work_type", "")).strip()
    if not work_item_id and not (owner_role and work_type):
        return (
            "Review-request intents must include `work_item_id`, or both `owner_role` and `work_type`."
        )
    context_refs = payload.get("context_refs")
    if context_refs is not None and not isinstance(context_refs, list):
        return "Review-request intent `context_refs` must be a list when provided."
    related_memory_refs = payload.get("related_memory_refs")
    if related_memory_refs is not None and not isinstance(related_memory_refs, list):
        return "Review-request intent `related_memory_refs` must be a list when provided."
    return None


def _validate_prepared_execution_invalidation_payload(payload: dict[str, Any]) -> str | None:
    reason = str(payload.get("reason", "")).strip()
    if not reason:
        return "Prepared-execution invalidation intents must include `reason`."
    source_plan_artifact_id = payload.get("source_plan_artifact_id")
    if source_plan_artifact_id is not None and not str(source_plan_artifact_id).strip():
        return "Prepared-execution invalidation intent `source_plan_artifact_id` must be non-empty when provided."
    return None


def _validate_planning_review_posture_payload(payload: dict[str, Any]) -> str | None:
    work_type = str(payload.get("work_type", "")).strip()
    review_state = str(payload.get("review_state", "")).strip()
    operator_prompt = str(payload.get("operator_prompt", "")).strip()
    if not work_type:
        return "Planning review-posture intents must include `work_type`."
    if review_state not in {"ready_for_review", "revision_requested", "approved"}:
        return "Planning review-posture intents must include a valid `review_state`."
    if not operator_prompt:
        return "Planning review-posture intents must include `operator_prompt`."
    return None


def _validate_planning_follow_on_payload(payload: dict[str, Any]) -> str | None:
    current_work_type = str(payload.get("current_work_type", "")).strip()
    next_work_type = str(payload.get("recommended_next_work_type", "")).strip()
    recommended_action = str(payload.get("recommended_action", "")).strip()
    if not current_work_type:
        return "Planning follow-on intents must include `current_work_type`."
    if not next_work_type:
        return "Planning follow-on intents must include `recommended_next_work_type`."
    if recommended_action not in {"prepare_next_family", "refresh_if_stale", "review_existing", "hold"}:
        return "Planning follow-on intents must include a valid `recommended_action`."
    return None


def _validate_planning_execution_state_payload(payload: dict[str, Any]) -> str | None:
    work_type = str(payload.get("work_type", "")).strip()
    recommended_action = str(payload.get("recommended_action", "")).strip()
    reason = str(payload.get("reason", "")).strip()
    if not work_type:
        return "Planning execution-state intents must include `work_type`."
    if recommended_action not in {"invalidate_prepared_execution_if_present", "await_operator_activation"}:
        return "Planning execution-state intents must include a valid `recommended_action`."
    if not reason:
        return "Planning execution-state intents must include `reason`."
    return None


def _validate_belief_state_payload(payload: dict[str, Any]) -> str | None:
    conversation_id = str(payload.get("conversation_id", "")).strip()
    if not conversation_id:
        return "Belief-state intents must include `conversation_id`."
    belief_state = payload.get("belief_state")
    if not isinstance(belief_state, dict):
        return "Belief-state intents must include a `belief_state` object."
    return None


def _validate_engagement_next_move_payload(payload: dict[str, Any]) -> str | None:
    conversation_id = str(payload.get("conversation_id", "")).strip()
    decision = str(payload.get("decision", "")).strip()
    if not conversation_id:
        return "Engagement next-move intents must include `conversation_id`."
    if not decision:
        return "Engagement next-move intents must include `decision`."
    return None


def _validate_low_risk_live_action_payload(payload: dict[str, Any]) -> str | None:
    account_id = str(payload.get("account_id", "")).strip()
    if not account_id:
        return "Low-risk live actions must include `account_id`."

    action_type = str(payload.get("action_type", "")).strip().lower()
    if action_type not in _LOW_RISK_ACTION_TYPES:
        if action_type in _OPERATOR_SEND_ACTION_TYPES or action_type in _OPERATOR_SEND_ACTION_ALIASES:
            return (
                "Outbound sends must use `live_action.enqueue_operator_send`, "
                "not `live_action.enqueue_low_risk`."
            )
        return "Low-risk live actions must use `join_community`, `mark_read`, or `leave_dialog` as `action_type`."

    if action_type == LiveActionType.JOIN_COMMUNITY.value:
        community_id = str(payload.get("community_id", "")).strip() or str(payload.get("chat_id", "")).strip()
        if not community_id:
            return "Join actions must include `community_id`."
        return None

    if action_type == LiveActionType.MARK_READ.value:
        if not str(payload.get("chat_id", "")).strip():
            return "Mark-read actions must include `chat_id`."
        return None

    peer_id = str(payload.get("peer_id", "")).strip() or str(payload.get("chat_id", "")).strip()
    if not peer_id:
        return "Leave-dialog actions must include `peer_id` or `chat_id`."
    return None


def _validate_operator_send_payload(payload: dict[str, Any]) -> str | None:
    account_id = str(payload.get("account_id", "")).strip()
    if not account_id:
        return "Operator-send intents must include `account_id`."

    raw_action_type = str(payload.get("action_type", "")).strip().lower()
    action_type = _OPERATOR_SEND_ACTION_ALIASES.get(raw_action_type, raw_action_type)
    if action_type not in _OPERATOR_SEND_ACTION_TYPES:
        return (
            "Operator-send intents must use `send_group_message`, `send_group_reply`, or `send_dm_reply` "
            "as `action_type`."
        )

    chat_id = str(payload.get("chat_id", "")).strip()
    if not chat_id:
        return "Operator-send intents must include `chat_id`."

    text = str(payload.get("text", ""))
    if not text.strip():
        return "Operator-send intents must include `text`."

    asset_refs = payload.get("asset_refs")
    if asset_refs is not None and not isinstance(asset_refs, list):
        return "Operator-send intent `asset_refs` must be a list when provided."

    if action_type in {LiveActionType.SEND_GROUP_REPLY.value, LiveActionType.SEND_DM_REPLY.value}:
        conversation_id = str(payload.get("conversation_id", "")).strip()
        reply_to_message_id = str(payload.get("reply_to_message_id", "")).strip()
        if not conversation_id and not reply_to_message_id:
            return (
                "Operator-send replies must include `conversation_id` or `reply_to_message_id`."
            )
    return None


def _validate_scope_payload(payload: dict[str, Any]) -> str | None:
    scope = str(payload.get("scope", "")).strip().lower()
    if scope not in _SCOPE_VALUES:
        return "Control intents must include a valid `scope`."
    return None


def _validate_review_control_payload(payload: dict[str, Any]) -> str | None:
    review_id = str(payload.get("review_id", "")).strip()
    if review_id:
        return None
    scope_error = _validate_scope_payload(payload)
    if scope_error is not None:
        return scope_error
    scope = str(payload.get("scope", "")).strip().lower()
    if scope != "review":
        return "Review-control intents must target the `review` scope when no `review_id` is provided."
    return None


def _validate_posture_payload(payload: dict[str, Any]) -> str | None:
    scope_error = _validate_scope_payload(payload)
    if scope_error is not None:
        return scope_error
    posture_field = str(payload.get("posture_field", "")).strip()
    if posture_field not in {"dm_reply_mode", "group_reply_mode", "group_outreach_mode"}:
        return (
            "Posture-update intents must include `dm_reply_mode`, `group_reply_mode`, "
            "or `group_outreach_mode` as `posture_field`."
        )
    requested_mode = str(payload.get("requested_mode", "")).strip()
    if requested_mode not in {"manual_only", "autonomous_allowed"}:
        return "Posture-update intents must include `manual_only` or `autonomous_allowed` as `requested_mode`."
    return None


def _validate_voice_payload(payload: dict[str, Any]) -> str | None:
    has_any_value = any(
        bool(str(value).strip()) if not isinstance(value, list) else any(str(item).strip() for item in value)
        for value in payload.values()
    )
    if not has_any_value:
        return "Voice-update intents must include at least one voice directive."
    return None


def _validate_safeguard_payload(payload: dict[str, Any]) -> str | None:
    instruction = str(payload.get("instruction", "")).strip() or str(payload.get("raw_text", "")).strip()
    if not instruction:
        return "Safeguard-update intents must include `instruction`."
    return None


def _validate_context_payload(payload: dict[str, Any]) -> str | None:
    meaningful_keys = (
        "operator_preferences",
        "voice_profile",
        "execution_constraints",
        "persistent_decisions",
        "open_ambiguities",
        "revision_threads",
    )
    has_meaningful_value = any(payload.get(key) not in ("", [], {}, None) for key in meaningful_keys)
    if not has_meaningful_value:
        return "Context-update intents must include at least one structured campaign-context field."
    return None
