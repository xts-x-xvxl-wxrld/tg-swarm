"""Helpers that normalize known runtime actions into compiled-intent records."""

from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from telegram_app.compiled_intents.models import (
    CompiledIntentRecord,
    CompiledIntentSafetyClass,
)
from telegram_app.external_conversations import ConversationBeliefState
from telegram_app.live_ops import LiveOpsIntent, LiveOpsIntentKind

_SCHEDULE_ACTION_TO_KIND = {
    "create": "schedule.create",
    "pause": "schedule.pause",
    "resume": "schedule.resume",
}
_LIVE_OPS_ACTION_TO_KIND = {
    LiveOpsIntentKind.APPROVE_REVIEW: "campaign_control.approve_review",
    LiveOpsIntentKind.DISMISS_REVIEW: "campaign_control.dismiss_review",
    LiveOpsIntentKind.PAUSE_SCOPE: "campaign_control.pause_scope",
    LiveOpsIntentKind.RESUME_SCOPE: "campaign_control.resume_scope",
    LiveOpsIntentKind.SET_POSTURE: "campaign_control.set_posture",
    LiveOpsIntentKind.UPDATE_VOICE: "campaign_control.update_voice",
    LiveOpsIntentKind.UPDATE_SAFEGUARD: "campaign_control.update_safeguard",
}
_OUTPUT_PROPOSAL_SAFETY_CLASS = {
    "schedule.create": CompiledIntentSafetyClass.SCHEDULE_MUTATION,
    "schedule.pause": CompiledIntentSafetyClass.SCHEDULE_MUTATION,
    "schedule.resume": CompiledIntentSafetyClass.SCHEDULE_MUTATION,
    "live_action.enqueue_low_risk": CompiledIntentSafetyClass.EXECUTION_ADJACENT,
    "live_action.enqueue_operator_send": CompiledIntentSafetyClass.EXECUTION_ADJACENT,
    "work.propose": CompiledIntentSafetyClass.STATE_MUTATION,
    "work.refresh": CompiledIntentSafetyClass.STATE_MUTATION,
    "memory.note": CompiledIntentSafetyClass.STATE_MUTATION,
    "review.request": CompiledIntentSafetyClass.STATE_MUTATION,
    "conversation.update_belief_state": CompiledIntentSafetyClass.STATE_MUTATION,
    "campaign_control.pause_scope": CompiledIntentSafetyClass.STATE_MUTATION,
    "campaign_control.resume_scope": CompiledIntentSafetyClass.STATE_MUTATION,
    "campaign_control.set_posture": CompiledIntentSafetyClass.STATE_MUTATION,
    "campaign_control.update_voice": CompiledIntentSafetyClass.STATE_MUTATION,
    "campaign_control.update_safeguard": CompiledIntentSafetyClass.STATE_MUTATION,
    "campaign_control.update_context": CompiledIntentSafetyClass.STATE_MUTATION,
    "prepared_execution.invalidate_stale": CompiledIntentSafetyClass.EXECUTION_ADJACENT,
}
_SPECIALIST_PROPOSAL_SAFETY_CLASS = {
    "planning.review_posture": CompiledIntentSafetyClass.ADVISORY,
    "planning.follow_on_recommendation": CompiledIntentSafetyClass.ADVISORY,
    "planning.execution_state_impact": CompiledIntentSafetyClass.EXECUTION_ADJACENT,
}


def build_compiled_intent(
    *,
    campaign_id: str,
    kind: str,
    summary: str,
    payload: dict[str, Any] | None,
    source_role: str,
    safety_class: CompiledIntentSafetyClass,
    grounding_refs: list[str] | None = None,
    confidence: float | None = None,
    ambiguity: str = "",
) -> CompiledIntentRecord:
    """Create one compiled-intent record from already structured meaning."""
    return CompiledIntentRecord(
        intent_id=str(uuid4()),
        campaign_id=campaign_id,
        kind=kind.strip(),
        summary=summary.strip(),
        payload=dict(payload or {}),
        grounding_refs=[
            str(value).strip()
            for value in grounding_refs or []
            if str(value).strip()
        ],
        source_role=source_role.strip(),
        confidence=confidence,
        ambiguity=ambiguity.strip(),
        safety_class=safety_class,
    )


def compile_schedule_action(
    campaign_id: str,
    action_payload: dict[str, Any],
    *,
    source_role: str,
    grounding_refs: list[str] | None = None,
) -> CompiledIntentRecord | None:
    """Compile one structured schedule action into the shared intent envelope."""
    action = str(action_payload.get("action", "")).strip().lower()
    kind = _SCHEDULE_ACTION_TO_KIND.get(action)
    schedule_payload = action_payload.get("schedule")
    if kind is None or not isinstance(schedule_payload, dict):
        return None

    return build_compiled_intent(
        campaign_id=campaign_id,
        kind=kind,
        summary=_build_schedule_summary(kind, schedule_payload),
        payload=schedule_payload,
        source_role=source_role,
        safety_class=CompiledIntentSafetyClass.SCHEDULE_MUTATION,
        grounding_refs=grounding_refs,
        confidence=1.0,
    )


def compile_work_intent(
    campaign_id: str,
    *,
    action: str,
    work_payload: dict[str, Any],
    source_role: str,
    grounding_refs: list[str] | None = None,
    confidence: float | None = 1.0,
) -> CompiledIntentRecord | None:
    """Compile one structured work proposal into the shared intent envelope."""
    normalized_action = action.strip().lower()
    if normalized_action not in {"propose", "refresh"}:
        return None
    if not isinstance(work_payload, dict):
        return None

    kind = f"work.{normalized_action}"
    return build_compiled_intent(
        campaign_id=campaign_id,
        kind=kind,
        summary=_build_work_summary(kind, work_payload),
        payload=work_payload,
        source_role=source_role,
        safety_class=CompiledIntentSafetyClass.STATE_MUTATION,
        grounding_refs=grounding_refs,
        confidence=confidence,
    )


def compile_memory_note(
    campaign_id: str,
    *,
    destination: str,
    line: str,
    source_role: str,
    grounding_refs: list[str] | None = None,
    confidence: float | None = 1.0,
    summary: str = "",
    category: str = "",
    dedupe_key: str = "",
) -> CompiledIntentRecord:
    """Compile one durable campaign-memory note into the shared intent envelope."""
    payload = {
        "destination": destination.strip(),
        "line": line.strip(),
        "category": category.strip(),
        "dedupe_key": dedupe_key.strip(),
    }
    resolved_summary = summary.strip() or f"Save a campaign memory note to `{payload['destination']}`."
    return build_compiled_intent(
        campaign_id=campaign_id,
        kind="memory.note",
        summary=resolved_summary,
        payload=payload,
        source_role=source_role,
        safety_class=CompiledIntentSafetyClass.STATE_MUTATION,
        grounding_refs=grounding_refs,
        confidence=confidence,
    )


def compile_review_request(
    campaign_id: str,
    *,
    review_payload: dict[str, Any],
    source_role: str,
    grounding_refs: list[str] | None = None,
    confidence: float | None = 1.0,
) -> CompiledIntentRecord | None:
    """Compile one specialist review-ready posture update into the shared intent envelope."""
    if not isinstance(review_payload, dict):
        return None
    summary = str(review_payload.get("summary", "")).strip()
    work_type = str(review_payload.get("work_type", "")).strip() or "work"
    resolved_summary = summary or f"Mark `{work_type}` work as ready for operator review."
    return build_compiled_intent(
        campaign_id=campaign_id,
        kind="review.request",
        summary=resolved_summary,
        payload=dict(review_payload),
        source_role=source_role,
        safety_class=CompiledIntentSafetyClass.STATE_MUTATION,
        grounding_refs=grounding_refs,
        confidence=confidence,
    )


def compile_conversation_belief_update(
    campaign_id: str,
    *,
    conversation_id: str,
    belief_state: ConversationBeliefState | dict[str, Any],
    source_role: str,
    grounding_refs: list[str] | None = None,
    confidence: float | None = 1.0,
    summary: str = "",
) -> CompiledIntentRecord:
    """Compile one deterministic belief-state persistence step for a reviewed conversation."""
    belief_payload = belief_state.to_dict() if isinstance(belief_state, ConversationBeliefState) else dict(belief_state)
    resolved_summary = summary.strip() or (
        str(belief_payload.get("last_meaningful_shift", "")).strip()
        or f"Update belief state for conversation `{conversation_id.strip()}`."
    )
    payload = {
        "conversation_id": conversation_id.strip(),
        "belief_state": belief_payload,
        "summary": resolved_summary,
    }
    return build_compiled_intent(
        campaign_id=campaign_id,
        kind="conversation.update_belief_state",
        summary=resolved_summary,
        payload=payload,
        source_role=source_role,
        safety_class=CompiledIntentSafetyClass.STATE_MUTATION,
        grounding_refs=grounding_refs,
        confidence=confidence,
    )


def compile_engagement_next_move(
    campaign_id: str,
    *,
    proposal_payload: dict[str, Any],
    source_role: str,
    grounding_refs: list[str] | None = None,
    confidence: float | None = 1.0,
) -> CompiledIntentRecord | None:
    """Compile one promoted-thread next-move proposal without authorizing execution."""
    if not isinstance(proposal_payload, dict):
        return None
    conversation_id = str(proposal_payload.get("conversation_id", "")).strip()
    decision = str(proposal_payload.get("decision", "")).strip()
    if not conversation_id or not decision:
        return None
    action_type = str(proposal_payload.get("action_type", "")).strip().lower()
    safety_class = (
        CompiledIntentSafetyClass.EXECUTION_ADJACENT
        if action_type and action_type != "none"
        else CompiledIntentSafetyClass.ADVISORY
    )
    goal = str(proposal_payload.get("goal", "")).strip()
    summary = f"Record the promoted-thread next move `{decision}` for conversation `{conversation_id}`."
    if goal:
        summary = f"{summary} Goal: {goal}."
    return build_compiled_intent(
        campaign_id=campaign_id,
        kind="engagement.next_move",
        summary=summary,
        payload=dict(proposal_payload),
        source_role=source_role,
        safety_class=safety_class,
        grounding_refs=grounding_refs,
        confidence=confidence,
    )


def compile_campaign_context_update(
    campaign_id: str,
    context_payload: dict[str, Any],
    *,
    summary: str,
    source_role: str,
    grounding_refs: list[str] | None = None,
    confidence: float | None = 1.0,
) -> CompiledIntentRecord | None:
    """Compile one structured campaign-context update into the shared intent envelope."""
    if not isinstance(context_payload, dict):
        return None

    return build_compiled_intent(
        campaign_id=campaign_id,
        kind="campaign_control.update_context",
        summary=summary,
        payload=context_payload,
        source_role=source_role,
        safety_class=CompiledIntentSafetyClass.STATE_MUTATION,
        grounding_refs=grounding_refs,
        confidence=confidence,
    )


def compile_specialist_proposal(
    campaign_id: str,
    *,
    proposal_payload: dict[str, Any],
    source_role: str,
    grounding_refs: list[str] | None = None,
) -> CompiledIntentRecord | None:
    """Compile one specialist advisory proposal into the shared intent envelope."""
    compiled_intent = compile_output_proposal(
        campaign_id,
        proposal_payload=proposal_payload,
        source_role=source_role,
        grounding_refs=grounding_refs,
    )
    if compiled_intent is None or not compiled_intent.kind.startswith("planning."):
        return None
    return compiled_intent


def compile_specialist_proposals(
    campaign_id: str,
    proposal_payloads: list[dict[str, Any]],
    *,
    source_role: str,
    grounding_refs: list[str] | None = None,
) -> list[CompiledIntentRecord]:
    """Compile multiple specialist advisory proposals from one output surface."""
    return [
        compiled_intent
        for compiled_intent in compile_output_proposals(
            campaign_id,
            proposal_payloads,
            source_role=source_role,
            grounding_refs=grounding_refs,
        )
        if compiled_intent.kind.startswith("planning.")
    ]


def compile_output_proposal(
    campaign_id: str,
    *,
    proposal_payload: dict[str, Any],
    source_role: str,
    grounding_refs: list[str] | None = None,
) -> CompiledIntentRecord | None:
    """Compile one shared output proposal into a compiled-intent record."""
    kind = str(proposal_payload.get("kind", "")).strip()
    payload = proposal_payload.get("payload")
    if not kind or not isinstance(payload, dict):
        return None

    summary = str(proposal_payload.get("summary", "")).strip() or _build_output_proposal_summary(kind, payload)
    confidence = proposal_payload.get("confidence")
    ambiguity = str(proposal_payload.get("ambiguity", "")).strip()
    resolved_confidence = float(confidence) if isinstance(confidence, (int, float)) else None

    if kind == "engagement.next_move":
        compiled_intent = compile_engagement_next_move(
            campaign_id,
            proposal_payload=payload,
            source_role=source_role,
            grounding_refs=grounding_refs,
            confidence=resolved_confidence,
        )
        if compiled_intent is None:
            return None
        if summary:
            compiled_intent.summary = summary
        if ambiguity:
            compiled_intent.ambiguity = ambiguity
        return compiled_intent

    safety_class = _SPECIALIST_PROPOSAL_SAFETY_CLASS.get(kind) or _OUTPUT_PROPOSAL_SAFETY_CLASS.get(kind)
    if safety_class is None:
        return None

    return build_compiled_intent(
        campaign_id=campaign_id,
        kind=kind,
        summary=summary,
        payload=payload,
        source_role=source_role,
        safety_class=safety_class,
        grounding_refs=grounding_refs,
        confidence=resolved_confidence,
        ambiguity=ambiguity,
    )


def compile_output_proposals(
    campaign_id: str,
    proposal_payloads: list[dict[str, Any]],
    *,
    source_role: str,
    grounding_refs: list[str] | None = None,
) -> list[CompiledIntentRecord]:
    """Compile multiple shared output proposals from one output surface."""
    compiled: list[CompiledIntentRecord] = []
    for proposal_payload in proposal_payloads:
        compiled_intent = compile_output_proposal(
            campaign_id,
            proposal_payload=proposal_payload,
            source_role=source_role,
            grounding_refs=grounding_refs,
        )
        if compiled_intent is not None:
            compiled.append(compiled_intent)
    return compiled


def compile_prepared_execution_invalidation(
    campaign_id: str,
    *,
    invalidation_payload: dict[str, Any] | None = None,
    source_role: str,
    grounding_refs: list[str] | None = None,
    confidence: float | None = 1.0,
) -> CompiledIntentRecord:
    """Compile one deterministic prepared-execution invalidation step."""
    payload = dict(invalidation_payload or {})
    reason = str(payload.get("reason", "")).strip() or "A newer account-plan revision replaced the prepared execution state."
    payload["reason"] = reason
    return build_compiled_intent(
        campaign_id=campaign_id,
        kind="prepared_execution.invalidate_stale",
        summary="Invalidate stale prepared execution state after an account-plan revision.",
        payload=payload,
        source_role=source_role,
        safety_class=CompiledIntentSafetyClass.EXECUTION_ADJACENT,
        grounding_refs=grounding_refs,
        confidence=confidence,
    )


def compile_live_ops_intent(
    campaign_id: str,
    intent: LiveOpsIntent,
    *,
    source_role: str,
    operator_id: str = "",
    grounding_refs: list[str] | None = None,
) -> CompiledIntentRecord | None:
    """Compile one deterministic live-ops control into the shared intent envelope."""
    kind = _LIVE_OPS_ACTION_TO_KIND.get(intent.kind)
    if kind is None:
        return None

    payload = {
        "scope": intent.scope.value,
        "raw_text": intent.raw_text.strip(),
        "operator_id": operator_id.strip(),
    }
    if intent.account_id.strip():
        payload["account_id"] = intent.account_id.strip()
    if intent.conversation_id.strip():
        payload["conversation_id"] = intent.conversation_id.strip()
    if intent.review_id.strip():
        payload["review_id"] = intent.review_id.strip()
    if intent.posture_field.strip():
        payload["posture_field"] = intent.posture_field.strip()
    if intent.requested_mode.strip():
        payload["requested_mode"] = intent.requested_mode.strip()
    if intent.kind is LiveOpsIntentKind.UPDATE_VOICE:
        payload.update(_build_voice_payload(intent.raw_text))
    if intent.kind is LiveOpsIntentKind.UPDATE_SAFEGUARD:
        instruction = _extract_safeguard_instruction(intent.raw_text)
        payload["instruction"] = instruction
        payload["label"] = _slugify_guardrail_label(instruction)

    return build_compiled_intent(
        campaign_id=campaign_id,
        kind=kind,
        summary=_build_live_ops_summary(kind, payload),
        payload=payload,
        source_role=source_role,
        safety_class=_live_ops_safety_class(intent.kind),
        grounding_refs=grounding_refs,
        confidence=1.0,
    )


def compile_live_ops_intents(
    campaign_id: str,
    intents: list[LiveOpsIntent],
    *,
    source_role: str,
    operator_id: str = "",
    grounding_refs: list[str] | None = None,
) -> list[CompiledIntentRecord]:
    """Compile multiple live-ops controls from one operator turn."""
    compiled: list[CompiledIntentRecord] = []
    for intent in intents:
        compiled_intent = compile_live_ops_intent(
            campaign_id,
            intent,
            source_role=source_role,
            operator_id=operator_id,
            grounding_refs=grounding_refs,
        )
        if compiled_intent is not None:
            compiled.append(compiled_intent)
    return compiled


def _build_schedule_summary(kind: str, schedule_payload: dict[str, Any]) -> str:
    work_type = str(schedule_payload.get("work_type", "")).strip()
    owner_role = str(schedule_payload.get("owner_role", "")).strip()
    schedule_id = str(schedule_payload.get("schedule_id", "")).strip()

    if kind == "schedule.create":
        interval_minutes = int(schedule_payload.get("interval_minutes", 0) or 0)
        return (
            f"Create a recurring `{work_type}` schedule for the `{owner_role}` role every "
            f"{interval_minutes} minute(s)."
        )
    if kind == "schedule.pause":
        if schedule_id:
            return f"Pause recurring schedule `{schedule_id}`."
        return f"Pause the recurring `{work_type}` schedule."
    if schedule_id:
        return f"Resume recurring schedule `{schedule_id}`."
    return f"Resume the recurring `{work_type}` schedule."


def _build_live_ops_summary(kind: str, payload: dict[str, Any]) -> str:
    scope = str(payload.get("scope", "campaign")).strip() or "campaign"
    if kind == "campaign_control.pause_scope":
        return f"Pause the `{scope}` live-ops scope."
    if kind == "campaign_control.resume_scope":
        return f"Resume the `{scope}` live-ops scope."
    if kind == "campaign_control.set_posture":
        field = str(payload.get("posture_field", "")).strip() or "reply_posture"
        mode = str(payload.get("requested_mode", "")).strip() or "manual_only"
        return f"Set `{field}` to `{mode}`."
    if kind == "campaign_control.update_voice":
        return "Update the campaign live-reply voice guidance."
    if kind == "campaign_control.update_safeguard":
        return "Update the campaign live-reply safeguard guidance."
    if kind == "campaign_control.approve_review":
        review_id = str(payload.get("review_id", "")).strip()
        return f"Approve review `{review_id}`." if review_id else "Approve the pending review."
    if kind == "campaign_control.dismiss_review":
        review_id = str(payload.get("review_id", "")).strip()
        return f"Dismiss review `{review_id}`." if review_id else "Dismiss the pending review."
    return "Apply a live-ops control update."


def _build_work_summary(kind: str, payload: dict[str, Any]) -> str:
    work_type = str(payload.get("work_type", "")).strip() or "work"
    owner_role = str(payload.get("owner_role", "")).strip() or "worker"
    if kind == "work.propose":
        return f"Propose `{work_type}` work for the `{owner_role}` role."
    return f"Refresh `{work_type}` work for the `{owner_role}` role."


def _build_specialist_proposal_summary(kind: str, payload: dict[str, Any]) -> str:
    if kind == "planning.review_posture":
        work_type = str(payload.get("work_type", "")).strip() or "planning"
        return f"Record operator-review posture for `{work_type}` output."
    if kind == "planning.follow_on_recommendation":
        next_work_type = str(payload.get("recommended_next_work_type", "")).strip() or "follow_on"
        action = str(payload.get("recommended_action", "")).strip() or "review"
        return f"Record a `{action}` follow-on recommendation for `{next_work_type}`."
    if kind == "planning.execution_state_impact":
        action = str(payload.get("recommended_action", "")).strip() or "review_execution_state"
        return f"Record execution-state impact `{action}` for the latest plan."
    return "Record a specialist advisory proposal."


def _build_output_proposal_summary(kind: str, payload: dict[str, Any]) -> str:
    if kind in _SPECIALIST_PROPOSAL_SAFETY_CLASS:
        return _build_specialist_proposal_summary(kind, payload)
    if kind in {"schedule.create", "schedule.pause", "schedule.resume"}:
        return _build_schedule_summary(kind, payload)
    if kind == "live_action.enqueue_low_risk":
        action_type = str(payload.get("action_type", "")).strip() or "action"
        account_id = str(payload.get("account_id", "")).strip() or "account"
        return f"Queue low-risk live action `{action_type}` for `{account_id}`."
    if kind == "live_action.enqueue_operator_send":
        action_type = str(payload.get("action_type", "")).strip() or "send_group_message"
        account_id = str(payload.get("account_id", "")).strip() or "account"
        return f"Queue operator-approved live send `{action_type}` for `{account_id}`."
    if kind in {"work.propose", "work.refresh"}:
        return _build_work_summary(kind, payload)
    if kind.startswith("campaign_control."):
        return _build_live_ops_summary(kind, payload)
    if kind == "prepared_execution.invalidate_stale":
        return "Invalidate stale prepared execution state after an account-plan revision."
    if kind == "review.request":
        work_type = str(payload.get("work_type", "")).strip() or "work"
        return f"Mark `{work_type}` work as ready for operator review."
    if kind == "memory.note":
        destination = str(payload.get("destination", "")).strip() or "campaign_memory"
        return f"Save a campaign memory note to `{destination}`."
    if kind == "conversation.update_belief_state":
        conversation_id = str(payload.get("conversation_id", "")).strip()
        return (
            f"Update belief state for conversation `{conversation_id}`."
            if conversation_id
            else "Update conversation belief state."
        )
    return "Record a compiled runtime proposal."


def _live_ops_safety_class(kind: LiveOpsIntentKind) -> CompiledIntentSafetyClass:
    if kind in {LiveOpsIntentKind.APPROVE_REVIEW, LiveOpsIntentKind.DISMISS_REVIEW}:
        return CompiledIntentSafetyClass.EXECUTION_ADJACENT
    return CompiledIntentSafetyClass.STATE_MUTATION


def _build_voice_payload(message: str) -> dict[str, Any]:
    normalized = message.strip().lower()
    if not normalized:
        return {}

    tone_descriptors: list[str] = []
    style_do: list[str] = []
    style_avoid: list[str] = []
    cta_style = ""
    emoji_policy = ""
    evidence_style = ""

    if "warmer" in normalized or "friendlier" in normalized:
        tone_descriptors.append("warmer")
    if "more direct" in normalized or "direct" in normalized:
        tone_descriptors.append("direct")
        style_do.append("answer more directly")
    if "less salesy" in normalized or "less pushy" in normalized:
        style_avoid.append("salesy language")
    if "less hypey" in normalized or "less hype" in normalized:
        style_avoid.append("hype-heavy language")
    if "more concise" in normalized:
        style_do.append("keep replies concise")
    if "concise" in normalized or "shorter" in normalized or "short chat" in normalized:
        style_do.append("keep replies concise")
    if "telegram-native" in normalized or "telegram native" in normalized or "short chat messages" in normalized:
        style_do.append("keep replies like short Telegram chat messages")
    if (
        "less punctuation" in normalized
        or "minimal punctuation" in normalized
        or "avoid too much punctuation" in normalized
        or "not too much punctuation" in normalized
    ):
        style_do.append("use minimal punctuation")
    if (
        "no prose" in normalized
        or "not prose" in normalized
        or "less prose" in normalized
        or "less polished" in normalized
        or "not polished" in normalized
    ):
        style_avoid.append("polished prose")
    if "not writers" in normalized or "not writerly" in normalized:
        style_avoid.append("writerly phrasing")
    if "no em dash" in normalized or "no em dashes" in normalized or "avoid em dash" in normalized:
        style_avoid.append("em dashes")
    if "no emoji" in normalized or "no emojis" in normalized or "avoid emoji" in normalized:
        style_avoid.append("emoji greetings")
        emoji_policy = "none"
    if "not corny" in normalized or "no corny" in normalized or "avoid corny" in normalized:
        style_avoid.append("corny openers")
    if "no quick question for the room" in normalized or "avoid quick question for the room" in normalized:
        style_avoid.append("room-addressing hooks")
    if "no hey everyone" in normalized or "avoid hey everyone" in normalized:
        style_avoid.append("room-addressing hooks")
    if "corporate filler" in normalized or "not corporate" in normalized:
        style_avoid.append("corporate filler")
    if "online service" in normalized or "service" in normalized:
        style_do.append("frame value around the online service naturally")
    if (
        "not car salesman" in normalized
        or "not a salesman" in normalized
        or "not salesmen" in normalized
        or "hard sell" in normalized
        or "hard-sell" in normalized
    ):
        style_avoid.append("hard close language")
    if "soft question" in normalized:
        cta_style = "soft_question"

    payload: dict[str, Any] = {}
    if tone_descriptors:
        payload["tone_descriptors"] = tone_descriptors
    if style_do:
        payload["style_do"] = style_do
    if style_avoid:
        payload["style_avoid"] = style_avoid
    if cta_style:
        payload["cta_style"] = cta_style
    if emoji_policy:
        payload["emoji_policy"] = emoji_policy
    if evidence_style:
        payload["evidence_style"] = evidence_style
    return payload


def _slugify_guardrail_label(instruction: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", instruction.lower()).strip("_")
    if normalized:
        return normalized[:48]
    return "operator_guardrail"


def _extract_safeguard_instruction(message: str) -> str:
    normalized = message.strip()
    if not normalized:
        return ""
    lowered = normalized.lower()
    for cue in ("do not mention", "don't mention"):
        start = lowered.find(cue)
        if start < 0:
            continue
        conditioned_segment = lowered[start:]
        if "unless asked" in conditioned_segment:
            end = start + conditioned_segment.find("unless asked") + len("unless asked")
            return normalized[start:end].strip(" ,.")
        return re.split(r"[,.!?;]", normalized[start:], maxsplit=1)[0].strip(" ,.")
    return normalized
