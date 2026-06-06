"""Deterministic live-ops chat surface for status, controls, and review resolution."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
import re
from typing import Iterable

from telegram_app.autonomous_send import (
    AutonomousSendManager,
    AutonomousSendMode,
    AutonomousSendReviewStatus,
    AutonomousSendService,
)
from telegram_app.campaign_context import (
    OPEN_AMBIGUITIES_KEY,
    VOICE_AVOID_TRAITS_KEY,
    VOICE_CTA_PREFERENCES_KEY,
    VOICE_PREFERRED_TRAITS_KEY,
    VOICE_PROFILE_KEY,
    VOICE_STYLE_NOTES_KEY,
)
from telegram_app.campaigns import CampaignManager
from telegram_app.continuous_ops import ContinuousOpsManager
from telegram_app.external_conversations import ExternalConversationManager, ExternalConversationStatus
from telegram_app.live_execution import LiveActionStatus, LiveExecutionPolicyStateManager, LiveExecutionService
from telegram_app.live_ops.formatter import format_block_reason, format_review_list, format_snapshot
from telegram_app.live_ops.manager import LiveOpsControlManager
from telegram_app.live_ops.models import (
    AttentionItem,
    CampaignLiveOpsSnapshot,
    ControlAreaState,
    ControlCompletenessStatus,
    LiveOpsIntent,
    LiveOpsIntentKind,
    LiveOpsScope,
    OperatorApprovedClaim,
    OperatorGuardrail,
)
from telegram_app.models import SessionRecord, WorkflowArtifact, WorkflowArtifactKind
from telegram_app.prepared_execution import PreparedExecutionManager

_REVIEW_ID_PATTERN = re.compile(r"\b(review-[a-z0-9_-]+)\b", re.IGNORECASE)
_CONVERSATION_ID_PATTERN = re.compile(r"\b(conv-[a-z0-9_-]+)\b", re.IGNORECASE)
_ACCOUNT_ID_PATTERN = re.compile(r"\baccount(?:\s+|[`'\"]?)([a-z0-9_-]+)\b", re.IGNORECASE)
_VOICE_CUE_PATTERN = re.compile(r"\b(tone|voice|salesy|warmer|direct|friendlier|pushy|hypey|formal|casual)\b")


class LiveOpsService:
    """Compose live runtime status and control actions behind one chat surface."""

    def __init__(
        self,
        *,
        campaign_manager: CampaignManager,
        continuous_ops_manager: ContinuousOpsManager | None,
        control_manager: LiveOpsControlManager,
        autonomous_send_manager: AutonomousSendManager,
        autonomous_send_service: AutonomousSendService,
        conversation_manager: ExternalConversationManager,
        live_execution_service: LiveExecutionService,
        live_execution_policy_state_manager: LiveExecutionPolicyStateManager,
        prepared_execution_manager: PreparedExecutionManager,
    ) -> None:
        self._campaign_manager = campaign_manager
        self._continuous_ops_manager = continuous_ops_manager
        self._control_manager = control_manager
        self._autonomous_send_manager = autonomous_send_manager
        self._autonomous_send_service = autonomous_send_service
        self._conversation_manager = conversation_manager
        self._live_execution_service = live_execution_service
        self._live_execution_policy_state_manager = live_execution_policy_state_manager
        self._prepared_execution_manager = prepared_execution_manager

    def detect_intents(self, operator_message: str) -> list[LiveOpsIntent]:
        """Return all explicit live-ops intents detected in one operator message."""
        normalized = _normalize_text(operator_message).lower()
        if not normalized:
            return []

        review_id = _extract_match(_REVIEW_ID_PATTERN, operator_message)
        conversation_id = _extract_match(_CONVERSATION_ID_PATTERN, operator_message)
        account_id = _extract_account_id(operator_message)

        if any(token in normalized for token in ("approve that review", "approve review", "approve that draft", "approve draft")):
            return [LiveOpsIntent(
                kind=LiveOpsIntentKind.APPROVE_REVIEW,
                scope=LiveOpsScope.REVIEW,
                raw_text=operator_message,
                review_id=review_id,
            )]
        if any(token in normalized for token in ("dismiss that review", "dismiss review", "dismiss that draft", "dismiss draft")):
            return [LiveOpsIntent(
                kind=LiveOpsIntentKind.DISMISS_REVIEW,
                scope=LiveOpsScope.REVIEW,
                raw_text=operator_message,
                review_id=review_id,
            )]
        if "pending autonomous review" in normalized or "pending autonomous reviews" in normalized:
            return [LiveOpsIntent(kind=LiveOpsIntentKind.SHOW_PENDING_REVIEWS, raw_text=operator_message)]
        if "why was this blocked" in normalized or "why is this blocked" in normalized:
            return [LiveOpsIntent(
                kind=LiveOpsIntentKind.SHOW_BLOCK_REASON,
                raw_text=operator_message,
                review_id=review_id,
                conversation_id=conversation_id,
            )]
        if any(token in normalized for token in ("show me what needs attention", "what needs attention", "show attention", "what needs me right now")):
            return [LiveOpsIntent(kind=LiveOpsIntentKind.SHOW_ATTENTION, raw_text=operator_message)]
        if any(token in normalized for token in ("what is blocked right now", "what's blocked right now", "show blocked", "what is blocked")):
            return [LiveOpsIntent(kind=LiveOpsIntentKind.SHOW_BLOCKED, raw_text=operator_message)]
        if any(token in normalized for token in ("show live status", "show status", "show readiness", "live readiness", "control readiness", "what is still unset", "what is still untouched")):
            return [LiveOpsIntent(kind=LiveOpsIntentKind.SHOW_STATUS, raw_text=operator_message)]

        intents: list[LiveOpsIntent] = []
        posture_intent = self._detect_posture_intent(normalized, operator_message)
        if posture_intent is not None:
            intents.append(posture_intent)

        pause_intent = self._detect_pause_or_resume_intent(normalized, operator_message, account_id, conversation_id)
        if pause_intent is not None:
            intents.append(pause_intent)

        if ("do not mention" in normalized or "don't mention" in normalized or "unless asked" in normalized) and (
            "price" in normalized or "pricing" in normalized or "mention" in normalized
        ):
            intents.append(LiveOpsIntent(kind=LiveOpsIntentKind.UPDATE_SAFEGUARD, raw_text=operator_message))

        if _VOICE_CUE_PATTERN.search(normalized) and any(token in normalized for token in ("tone", "voice", "update", "make", "less", "more")):
            intents.append(LiveOpsIntent(kind=LiveOpsIntentKind.UPDATE_VOICE, raw_text=operator_message))
        return intents

    def detect_intent(self, operator_message: str) -> LiveOpsIntent | None:
        """Return the first explicit live-ops intent for compatibility callers."""
        intents = self.detect_intents(operator_message)
        return intents[0] if intents else None

    def handle_intent(
        self,
        session: SessionRecord,
        intent: LiveOpsIntent,
        *,
        operator_id: str,
    ) -> str:
        """Apply one parsed live-ops intent and return Telegram-facing copy."""
        campaign_id = session.campaign_id or intent.campaign_id
        if not campaign_id:
            return "This session does not have a campaign attached yet, so I cannot control live ops from here."
        self._refresh_continuous_ops(session)
        return self.handle_campaign_intent(campaign_id, intent, operator_id=operator_id)

    def handle_campaign_intent(
        self,
        campaign_id: str,
        intent: LiveOpsIntent,
        *,
        operator_id: str,
    ) -> str:
        """Apply one parsed live-ops intent when the campaign is already known."""
        intent = replace(intent, campaign_id=campaign_id)
        self._refresh_continuous_ops_for_campaign(campaign_id)

        if intent.kind is LiveOpsIntentKind.SHOW_STATUS:
            snapshot = self._build_snapshot(campaign_id)
            return format_snapshot(
                snapshot,
                headline=f"Campaign `{campaign_id}` is `{snapshot.campaign_status}`.",
                include_attention=True,
                include_control_gaps=True,
            )
        if intent.kind is LiveOpsIntentKind.SHOW_ATTENTION:
            snapshot = self._build_snapshot(campaign_id)
            return format_snapshot(
                snapshot,
                headline=f"Attention queue for `{campaign_id}`.",
                include_attention=True,
                include_control_gaps=True,
            )
        if intent.kind is LiveOpsIntentKind.SHOW_BLOCKED:
            snapshot = self._build_snapshot(campaign_id)
            blocked_details = snapshot.blocked_reasons or [item.summary for item in snapshot.attention_items if "blocked" in item.item_type]
            detail_text = "\n".join(f"- {detail}" for detail in blocked_details[:5]) or "No blocked live items right now."
            return format_block_reason(
                f"Blocked state for `{campaign_id}`.",
                detail_text,
                next_step=snapshot.recommended_next_action,
            )
        if intent.kind is LiveOpsIntentKind.SHOW_BLOCK_REASON:
            return self._explain_block_reason(campaign_id, intent)
        if intent.kind is LiveOpsIntentKind.SHOW_PENDING_REVIEWS:
            return self._show_pending_reviews(campaign_id)
        if intent.kind is LiveOpsIntentKind.PAUSE_SCOPE:
            return self._pause_scope(campaign_id, intent)
        if intent.kind is LiveOpsIntentKind.RESUME_SCOPE:
            return self._resume_scope(campaign_id, intent)
        if intent.kind is LiveOpsIntentKind.SET_POSTURE:
            return self._set_posture(campaign_id, intent, operator_id=operator_id)
        if intent.kind is LiveOpsIntentKind.APPROVE_REVIEW:
            return self._approve_review(campaign_id, intent, operator_id=operator_id)
        if intent.kind is LiveOpsIntentKind.DISMISS_REVIEW:
            return self._dismiss_review(campaign_id, intent, operator_id=operator_id)
        if intent.kind is LiveOpsIntentKind.UPDATE_VOICE:
            return self._update_voice(campaign_id, intent, operator_id=operator_id)
        if intent.kind is LiveOpsIntentKind.UPDATE_SAFEGUARD:
            return self._update_safeguard(campaign_id, intent, operator_id=operator_id)
        return "I understood that as a live-ops request, but this control path is not available yet."

    def _detect_posture_intent(self, normalized: str, operator_message: str) -> LiveOpsIntent | None:
        field = ""
        if "group outreach" in normalized or "group messages" in normalized or "outbound group" in normalized:
            field = "group_outreach_mode"
        elif "dm" in normalized or "direct message" in normalized:
            field = "dm_reply_mode"
        elif "group repl" in normalized or "group reply" in normalized:
            field = "group_reply_mode"
        elif "autonomous replies" in normalized:
            field = "dm_reply_mode"
        if not field:
            return None

        if any(token in normalized for token in ("stop", "disable", "turn off", "manual", "manually")):
            return LiveOpsIntent(
                kind=LiveOpsIntentKind.SET_POSTURE,
                scope=LiveOpsScope.CAMPAIGN,
                raw_text=operator_message,
                posture_field=field,
                requested_mode=AutonomousSendMode.MANUAL_ONLY.value,
            )
        if any(token in normalized for token in ("let", "enable", "turn on", "run automatically", "automatically", "automatic")):
            return LiveOpsIntent(
                kind=LiveOpsIntentKind.SET_POSTURE,
                scope=LiveOpsScope.CAMPAIGN,
                raw_text=operator_message,
                posture_field=field,
                requested_mode=AutonomousSendMode.AUTONOMOUS_ALLOWED.value,
            )
        return None

    def _detect_pause_or_resume_intent(
        self,
        normalized: str,
        operator_message: str,
        account_id: str,
        conversation_id: str,
    ) -> LiveOpsIntent | None:
        if not (normalized.startswith("pause") or normalized.startswith("resume")):
            return None
        kind = LiveOpsIntentKind.PAUSE_SCOPE if normalized.startswith("pause") else LiveOpsIntentKind.RESUME_SCOPE
        if "campaign" in normalized or "this campaign" in normalized:
            return LiveOpsIntent(kind=kind, scope=LiveOpsScope.CAMPAIGN, raw_text=operator_message)
        if "conversation" in normalized or "this thread" in normalized:
            return LiveOpsIntent(
                kind=kind,
                scope=LiveOpsScope.CONVERSATION,
                raw_text=operator_message,
                conversation_id=conversation_id,
            )
        if "account" in normalized:
            return LiveOpsIntent(
                kind=kind,
                scope=LiveOpsScope.ACCOUNT,
                raw_text=operator_message,
                account_id=account_id,
            )
        return None

    def _pause_scope(self, campaign_id: str, intent: LiveOpsIntent) -> str:
        if intent.scope is LiveOpsScope.CAMPAIGN:
            changed = self._live_execution_service.pause_campaign(campaign_id)
            self._refresh_continuous_ops_for_campaign(campaign_id)
            return (
                f"Paused campaign `{campaign_id}`. Live execution and autonomous work will stay stopped until you resume it."
                if changed
                else f"I could not pause campaign `{campaign_id}`."
            )
        if intent.scope is LiveOpsScope.ACCOUNT:
            account_id = intent.account_id.strip()
            if not account_id:
                return "Which account should I pause?"
            changed = self._live_execution_service.pause_account(account_id, reason="operator_pause_from_chat")
            return (
                f"Paused account `{account_id}` for live engagement."
                if changed
                else f"I could not pause account `{account_id}`."
            )
        if intent.scope is LiveOpsScope.CONVERSATION:
            resolved = self._resolve_conversation_target(campaign_id, intent.conversation_id, desired_status="active")
            if isinstance(resolved, str):
                return resolved
            changed = self._live_execution_service.pause_conversation(
                campaign_id,
                resolved.conversation_id,
                reason="operator_pause_from_chat",
            )
            return (
                f"Paused conversation `{resolved.conversation_id}`."
                if changed
                else f"I could not pause conversation `{resolved.conversation_id}`."
            )
        return "I could not tell what scope you wanted me to pause."

    def _resume_scope(self, campaign_id: str, intent: LiveOpsIntent) -> str:
        if intent.scope is LiveOpsScope.CAMPAIGN:
            changed = self._live_execution_service.resume_campaign(campaign_id)
            self._refresh_continuous_ops_for_campaign(campaign_id)
            return (
                f"Resumed campaign `{campaign_id}`."
                if changed
                else f"I could not resume campaign `{campaign_id}`."
            )
        if intent.scope is LiveOpsScope.ACCOUNT:
            account_id = intent.account_id.strip()
            if not account_id:
                return "Which account should I resume?"
            changed = self._live_execution_service.resume_account(account_id)
            return (
                f"Resumed account `{account_id}` for live engagement."
                if changed
                else f"I could not resume account `{account_id}`."
            )
        if intent.scope is LiveOpsScope.CONVERSATION:
            resolved = self._resolve_conversation_target(campaign_id, intent.conversation_id, desired_status="paused")
            if isinstance(resolved, str):
                return resolved
            changed = self._live_execution_service.resume_conversation(campaign_id, resolved.conversation_id)
            return (
                f"Resumed conversation `{resolved.conversation_id}`."
                if changed
                else f"I could not resume conversation `{resolved.conversation_id}`."
            )
        return "I could not tell what scope you wanted me to resume."

    def _set_posture(self, campaign_id: str, intent: LiveOpsIntent, *, operator_id: str) -> str:
        field = intent.posture_field.strip()
        requested_mode = AutonomousSendMode(intent.requested_mode)
        kwargs = {
            "updated_by": operator_id,
            "notes": intent.raw_text.strip(),
        }
        if field == "dm_reply_mode":
            kwargs["dm_reply_mode"] = requested_mode
            area_key = "dm_reply_posture"
            label = "DM replies"
        elif field == "group_outreach_mode":
            kwargs["group_outreach_mode"] = requested_mode
            area_key = "group_outreach_posture"
            label = "Group outreach sends"
        else:
            kwargs["group_reply_mode"] = requested_mode
            area_key = "group_reply_posture"
            label = "Group replies"
        posture = self._autonomous_send_manager.update_posture(campaign_id, **kwargs)
        profile = self._control_manager.get_profile(campaign_id)
        if area_key not in profile.confirmed_areas:
            profile.confirmed_areas.append(area_key)
        if intent.raw_text.strip() and intent.raw_text.strip() not in profile.operator_preferences:
            profile.operator_preferences.append(intent.raw_text.strip())
        profile.updated_by = operator_id
        self._control_manager.save_profile(profile)
        if field == "dm_reply_mode":
            effective_mode = posture.dm_reply_mode.value
        elif field == "group_outreach_mode":
            effective_mode = posture.group_outreach_mode.value
        else:
            effective_mode = posture.group_reply_mode.value
        human_mode = "automatic" if effective_mode == AutonomousSendMode.AUTONOMOUS_ALLOWED.value else "manual-only"
        return f"{label} are now `{human_mode}` for campaign `{campaign_id}`."

    def _approve_review(self, campaign_id: str, intent: LiveOpsIntent, *, operator_id: str) -> str:
        review_id = self._resolve_review_id(campaign_id, intent.review_id)
        if isinstance(review_id, str) and review_id.startswith("Which review"):
            return review_id
        resolved_review_id = str(review_id)
        result = self._autonomous_send_service.materialize_review(
            campaign_id,
            resolved_review_id,
            operator_id=operator_id,
        )
        return result

    def _dismiss_review(self, campaign_id: str, intent: LiveOpsIntent, *, operator_id: str) -> str:
        review_id = self._resolve_review_id(campaign_id, intent.review_id)
        if isinstance(review_id, str) and review_id.startswith("Which review"):
            return review_id
        resolved_review_id = str(review_id)
        return self._autonomous_send_service.dismiss_review(
            campaign_id,
            resolved_review_id,
            operator_id=operator_id,
            note="Dismissed from Telegram live ops.",
        )

    def _update_voice(self, campaign_id: str, intent: LiveOpsIntent, *, operator_id: str) -> str:
        directives = _extract_voice_directives(intent.raw_text)
        if not any(directives.values()):
            return "What voice change should I lock in for this campaign? A short cue like `warmer, less salesy, more direct` is enough."
        profile = self._control_manager.get_profile(campaign_id)
        profile.voice_profile.tone_descriptors = _merge_unique(
            profile.voice_profile.tone_descriptors,
            directives["tone_descriptors"],
        )
        profile.voice_profile.style_do = _merge_unique(
            profile.voice_profile.style_do,
            directives["style_do"],
        )
        profile.voice_profile.style_avoid = _merge_unique(
            profile.voice_profile.style_avoid,
            directives["style_avoid"],
        )
        if directives["cta_style"]:
            profile.voice_profile.cta_style = directives["cta_style"][0]
        if directives["emoji_policy"]:
            profile.voice_profile.emoji_policy = directives["emoji_policy"][0]
        if directives["evidence_style"]:
            profile.voice_profile.evidence_style = directives["evidence_style"][0]
        profile.operator_preferences = _merge_unique(profile.operator_preferences, [intent.raw_text.strip()])
        if "voice_profile" not in profile.confirmed_areas:
            profile.confirmed_areas.append("voice_profile")
        profile.updated_by = operator_id
        self._control_manager.save_profile(profile)
        changes = ", ".join(
            _merge_unique(
                directives["tone_descriptors"],
                [f"avoid {value}" for value in directives["style_avoid"]],
            )
        )
        return f"Updated the live reply voice for campaign `{campaign_id}`: {changes or 'voice override saved'}."

    def _update_safeguard(self, campaign_id: str, intent: LiveOpsIntent, *, operator_id: str) -> str:
        instruction = _normalize_text(intent.raw_text)
        if not instruction:
            return "What safeguard should I add?"
        profile = self._control_manager.get_profile(campaign_id)
        label = _slugify_guardrail_label(instruction)
        guardrail = OperatorGuardrail(label=label, instruction=instruction)
        existing = {item.label: item for item in profile.forbidden_claims}
        existing[label] = guardrail
        profile.forbidden_claims = list(existing.values())
        profile.operator_preferences = _merge_unique(profile.operator_preferences, [instruction])
        if "forbidden_claims" not in profile.confirmed_areas:
            profile.confirmed_areas.append("forbidden_claims")
        profile.updated_by = operator_id
        self._control_manager.save_profile(profile)
        return f"Saved that safeguard for campaign `{campaign_id}`: {instruction}"

    def _show_pending_reviews(self, campaign_id: str) -> str:
        pending_reviews = [
            review
            for review in self._autonomous_send_manager.list_reviews(campaign_id)
            if review.status is AutonomousSendReviewStatus.PENDING
        ]
        review_lines = [
            f"- `{review.review_id}`: {review.summary or review.draft_text[:90]} Say `approve {review.review_id}` or `dismiss {review.review_id}`."
            for review in pending_reviews[:8]
        ]
        return format_review_list(review_lines, heading=f"Pending autonomous reviews for `{campaign_id}`.")

    def _explain_block_reason(self, campaign_id: str, intent: LiveOpsIntent) -> str:
        if intent.review_id.strip():
            review = self._autonomous_send_manager.get_review(campaign_id, intent.review_id.strip())
            if review is not None:
                return format_block_reason(
                    f"`{review.review_id}` is blocked for operator review.",
                    review.summary or ", ".join(review.reason_codes),
                    next_step=f"approve {review.review_id}",
                )

        if intent.conversation_id.strip():
            conversation = self._conversation_manager.get(campaign_id, intent.conversation_id.strip())
            if conversation is not None:
                return format_block_reason(
                    f"Conversation `{conversation.conversation_id}` is `{conversation.status.value}`.",
                    conversation.next_action_reason or conversation.status_reason or conversation.operator_hold_reason or "No extra reason is stored.",
                    next_step=f"resume {conversation.conversation_id}",
                )

        snapshot = self._build_snapshot(campaign_id)
        if len(snapshot.blocked_reasons) == 1:
            return format_block_reason(
                f"Top blocked reason for `{campaign_id}`.",
                snapshot.blocked_reasons[0],
                next_step=snapshot.recommended_next_action,
            )
        if snapshot.blocked_reasons:
            return format_block_reason(
                f"There are {len(snapshot.blocked_reasons)} blocked reasons for `{campaign_id}`.",
                "\n".join(f"- {reason}" for reason in snapshot.blocked_reasons[:5]),
                next_step="Ask me about a specific review or conversation if you want the exact record.",
            )
        return "Nothing in the current live state is blocked right now."

    def _build_snapshot(self, campaign_id: str) -> CampaignLiveOpsSnapshot:
        campaign = self._campaign_manager.get(campaign_id)
        actions = self._live_execution_service.manager.list_for_campaign(campaign_id)
        conversations = self._conversation_manager.list_for_campaign(campaign_id)
        posture = self._autonomous_send_manager.get_posture(campaign_id)
        pending_reviews = [
            review
            for review in self._autonomous_send_manager.list_reviews(campaign_id)
            if review.status is AutonomousSendReviewStatus.PENDING
        ]
        batches = self._prepared_execution_manager.list_batches_for_campaign(campaign_id)
        latest_batch = batches[0] if batches else None
        action_statuses = Counter(action.status.value for action in actions)
        attention_items = self._build_attention_items(campaign_id, conversations, pending_reviews, actions, campaign.status.value if campaign is not None else "unknown")
        control_areas = self._build_control_states(campaign_id)
        continuous_state = self._continuous_ops_manager.get_for_campaign(campaign_id) if self._continuous_ops_manager is not None else None
        blocked_reasons = list(continuous_state.blocked_reasons) if continuous_state is not None else []
        blocked_reasons.extend(
            action.last_result_summary or action.terminal_failure_reason
            for action in actions
            if action.status is LiveActionStatus.BLOCKED and (action.last_result_summary or action.terminal_failure_reason)
        )
        blocked_reasons = _unique_strings(blocked_reasons)
        return CampaignLiveOpsSnapshot(
            campaign_id=campaign_id,
            campaign_status=campaign.status.value if campaign is not None else "unknown",
            primary_goal=campaign.primary_goal if campaign is not None else "",
            activation_status=(
                "not activated yet"
                if latest_batch is None
                else latest_batch.status.value.replace("_", " ")
            ),
            latest_batch_id=latest_batch.batch_id if latest_batch is not None else "",
            queued_count=action_statuses.get(LiveActionStatus.QUEUED.value, 0),
            retry_wait_count=action_statuses.get(LiveActionStatus.RETRY_WAIT.value, 0),
            running_count=action_statuses.get(LiveActionStatus.CLAIMED.value, 0) + action_statuses.get(LiveActionStatus.RUNNING.value, 0),
            blocked_count=action_statuses.get(LiveActionStatus.BLOCKED.value, 0),
            recent_success_count=action_statuses.get(LiveActionStatus.SUCCEEDED.value, 0),
            pending_autonomous_review_count=len(pending_reviews),
            paused_conversation_count=sum(1 for conversation in conversations if conversation.status is ExternalConversationStatus.PAUSED),
            escalated_conversation_count=sum(1 for conversation in conversations if conversation.status is ExternalConversationStatus.ESCALATED),
            review_inbound_count=sum(1 for conversation in conversations if conversation.next_action_type == "review_inbound"),
            follow_up_due_count=sum(1 for conversation in conversations if conversation.follow_up_due_at is not None),
            commercial_summary=continuous_state.commercial_summary if continuous_state is not None else "",
            promising_active_thread_count=(
                continuous_state.promising_active_thread_count
                if continuous_state is not None
                else 0
            ),
            objection_heavy_thread_count=(
                continuous_state.objection_heavy_thread_count
                if continuous_state is not None
                else 0
            ),
            conversion_ready_thread_count=(
                continuous_state.conversion_ready_thread_count
                if continuous_state is not None
                else 0
            ),
            unresolved_high_opportunity_thread_count=(
                continuous_state.unresolved_high_opportunity_thread_count
                if continuous_state is not None
                else 0
            ),
            stale_promising_thread_count=(
                continuous_state.stale_promising_thread_count
                if continuous_state is not None
                else 0
            ),
            high_yield_account_labels=(
                list(continuous_state.high_yield_account_labels)
                if continuous_state is not None
                else []
            ),
            high_yield_community_labels=(
                list(continuous_state.high_yield_community_labels)
                if continuous_state is not None
                else []
            ),
            group_reply_mode=posture.group_reply_mode.value,
            dm_reply_mode=posture.dm_reply_mode.value,
            blocked_reasons=blocked_reasons,
            attention_items=attention_items,
            control_areas=control_areas,
            recommended_next_action=self._recommended_next_action(attention_items, control_areas, campaign_id),
        )

    def _build_attention_items(
        self,
        campaign_id: str,
        conversations,
        pending_reviews,
        actions,
        campaign_status: str,
    ) -> list[AttentionItem]:
        items: list[AttentionItem] = []
        for review in pending_reviews:
            items.append(
                AttentionItem(
                    item_type="pending_review",
                    item_id=review.review_id,
                    conversation_id=review.conversation_id,
                    account_id=review.account_id,
                    summary=review.summary or "Autonomous reply needs operator review.",
                    recommended_action=f"approve {review.review_id}",
                    reason_code=review.reason_codes[0] if review.reason_codes else "",
                )
            )
        for conversation in conversations:
            if self._is_conversion_ready_attention(conversation):
                recommendation = "show live status"
                if conversation.pending_autonomous_review_id:
                    recommendation = f"approve {conversation.pending_autonomous_review_id}"
                items.append(
                    AttentionItem(
                        item_type="conversion_ready_thread",
                        item_id=conversation.conversation_id,
                        conversation_id=conversation.conversation_id,
                        account_id=conversation.account_id,
                        summary=conversation.handoff_summary or conversation.qualification_summary or "Thread is commercially ready for a next step.",
                        recommended_action=recommendation,
                    )
                )
            if self._is_stale_promising_attention(conversation):
                items.append(
                    AttentionItem(
                        item_type="stale_promising_thread",
                        item_id=conversation.conversation_id,
                        conversation_id=conversation.conversation_id,
                        account_id=conversation.account_id,
                        summary=conversation.summary or "Previously promising thread looks stale and may need a follow-up decision.",
                        recommended_action="show live status",
                    )
                )
            if conversation.status is ExternalConversationStatus.ESCALATED:
                items.append(
                    AttentionItem(
                        item_type="escalated_conversation",
                        item_id=conversation.conversation_id,
                        conversation_id=conversation.conversation_id,
                        account_id=conversation.account_id,
                        summary=conversation.next_action_reason or conversation.status_reason or "Conversation is escalated.",
                        recommended_action=f"resume {conversation.conversation_id}",
                    )
                )
            if conversation.status is ExternalConversationStatus.PAUSED and conversation.last_inbound_at is not None:
                items.append(
                    AttentionItem(
                        item_type="paused_conversation",
                        item_id=conversation.conversation_id,
                        conversation_id=conversation.conversation_id,
                        account_id=conversation.account_id,
                        summary=conversation.operator_hold_reason or conversation.next_action_reason or "Conversation is paused.",
                        recommended_action=f"resume {conversation.conversation_id}",
                    )
                )
        for action in actions:
            if action.status is not LiveActionStatus.BLOCKED:
                continue
            items.append(
                AttentionItem(
                    item_type="blocked_action",
                    item_id=action.action_id,
                    conversation_id=action.conversation_id,
                    account_id=action.account_id,
                    summary=action.last_result_summary or action.terminal_failure_reason or "Live action is blocked.",
                    recommended_action="show blocked",
                )
            )
        if campaign_status == "paused":
            items.append(
                AttentionItem(
                    item_type="paused_campaign",
                    item_id=campaign_id,
                    summary="Campaign is paused, so autonomous work is stopped.",
                    recommended_action="resume this campaign",
                )
            )

        for account_id in _unique_strings(item.account_id for item in items if item.account_id):
            state = self._live_execution_policy_state_manager.get_account_state(account_id)
            if state is None or not state.is_paused:
                continue
            items.append(
                AttentionItem(
                    item_type="paused_account",
                    item_id=account_id,
                    account_id=account_id,
                    summary=state.pause_reason or "Managed account is paused.",
                    recommended_action=f"resume account {account_id}",
                )
            )
        return sorted(items, key=_attention_sort_key)[:8]

    def _build_control_states(self, campaign_id: str) -> list[ControlAreaState]:
        artifact_map = self._artifact_map(campaign_id)
        strategy = artifact_map.get(WorkflowArtifactKind.STRATEGY_PLAYBOOK)
        campaign_context = artifact_map.get(WorkflowArtifactKind.CAMPAIGN_CONTEXT)
        campaign_brief = artifact_map.get(WorkflowArtifactKind.CAMPAIGN_BRIEF)
        posture = self._autonomous_send_manager.get_posture(campaign_id)
        profile = self._control_manager.get_profile(campaign_id)
        open_ambiguities = []
        if campaign_context is not None and isinstance(campaign_context.data, dict):
            open_ambiguities = [
                str(item).strip()
                for item in campaign_context.data.get(OPEN_AMBIGUITIES_KEY, [])
                if str(item).strip()
            ]

        voice_profile = strategy.data.get("voice_profile", {}) if strategy is not None and isinstance(strategy.data, dict) else {}
        strategy_approved_claims = strategy.data.get("approved_claims", []) if strategy is not None and isinstance(strategy.data, dict) else []
        strategy_forbidden_claims = strategy.data.get("forbidden_claims", []) if strategy is not None and isinstance(strategy.data, dict) else []
        strategy_communities = strategy.data.get("communities", []) if strategy is not None and isinstance(strategy.data, dict) else []
        context_voice = campaign_context.data.get(VOICE_PROFILE_KEY, {}) if campaign_context is not None and isinstance(campaign_context.data, dict) else {}

        voice_state = self._voice_control_state(profile, voice_profile, context_voice, open_ambiguities)
        approved_claim_state = self._approved_claim_state(profile, strategy_approved_claims, campaign_brief, open_ambiguities)
        forbidden_claim_state = self._forbidden_claim_state(profile, strategy_forbidden_claims, open_ambiguities)
        dm_posture_state = self._posture_state(
            area_key="dm_reply_posture",
            label="Autonomous DM reply posture",
            mode=posture.dm_reply_mode.value,
            confirmed_areas=profile.confirmed_areas,
        )
        group_posture_state = self._posture_state(
            area_key="group_reply_posture",
            label="Autonomous group reply posture",
            mode=posture.group_reply_mode.value,
            confirmed_areas=profile.confirmed_areas,
        )
        tone_guidance_state = self._community_tone_state(profile, strategy_communities, open_ambiguities)
        escalation_state = self._escalation_rule_state(profile, strategy_communities, open_ambiguities)
        return [
            voice_state,
            approved_claim_state,
            forbidden_claim_state,
            dm_posture_state,
            group_posture_state,
            tone_guidance_state,
            escalation_state,
        ]

    def _voice_control_state(
        self,
        profile,
        strategy_voice: dict,
        context_voice: dict,
        open_ambiguities: list[str],
    ) -> ControlAreaState:
        if _has_area_ambiguity(open_ambiguities, ("voice", "tone", "style")):
            return ControlAreaState(
                area_key="voice_profile",
                label="Voice profile",
                status=ControlCompletenessStatus.AMBIGUOUS,
                summary="Voice guidance is still ambiguous in the stored campaign context.",
            )
        if profile.voice_profile.has_any() or _strategy_voice_defined(strategy_voice):
            return ControlAreaState(
                area_key="voice_profile",
                label="Voice profile",
                status=ControlCompletenessStatus.CONFIRMED if profile.voice_profile.has_any() or "voice_profile" in profile.confirmed_areas else ControlCompletenessStatus.PARTIAL,
                summary="Live reply voice guidance is defined." if profile.voice_profile.has_any() else "A strategy voice profile exists, but chat-level overrides are still minimal.",
            )
        if _context_voice_hint_present(context_voice):
            return ControlAreaState(
                area_key="voice_profile",
                label="Voice profile",
                status=ControlCompletenessStatus.PARTIAL,
                summary="Campaign context has tone hints, but no explicit live reply voice profile is locked yet.",
            )
        return ControlAreaState(
            area_key="voice_profile",
            label="Voice profile",
            status=ControlCompletenessStatus.DEFAULT,
            summary="Voice profile is still using the built-in live reply default.",
            default_is_acceptable=True,
        )

    def _approved_claim_state(
        self,
        profile,
        strategy_approved_claims,
        campaign_brief,
        open_ambiguities: list[str],
    ) -> ControlAreaState:
        if _has_area_ambiguity(open_ambiguities, ("claim", "proof", "pricing")):
            return ControlAreaState(
                area_key="approved_claims",
                label="Approved claims",
                status=ControlCompletenessStatus.AMBIGUOUS,
                summary="Some campaign facts still look ambiguous, so approved-claims guidance is not fully locked.",
            )
        explicit_claim_count = len(profile.approved_claims) + (
            len(strategy_approved_claims) if isinstance(strategy_approved_claims, list) else 0
        )
        if explicit_claim_count > 0:
            return ControlAreaState(
                area_key="approved_claims",
                label="Approved claims",
                status=ControlCompletenessStatus.CONFIRMED,
                summary=f"{explicit_claim_count} approved claim(s) are defined for live replies.",
            )
        brief_facts_present = False
        if campaign_brief is not None and isinstance(campaign_brief.data, dict):
            brief_facts_present = any(str(value).strip() for value in campaign_brief.data.values() if isinstance(value, str))
        if brief_facts_present:
            return ControlAreaState(
                area_key="approved_claims",
                label="Approved claims",
                status=ControlCompletenessStatus.UNSET,
                summary="Approved claims are not defined yet. The runtime can fall back to brief facts, but it does not have an explicit approved-claims list.",
            )
        return ControlAreaState(
            area_key="approved_claims",
            label="Approved claims",
            status=ControlCompletenessStatus.UNSET,
            summary="Approved claims are not defined yet.",
        )

    def _forbidden_claim_state(
        self,
        profile,
        strategy_forbidden_claims,
        open_ambiguities: list[str],
    ) -> ControlAreaState:
        if _has_area_ambiguity(open_ambiguities, ("safeguard", "pricing", "claim", "promise")):
            return ControlAreaState(
                area_key="forbidden_claims",
                label="Forbidden claims",
                status=ControlCompletenessStatus.AMBIGUOUS,
                summary="Safeguard guidance is still ambiguous in campaign context.",
            )
        explicit_count = len(profile.forbidden_claims) + (
            len(strategy_forbidden_claims) if isinstance(strategy_forbidden_claims, list) else 0
        )
        if explicit_count > 0:
            return ControlAreaState(
                area_key="forbidden_claims",
                label="Forbidden claims",
                status=ControlCompletenessStatus.CONFIRMED,
                summary=f"{explicit_count} forbidden-claim safeguard(s) are defined.",
            )
        return ControlAreaState(
            area_key="forbidden_claims",
            label="Forbidden claims",
            status=ControlCompletenessStatus.DEFAULT,
            summary="Forbidden claims are still relying on the built-in defaults for invented pricing, guarantees, and fabricated proof.",
            default_is_acceptable=True,
        )

    def _posture_state(
        self,
        *,
        area_key: str,
        label: str,
        mode: str,
        confirmed_areas: list[str],
    ) -> ControlAreaState:
        if area_key in confirmed_areas:
            return ControlAreaState(
                area_key=area_key,
                label=label,
                status=ControlCompletenessStatus.CONFIRMED,
                summary=f"{label} is explicitly set to `{mode}`.",
            )
        return ControlAreaState(
            area_key=area_key,
            label=label,
            status=ControlCompletenessStatus.DEFAULT,
            summary=f"{label} is still on the default `{mode}` setting.",
            default_is_acceptable=True,
        )

    def _community_tone_state(
        self,
        profile,
        strategy_communities,
        open_ambiguities: list[str],
    ) -> ControlAreaState:
        if _has_area_ambiguity(open_ambiguities, ("community", "tone")):
            return ControlAreaState(
                area_key="community_tone_guidance",
                label="Community-specific tone guidance",
                status=ControlCompletenessStatus.AMBIGUOUS,
                summary="Community-specific tone guidance is still ambiguous.",
            )
        communities = strategy_communities if isinstance(strategy_communities, list) else []
        community_count = len([community for community in communities if isinstance(community, dict)])
        guided_count = len(
            [
                community
                for community in communities
                if isinstance(community, dict) and str(community.get("tone_guidance", "")).strip()
            ]
        )
        guided_count += len(profile.community_tone_guidance)
        if guided_count > 0 and community_count > 0 and guided_count < community_count:
            return ControlAreaState(
                area_key="community_tone_guidance",
                label="Community-specific tone guidance",
                status=ControlCompletenessStatus.PARTIAL,
                summary=f"Tone guidance exists for {guided_count} of {community_count} mapped communities.",
            )
        if guided_count > 0:
            return ControlAreaState(
                area_key="community_tone_guidance",
                label="Community-specific tone guidance",
                status=ControlCompletenessStatus.CONFIRMED,
                summary="Community-specific tone guidance is defined.",
            )
        return ControlAreaState(
            area_key="community_tone_guidance",
            label="Community-specific tone guidance",
            status=ControlCompletenessStatus.UNSET,
            summary="Community-specific tone guidance is still missing.",
        )

    def _escalation_rule_state(
        self,
        profile,
        strategy_communities,
        open_ambiguities: list[str],
    ) -> ControlAreaState:
        if _has_area_ambiguity(open_ambiguities, ("escalat", "review", "operator")):
            return ControlAreaState(
                area_key="escalation_rules",
                label="Escalation rules",
                status=ControlCompletenessStatus.AMBIGUOUS,
                summary="Escalation rules are still implicit or ambiguous.",
            )
        communities = strategy_communities if isinstance(strategy_communities, list) else []
        community_count = len([community for community in communities if isinstance(community, dict)])
        rule_count = len(
            [
                community
                for community in communities
                if isinstance(community, dict) and str(community.get("escalation_rule", "")).strip()
            ]
        )
        rule_count += len(profile.escalation_rules)
        if rule_count > 0 and community_count > 0 and rule_count < community_count:
            return ControlAreaState(
                area_key="escalation_rules",
                label="Escalation rules",
                status=ControlCompletenessStatus.PARTIAL,
                summary=f"Escalation rules exist for {rule_count} of {community_count} mapped communities.",
            )
        if rule_count > 0:
            return ControlAreaState(
                area_key="escalation_rules",
                label="Escalation rules",
                status=ControlCompletenessStatus.CONFIRMED,
                summary="Escalation rules are defined.",
            )
        return ControlAreaState(
            area_key="escalation_rules",
            label="Escalation rules",
            status=ControlCompletenessStatus.DEFAULT,
            summary="Escalation rules are still implicit.",
            default_is_acceptable=True,
        )

    def _resolve_review_id(self, campaign_id: str, requested_review_id: str) -> str:
        normalized_review_id = requested_review_id.strip()
        if normalized_review_id:
            return normalized_review_id
        pending_reviews = [
            review.review_id
            for review in self._autonomous_send_manager.list_reviews(campaign_id)
            if review.status is AutonomousSendReviewStatus.PENDING
        ]
        if len(pending_reviews) == 1:
            return pending_reviews[0]
        return "Which review should I use? Please mention the `review-...` id."

    def _resolve_conversation_target(
        self,
        campaign_id: str,
        requested_conversation_id: str,
        *,
        desired_status: str,
    ):
        normalized_conversation_id = requested_conversation_id.strip()
        if normalized_conversation_id:
            conversation = self._conversation_manager.get(campaign_id, normalized_conversation_id)
            if conversation is None:
                return f"I could not find conversation `{normalized_conversation_id}`."
            return conversation
        conversations = self._conversation_manager.list_for_campaign(campaign_id)
        if desired_status == "paused":
            candidates = [
                conversation
                for conversation in conversations
                if conversation.status in {ExternalConversationStatus.PAUSED, ExternalConversationStatus.ESCALATED}
            ]
        else:
            candidates = [
                conversation
                for conversation in conversations
                if conversation.status is ExternalConversationStatus.ACTIVE
            ]
        if len(candidates) == 1:
            return candidates[0]
        return "Which conversation should I use? Please mention the `conv-...` id."

    def _artifact_map(self, campaign_id: str) -> dict[WorkflowArtifactKind, WorkflowArtifact]:
        artifact_map: dict[WorkflowArtifactKind, WorkflowArtifact] = {}
        for artifact in self._campaign_manager.load_compatibility_artifacts(campaign_id):
            existing = artifact_map.get(artifact.kind)
            if existing is None or artifact.updated_at >= existing.updated_at:
                artifact_map[artifact.kind] = artifact
        return artifact_map

    def _recommended_next_action(
        self,
        attention_items: list[AttentionItem],
        control_areas: list[ControlAreaState],
        campaign_id: str,
    ) -> str:
        if attention_items:
            return attention_items[0].recommended_action
        unresolved_controls = [
            area
            for area in control_areas
            if area.status in {
                ControlCompletenessStatus.UNSET,
                ControlCompletenessStatus.PARTIAL,
                ControlCompletenessStatus.AMBIGUOUS,
            }
        ]
        if unresolved_controls:
            return f"tighten {unresolved_controls[0].label.lower()} for `{campaign_id}`"
        return "live controls look stable right now"

    def _refresh_continuous_ops(self, session: SessionRecord) -> None:
        if self._continuous_ops_manager is None:
            return
        self._continuous_ops_manager.refresh_for_session(session)

    def _refresh_continuous_ops_for_campaign(self, campaign_id: str) -> None:
        if self._continuous_ops_manager is None:
            return
        self._continuous_ops_manager.refresh_for_campaign(campaign_id)

    def _is_conversion_ready_attention(self, conversation) -> bool:
        if conversation.status in {ExternalConversationStatus.CLOSED, ExternalConversationStatus.BLOCKED}:
            return False
        return bool(
            conversation.handoff_status in {"ready", "clarification_required", "blocked"}
            or conversation.qualification_status == "conversion_ready"
            or conversation.belief_state.commercial_stage in {
                "handoff_ready",
                "conversion_target_clarification_required",
            }
        )

    def _is_stale_promising_attention(self, conversation) -> bool:
        if conversation.status in {ExternalConversationStatus.CLOSED, ExternalConversationStatus.BLOCKED}:
            return False
        if conversation.handoff_status == "delivered":
            return False
        if not (
            conversation.qualification_status in {"potential_fit", "conversion_ready"}
            or conversation.handoff_status in {"ready", "clarification_required"}
            or conversation.belief_state.commercial_stage in {
                "potential_fit",
                "conversion_ready",
                "handoff_ready",
                "conversion_target_clarification_required",
            }
            or conversation.belief_state.known_fit_signals
        ):
            return False
        latest_timestamp = max(
            timestamp.timestamp()
            for timestamp in [
                conversation.last_inbound_at,
                conversation.last_outbound_at,
                conversation.belief_state.last_belief_update_at,
                conversation.last_handoff_attempted_at,
                conversation.last_handoff_completed_at,
                conversation.created_at,
            ]
            if timestamp is not None
        )
        return latest_timestamp <= (_utc_now_timestamp() - (72 * 3600))


def _normalize_text(value: str) -> str:
    return " ".join(str(value or "").strip().split())


def _extract_match(pattern: re.Pattern[str], value: str) -> str:
    match = pattern.search(value)
    return match.group(1).strip() if match else ""


def _extract_account_id(value: str) -> str:
    match = _ACCOUNT_ID_PATTERN.search(value)
    return match.group(1).strip() if match else ""


def _merge_unique(existing: list[str], new_values: Iterable[str]) -> list[str]:
    merged = [value for value in existing if str(value).strip()]
    for raw_value in new_values:
        value = str(raw_value).strip()
        if value and value not in merged:
            merged.append(value)
    return merged


def _unique_strings(values: Iterable[str]) -> list[str]:
    unique: list[str] = []
    for raw_value in values:
        value = str(raw_value).strip()
        if value and value not in unique:
            unique.append(value)
    return unique


def _strategy_voice_defined(raw_profile: dict) -> bool:
    if not isinstance(raw_profile, dict):
        return False
    return any(
        bool(raw_profile.get(key))
        for key in ("tone_descriptors", "style_do", "style_avoid", "cta_style", "emoji_policy", "evidence_style")
    )


def _context_voice_hint_present(raw_profile: dict) -> bool:
    if not isinstance(raw_profile, dict):
        return False
    return any(
        bool(raw_profile.get(key))
        for key in (
            VOICE_PREFERRED_TRAITS_KEY,
            VOICE_AVOID_TRAITS_KEY,
            VOICE_STYLE_NOTES_KEY,
            VOICE_CTA_PREFERENCES_KEY,
        )
    )


def _has_area_ambiguity(ambiguities: list[str], keywords: tuple[str, ...]) -> bool:
    lowered = [item.lower() for item in ambiguities]
    return any(any(keyword in item for keyword in keywords) for item in lowered)


def _attention_sort_key(item: AttentionItem) -> tuple[int, str]:
    order = {
        "pending_review": 1,
        "conversion_ready_thread": 2,
        "stale_promising_thread": 3,
        "escalated_conversation": 4,
        "blocked_action": 5,
        "paused_conversation": 6,
        "paused_account": 7,
        "paused_campaign": 8,
    }
    return order.get(item.item_type, 99), item.item_id


def _utc_now_timestamp() -> float:
    from datetime import UTC, datetime

    return datetime.now(UTC).timestamp()


def _extract_voice_directives(message: str) -> dict[str, list[str]]:
    normalized = _normalize_text(message).lower()
    directives = {
        "tone_descriptors": [],
        "style_do": [],
        "style_avoid": [],
        "cta_style": [],
        "emoji_policy": [],
        "evidence_style": [],
    }
    if "warmer" in normalized or "friendlier" in normalized:
        directives["tone_descriptors"].append("warmer")
    if "more direct" in normalized or "direct" in normalized:
        directives["tone_descriptors"].append("direct")
        directives["style_do"].append("answer more directly")
    if "less salesy" in normalized or "less pushy" in normalized:
        directives["style_avoid"].append("salesy language")
    if "less hypey" in normalized or "less hype" in normalized:
        directives["style_avoid"].append("hype-heavy language")
    if "more concise" in normalized:
        directives["style_do"].append("keep replies concise")
    if "concise" in normalized or "shorter" in normalized or "short chat" in normalized:
        directives["style_do"].append("keep replies concise")
    if "telegram-native" in normalized or "telegram native" in normalized or "short chat messages" in normalized:
        directives["style_do"].append("keep replies like short Telegram chat messages")
    if (
        "less punctuation" in normalized
        or "minimal punctuation" in normalized
        or "avoid too much punctuation" in normalized
        or "not too much punctuation" in normalized
    ):
        directives["style_do"].append("use minimal punctuation")
    if (
        "no prose" in normalized
        or "not prose" in normalized
        or "less prose" in normalized
        or "less polished" in normalized
        or "not polished" in normalized
    ):
        directives["style_avoid"].append("polished prose")
    if "not writers" in normalized or "not writerly" in normalized:
        directives["style_avoid"].append("writerly phrasing")
    if "no em dash" in normalized or "no em dashes" in normalized or "avoid em dash" in normalized:
        directives["style_avoid"].append("em dashes")
    if "no emoji" in normalized or "no emojis" in normalized or "avoid emoji" in normalized:
        directives["style_avoid"].append("emoji greetings")
        directives["emoji_policy"].append("none")
    if "not corny" in normalized or "no corny" in normalized or "avoid corny" in normalized:
        directives["style_avoid"].append("corny openers")
    if "no quick question for the room" in normalized or "avoid quick question for the room" in normalized:
        directives["style_avoid"].append("room-addressing hooks")
    if "no hey everyone" in normalized or "avoid hey everyone" in normalized:
        directives["style_avoid"].append("room-addressing hooks")
    if "corporate filler" in normalized or "not corporate" in normalized:
        directives["style_avoid"].append("corporate filler")
    if "online service" in normalized or "service" in normalized:
        directives["style_do"].append("frame value around the online service naturally")
    if (
        "not car salesman" in normalized
        or "not a salesman" in normalized
        or "not salesmen" in normalized
        or "hard sell" in normalized
        or "hard-sell" in normalized
    ):
        directives["style_avoid"].append("hard close language")
    if "soft question" in normalized:
        directives["cta_style"].append("soft_question")
    return directives


def _slugify_guardrail_label(instruction: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", instruction.lower()).strip("_")
    if normalized:
        return normalized[:48]
    return "operator_guardrail"
