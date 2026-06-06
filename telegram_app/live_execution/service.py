"""Execution service that turns queued live actions into audited capability calls."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import hashlib
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from telegram_app.campaign_signals import CampaignSignalBridge, CampaignSignalSeverity
from telegram_app.campaigns import CampaignManager
from telegram_app.campaign_memory.operational_notes import (
    EXECUTION_LOG_DESTINATION,
    NEXT_ACTIONS_DESTINATION,
)
from telegram_app.capabilities import MembershipCapability, MessagingCapability
from telegram_app.capabilities.base import CapabilityResult
from telegram_app.capabilities.mtproto.registry import AccountRegistry
from telegram_app.external_conversations import (
    ExternalConversationManager,
    ExternalConversationStatus,
    ExternalConversationTimingService,
    ThreadOrigin,
)
from telegram_app.models import CampaignStatus
from telegram_app.live_execution.manager import LiveExecutionManager
from telegram_app.live_execution.models import (
    LiveActionAttemptRecord,
    LiveActionRecord,
    LiveActionStatus,
    LiveActionType,
    parse_datetime,
    utc_now,
)
from telegram_app.live_execution.policy import (
    LiveActionPolicyDecision,
    LiveActionPolicyDecisionType,
    LiveActionPolicyEvaluator,
)
from telegram_app.live_execution.policy_state import LiveExecutionPolicyStateManager
from telegram_app.qualification import QualificationService

if TYPE_CHECKING:
    from telegram_app.engagement_policy.service import CampaignEngagementPolicyService

_RETRYABLE_OUTCOME_CODES = frozenset({"rate_limited", "transient_error"})
_BLOCKED_OUTCOME_CODES = frozenset(
    {
        "account_banned",
        "account_flagged",
        "account_paused",
        "already_not_participating",
        "approval_required",
        "campaign_paused",
        "channel_join_deferred",
        "channel_send_deferred",
        "community_private",
        "community_risk_pause",
        "consent_posture_blocked",
        "conversation_not_found",
        "conversation_account_mismatch",
        "conversation_blocked",
        "conversation_closed",
        "conversation_escalated",
        "conversation_paused",
        "conversation_state_unavailable",
        "dm_inbound_required",
        "group_reply_lineage_required",
        "invalid_action_payload",
        "join_request_sent",
        "message_not_found",
        "paused_conversation",
        "peer_invalid",
        "policy_blocked",
        "blocked_conversation",
        "closed_conversation",
        "escalated_conversation",
        "unsupported_action",
        "write_forbidden",
        "wrong_conversation_posture",
    }
)


@dataclass(slots=True)
class DispatchOutcome:
    """Normalized result of one execution attempt before persistence."""

    outcome_code: str
    success: bool = False
    blocked: bool = False
    retryable: bool = False
    error: str = ""
    wait_seconds: int | None = None
    result_data: dict[str, Any] = field(default_factory=dict)
    summary: str = ""


class LiveExecutionService:
    """Own the single path that turns queued actions into visible Telegram writes."""

    def __init__(
        self,
        manager: LiveExecutionManager,
        *,
        membership_capability: MembershipCapability | None = None,
        messaging_capability: MessagingCapability | None = None,
        conversation_manager: ExternalConversationManager | None = None,
        conversation_timing_service: ExternalConversationTimingService | None = None,
        campaign_manager: CampaignManager | None = None,
        account_registry: AccountRegistry | None = None,
        policy_state_manager: LiveExecutionPolicyStateManager | None = None,
        qualification_service: QualificationService | None = None,
        signal_bridge: CampaignSignalBridge | None = None,
        engagement_policy_service: CampaignEngagementPolicyService | None = None,
        worker_id: str | None = None,
        claim_ttl_seconds: int = 300,
        retry_base_delay_seconds: int = 60,
        retry_max_delay_seconds: int = 3600,
    ) -> None:
        self._manager = manager
        self._membership_capability = membership_capability
        self._messaging_capability = messaging_capability
        self._conversation_manager = conversation_manager
        self._campaign_manager = campaign_manager
        self._account_registry = account_registry
        self._policy_state_manager = policy_state_manager
        self._qualification_service = qualification_service
        self._signal_bridge = signal_bridge
        self._engagement_policy_service = engagement_policy_service
        self._worker_id = (worker_id or str(uuid4())).strip()
        self._claim_ttl_seconds = max(claim_ttl_seconds, 1)
        self._retry_base_delay_seconds = max(retry_base_delay_seconds, 1)
        self._retry_max_delay_seconds = max(retry_max_delay_seconds, self._retry_base_delay_seconds)
        self._conversation_timing_service = conversation_timing_service
        if self._conversation_timing_service is None and conversation_manager is not None:
            self._conversation_timing_service = ExternalConversationTimingService(
                conversation_manager,
                engagement_policy_service=engagement_policy_service,
            )
        self._policy_evaluator = LiveActionPolicyEvaluator(
            campaign_manager=campaign_manager,
            account_registry=account_registry,
            conversation_manager=conversation_manager,
            policy_state_manager=policy_state_manager,
        )

    @property
    def worker_id(self) -> str:
        """Expose the stable worker id for logs and tests."""
        return self._worker_id

    @property
    def manager(self) -> LiveExecutionManager:
        """Expose the execution manager for read-oriented composition layers."""
        return self._manager

    def enqueue_action(
        self,
        campaign_id: str,
        account_id: str,
        *,
        action_type: LiveActionType,
        payload: dict[str, object],
        conversation_id: str = "",
        idempotency_key: str = "",
        source_batch_id: str = "",
        source_prepared_item_id: str = "",
        source_plan_artifact_id: str = "",
        max_retries: int = 3,
        next_attempt_at: datetime | None = None,
    ) -> LiveActionRecord:
        """Persist one new live action for later dispatch."""
        return self._manager.enqueue(
            campaign_id,
            account_id,
            action_type=action_type,
            payload=payload,
            conversation_id=conversation_id,
            idempotency_key=idempotency_key,
            source_batch_id=source_batch_id,
            source_prepared_item_id=source_prepared_item_id,
            source_plan_artifact_id=source_plan_artifact_id,
            max_retries=max_retries,
            next_attempt_at=next_attempt_at,
        )

    def dispatch_next_ready(self, *, now: datetime | None = None) -> LiveActionRecord | None:
        """Claim and execute the next ready action, if any."""
        started_at = now or utc_now()
        action = self._manager.claim_next_ready(
            owner_id=self._worker_id,
            claim_ttl_seconds=self._claim_ttl_seconds,
            now=started_at,
        )
        if action is None:
            return None

        action.status = LiveActionStatus.RUNNING
        action.touch()
        self._manager.save(action)

        outcome = self._evaluate_action_policy(action, now=started_at)
        if outcome is None:
            outcome = self._execute(action)

        finished_at = now or utc_now()
        self._apply_outcome_side_effects(action, outcome, finished_at=finished_at)
        self._record_engagement_policy_outcome(action, outcome)
        attempt_number = action.retry_count + 1
        updated_action = self._apply_outcome(action, outcome, finished_at=finished_at)
        self._manager.record_attempt(
            LiveActionAttemptRecord(
                attempt_id=str(uuid4()),
                action_id=updated_action.action_id,
                campaign_id=updated_action.campaign_id,
                account_id=updated_action.account_id,
                action_type=updated_action.action_type,
                conversation_id=updated_action.conversation_id,
                attempt_number=attempt_number,
                outcome_code=outcome.outcome_code,
                started_at=started_at,
                finished_at=finished_at,
                error=outcome.error,
                wait_seconds=outcome.wait_seconds,
                result_data=outcome.result_data,
            )
        )
        self._manager.save(updated_action)
        return updated_action

    def _execute(self, action: LiveActionRecord) -> DispatchOutcome:
        if action.action_type is LiveActionType.JOIN_COMMUNITY:
            return self._execute_join(action)
        if action.action_type is LiveActionType.SEND_GROUP_MESSAGE:
            return self._execute_group_message(action)
        if action.action_type is LiveActionType.SEND_GROUP_REPLY:
            return self._execute_group_reply(action)
        if action.action_type is LiveActionType.SEND_DM_REPLY:
            return self._execute_dm_reply(action)
        if action.action_type is LiveActionType.MARK_READ:
            return self._execute_mark_read(action)
        if action.action_type is LiveActionType.LEAVE_DIALOG:
            return self._execute_leave_dialog(action)
        return DispatchOutcome(
            outcome_code="unsupported_action",
            blocked=True,
            error=f"Unsupported live action type: {action.action_type.value}",
            summary="Blocked an unknown live execution action type.",
        )

    def _execute_join(self, action: LiveActionRecord) -> DispatchOutcome:
        community_id = str(action.payload.get("community_id", "")).strip()
        if not community_id:
            return DispatchOutcome(
                outcome_code="invalid_action_payload",
                blocked=True,
                error="join_community actions require payload.community_id.",
                summary="Blocked a join action because the payload did not include a community id.",
            )
        if self._membership_capability is None:
            return DispatchOutcome(
                outcome_code="unsupported_action",
                blocked=True,
                error="Membership capability is not available in this runtime.",
                summary="Blocked a join action because no membership capability is available.",
            )
        return self._normalize_capability_result(
            self._membership_capability.join(action.account_id, community_id),
            success_summary=f"Joined {community_id} successfully.",
        )

    def _execute_group_message(self, action: LiveActionRecord) -> DispatchOutcome:
        message_input = self._extract_message_input(action)
        if isinstance(message_input, DispatchOutcome):
            return message_input
        chat_id, text, approval_context = message_input
        if self._messaging_capability is None:
            return DispatchOutcome(
                outcome_code="unsupported_action",
                blocked=True,
                error="Messaging capability is not available in this runtime.",
                summary="Blocked a message send because no messaging capability is available.",
            )
        outcome = self._normalize_capability_result(
            self._messaging_capability.send_message(
                action.account_id,
                chat_id,
                text,
                approval_context=approval_context,
            ),
            success_summary=f"Sent a group message into {chat_id}.",
        )
        outcome = self._finalize_visible_send_outcome(
            outcome,
            action_label=f"group message into {chat_id}",
        )
        if outcome.success:
            self._record_outbound_conversation_delivery(action, outcome)
        return outcome

    def _execute_group_reply(self, action: LiveActionRecord) -> DispatchOutcome:
        message_input = self._extract_message_input(action)
        if isinstance(message_input, DispatchOutcome):
            return message_input
        chat_id, text, approval_context = message_input
        reply_to_message_id = self._resolve_reply_target_message_id(action)
        if isinstance(reply_to_message_id, DispatchOutcome):
            return reply_to_message_id
        if not reply_to_message_id:
            return DispatchOutcome(
                outcome_code="invalid_action_payload",
                blocked=True,
                error="Group replies require a reply target message id.",
                summary="Blocked a group reply because no reply target could be resolved.",
            )
        if self._messaging_capability is None:
            return DispatchOutcome(
                outcome_code="unsupported_action",
                blocked=True,
                error="Messaging capability is not available in this runtime.",
                summary="Blocked a group reply because no messaging capability is available.",
            )
        outcome = self._normalize_capability_result(
            self._messaging_capability.send_reply(
                action.account_id,
                chat_id,
                reply_to_message_id,
                text,
                approval_context=approval_context,
            ),
            success_summary=f"Sent a group reply into {chat_id}.",
        )
        outcome = self._finalize_visible_send_outcome(
            outcome,
            action_label=f"group reply into {chat_id}",
        )
        if outcome.success:
            self._record_outbound_conversation_delivery(action, outcome)
        return outcome

    def _execute_dm_reply(self, action: LiveActionRecord) -> DispatchOutcome:
        message_input = self._extract_message_input(action)
        if isinstance(message_input, DispatchOutcome):
            return message_input
        chat_id, text, approval_context = message_input
        if self._messaging_capability is None:
            return DispatchOutcome(
                outcome_code="unsupported_action",
                blocked=True,
                error="Messaging capability is not available in this runtime.",
                summary="Blocked a DM reply because no messaging capability is available.",
            )
        reply_to_message_id = self._resolve_reply_target_message_id(action)
        if isinstance(reply_to_message_id, DispatchOutcome):
            return reply_to_message_id
        if reply_to_message_id:
            outcome = self._normalize_capability_result(
                self._messaging_capability.send_reply(
                    action.account_id,
                    chat_id,
                    reply_to_message_id,
                    text,
                    approval_context=approval_context,
                ),
                success_summary=f"Sent a DM reply into {chat_id}.",
            )
        else:
            outcome = self._normalize_capability_result(
                self._messaging_capability.send_message(
                    action.account_id,
                    chat_id,
                    text,
                    approval_context=approval_context,
                ),
                success_summary=f"Sent a DM reply into {chat_id}.",
            )
        outcome = self._finalize_visible_send_outcome(
            outcome,
            action_label=f"DM reply into {chat_id}",
        )
        if outcome.success:
            self._record_outbound_conversation_delivery(action, outcome)
        return outcome

    def _execute_mark_read(self, action: LiveActionRecord) -> DispatchOutcome:
        chat_id = str(action.payload.get("chat_id", "")).strip()
        if not chat_id:
            return DispatchOutcome(
                outcome_code="invalid_action_payload",
                blocked=True,
                error="mark_read actions require payload.chat_id.",
                summary="Blocked a read-state action because the payload did not include a chat id.",
            )
        if self._messaging_capability is None:
            return DispatchOutcome(
                outcome_code="unsupported_action",
                blocked=True,
                error="Messaging capability is not available in this runtime.",
                summary="Blocked a read-state action because no messaging capability is available.",
            )
        message_id = str(action.payload.get("message_id", "")).strip() or None
        outcome = self._normalize_capability_result(
            self._messaging_capability.mark_read(
                action.account_id,
                chat_id,
                message_id=message_id,
            ),
            success_summary=f"Marked {chat_id} as read.",
        )
        return outcome

    def _execute_leave_dialog(self, action: LiveActionRecord) -> DispatchOutcome:
        peer_id = str(action.payload.get("peer_id", "")).strip() or str(action.payload.get("chat_id", "")).strip()
        if not peer_id:
            return DispatchOutcome(
                outcome_code="invalid_action_payload",
                blocked=True,
                error="leave_dialog actions require payload.peer_id or payload.chat_id.",
                summary="Blocked a leave-dialog action because the payload did not include a peer id.",
            )
        if self._messaging_capability is None:
            return DispatchOutcome(
                outcome_code="unsupported_action",
                blocked=True,
                error="Messaging capability is not available in this runtime.",
                summary="Blocked a leave-dialog action because no messaging capability is available.",
            )
        return self._normalize_capability_result(
            self._messaging_capability.leave_dialog(action.account_id, peer_id),
            success_summary=f"Left dialog {peer_id}.",
        )

    def _resolve_reply_target_message_id(self, action: LiveActionRecord) -> str | DispatchOutcome:
        payload_reply_target = str(action.payload.get("reply_to_message_id", "")).strip()
        if self._conversation_manager is None or not action.conversation_id:
            return payload_reply_target
        conversation = self._conversation_manager.get(action.campaign_id, action.conversation_id)
        if conversation is None:
            return payload_reply_target
        conversation_reply_target = conversation.reply_target_message_id.strip()
        if payload_reply_target and conversation_reply_target and payload_reply_target != conversation_reply_target:
            return DispatchOutcome(
                outcome_code="reply_target_mismatch",
                blocked=True,
                error="The queued reply target no longer matches the current conversation state.",
                summary="Blocked a reply because the stored conversation reply target changed after this action was queued.",
            )
        if payload_reply_target:
            return payload_reply_target
        return conversation_reply_target

    def _extract_message_input(
        self,
        action: LiveActionRecord,
    ) -> tuple[str, str, dict[str, object]] | DispatchOutcome:
        chat_id = str(action.payload.get("chat_id", "")).strip()
        text = str(action.payload.get("text", ""))
        if not chat_id or not text.strip():
            return DispatchOutcome(
                outcome_code="invalid_action_payload",
                blocked=True,
                error=f"{action.action_type.value} actions require payload.chat_id and payload.text.",
                summary="Blocked a message action because the payload was incomplete.",
            )
        raw_approval_context = action.payload.get("approval_context", {})
        approval_context = dict(raw_approval_context) if isinstance(raw_approval_context, dict) else {}
        approval_context.setdefault("campaign_id", action.campaign_id)
        if action.conversation_id:
            approval_context.setdefault("conversation_id", action.conversation_id)
        raw_asset_refs = action.payload.get("asset_refs", [])
        if "asset_refs" not in approval_context and isinstance(raw_asset_refs, list):
            normalized_asset_refs = [str(value).strip() for value in raw_asset_refs if str(value).strip()]
            if normalized_asset_refs:
                approval_context["asset_refs"] = normalized_asset_refs
        return chat_id, text, approval_context

    def evaluate_policy(
        self,
        action: LiveActionRecord,
        *,
        now: datetime | None = None,
    ) -> LiveActionPolicyDecision:
        """Expose the live-engagement policy evaluation for queue-time callers."""
        return self._policy_evaluator.evaluate(action, now=now)

    def _evaluate_action_policy(
        self,
        action: LiveActionRecord,
        *,
        now: datetime,
    ) -> DispatchOutcome | None:
        decision = self.evaluate_policy(action, now=now)
        if decision.decision is LiveActionPolicyDecisionType.ALLOWED:
            return None
        return self._build_policy_outcome(decision, now=now)

    def _build_policy_outcome(
        self,
        decision: LiveActionPolicyDecision,
        *,
        now: datetime,
    ) -> DispatchOutcome:
        result_data = decision.to_result_data(now=now)
        error = decision.summary

        if decision.decision is LiveActionPolicyDecisionType.COOLDOWN:
            return DispatchOutcome(
                outcome_code=decision.primary_reason_code(),
                retryable=True,
                error=error,
                wait_seconds=decision.wait_seconds(now=now),
                result_data=result_data,
                summary=decision.summary,
            )

        return DispatchOutcome(
            outcome_code=decision.primary_reason_code(),
            blocked=True,
            error=error,
            result_data=result_data,
            summary=decision.summary,
        )

    def _record_engagement_policy_outcome(
        self,
        action: LiveActionRecord,
        outcome: DispatchOutcome,
    ) -> None:
        if self._engagement_policy_service is None:
            return
        raw_policy_context = action.payload.get("engagement_policy_context", {})
        if not isinstance(raw_policy_context, dict) or not raw_policy_context:
            return
        self._engagement_policy_service.record_execution_outcome(
            action.campaign_id,
            outcome_code=outcome.outcome_code,
            policy_context=raw_policy_context,
        )

    def pause_campaign(self, campaign_id: str) -> bool:
        """Pause all automatic live engagement for one campaign."""
        if self._campaign_manager is None:
            return False
        updated = self._campaign_manager.update_status(campaign_id, CampaignStatus.PAUSED)
        return updated is not None

    def resume_campaign(self, campaign_id: str) -> bool:
        """Resume automatic live engagement for one campaign."""
        if self._campaign_manager is None:
            return False
        updated = self._campaign_manager.update_status(campaign_id, CampaignStatus.ACTIVE)
        return updated is not None

    def pause_account(self, account_id: str, *, reason: str = "operator_pause") -> bool:
        """Pause one managed account across campaigns."""
        if self._policy_state_manager is None:
            return False
        self._policy_state_manager.pause_account(account_id, reason=reason)
        return True

    def resume_account(self, account_id: str) -> bool:
        """Resume one managed account across campaigns."""
        if self._policy_state_manager is None:
            return False
        self._policy_state_manager.resume_account(account_id)
        return True

    def pause_conversation(
        self,
        campaign_id: str,
        conversation_id: str,
        *,
        reason: str = "operator_pause",
    ) -> bool:
        """Pause one external conversation thread."""
        if self._conversation_manager is None:
            return False
        updated = self._conversation_manager.update_status(
            campaign_id,
            conversation_id,
            status=ExternalConversationStatus.PAUSED,
            operator_hold_reason=reason,
            status_reason=reason,
            next_action_type="operator_review",
            next_action_reason="This conversation is paused until the operator resumes it.",
        )
        return updated is not None

    def resume_conversation(self, campaign_id: str, conversation_id: str) -> bool:
        """Resume one paused or escalated conversation thread."""
        if self._conversation_manager is None:
            return False
        updated = self._conversation_manager.update_status(
            campaign_id,
            conversation_id,
            status=ExternalConversationStatus.ACTIVE,
            operator_hold_reason="",
            status_reason="",
            next_action_type="review_inbound",
            next_action_reason="Conversation resumed for bounded live engagement.",
        )
        return updated is not None

    def _normalize_capability_result(
        self,
        result: CapabilityResult,
        *,
        success_summary: str,
    ) -> DispatchOutcome:
        outcome_code = str(result.data.get("outcome_code", "")).strip() or ("success" if result.success else "failed")
        wait_seconds = int(result.data["wait_seconds"]) if result.data.get("wait_seconds") is not None else None
        summary = success_summary if result.success else (result.error or f"Live execution failed with outcome {outcome_code}.")

        if result.success:
            return DispatchOutcome(
                outcome_code=outcome_code,
                success=True,
                result_data=dict(result.data),
                summary=summary,
            )
        if outcome_code in _RETRYABLE_OUTCOME_CODES or (wait_seconds is not None and wait_seconds > 0):
            return DispatchOutcome(
                outcome_code=outcome_code,
                retryable=True,
                error=result.error,
                wait_seconds=wait_seconds,
                result_data=dict(result.data),
                summary=summary,
            )
        if outcome_code in _BLOCKED_OUTCOME_CODES:
            return DispatchOutcome(
                outcome_code=outcome_code,
                blocked=True,
                error=result.error,
                wait_seconds=wait_seconds,
                result_data=dict(result.data),
                summary=summary,
            )
        return DispatchOutcome(
            outcome_code=outcome_code,
            error=result.error,
            wait_seconds=wait_seconds,
            result_data=dict(result.data),
            summary=summary,
        )

    def _finalize_visible_send_outcome(
        self,
        outcome: DispatchOutcome,
        *,
        action_label: str,
    ) -> DispatchOutcome:
        if outcome.success or outcome.outcome_code != "transient_error":
            return outcome
        result_data = dict(outcome.result_data)
        result_data.setdefault("delivery_state", "uncertain")
        error = outcome.error or (
            "Telegram reported a transient send failure and delivery could not be verified safely."
        )
        return DispatchOutcome(
            outcome_code=outcome.outcome_code,
            error=error,
            wait_seconds=outcome.wait_seconds,
            result_data=result_data,
            summary=(
                f"Stopped automatic retry after an ambiguous Telegram send failure for {action_label} "
                "to avoid duplicate visible posts."
            ),
        )

    def _apply_outcome(
        self,
        action: LiveActionRecord,
        outcome: DispatchOutcome,
        *,
        finished_at: datetime,
    ) -> LiveActionRecord:
        action.claimed_by = ""
        action.claimed_at = None
        action.claim_expires_at = None
        action.last_result_summary = outcome.summary

        if outcome.success:
            action.status = LiveActionStatus.SUCCEEDED
            action.last_error = ""
            action.terminal_failure_reason = ""
            action.completed_at = finished_at
            action.next_attempt_at = None
        elif outcome.blocked:
            action.status = LiveActionStatus.BLOCKED
            action.last_error = outcome.error
            action.terminal_failure_reason = outcome.error
            action.completed_at = finished_at
            action.next_attempt_at = None
        elif outcome.retryable and action.retry_count < action.max_retries:
            action.retry_count += 1
            action.status = LiveActionStatus.RETRY_WAIT
            action.last_error = outcome.error
            action.terminal_failure_reason = ""
            action.completed_at = None
            action.next_attempt_at = finished_at + timedelta(
                seconds=self._compute_retry_delay_seconds(
                    action,
                    action.retry_count,
                    wait_seconds=outcome.wait_seconds,
                )
            )
        else:
            if not outcome.success:
                action.retry_count += 1
            action.status = LiveActionStatus.FAILED
            action.last_error = outcome.error
            action.terminal_failure_reason = outcome.error or outcome.summary
            action.completed_at = finished_at
            action.next_attempt_at = None

        action.touch()
        return action

    def _apply_outcome_side_effects(
        self,
        action: LiveActionRecord,
        outcome: DispatchOutcome,
        *,
        finished_at: datetime,
    ) -> None:
        if outcome.success:
            self._handle_success_outcome(action)
            return

        if self._should_track_handoff(action):
            if outcome.blocked:
                self._record_blocked_handoff(action, outcome)
            elif not outcome.retryable:
                self._record_failed_handoff(action, outcome)

        if outcome.outcome_code == "rate_limited" and outcome.wait_seconds:
            self._handle_rate_limited_outcome(action, outcome, finished_at=finished_at)
            return

        if outcome.outcome_code in {"account_flagged", "account_banned"}:
            self._handle_account_health_outcome(action, outcome, finished_at=finished_at)
            return

        if outcome.outcome_code == "write_forbidden":
            self._handle_write_forbidden_outcome(action, outcome, finished_at=finished_at)
            return

        if outcome.outcome_code == "policy_blocked":
            self._handle_generic_policy_block(action, outcome, finished_at=finished_at)

    def _compute_retry_delay_seconds(
        self,
        action: LiveActionRecord,
        retry_count: int,
        *,
        wait_seconds: int | None,
    ) -> int:
        if wait_seconds is not None and wait_seconds > 0:
            return min(wait_seconds, self._retry_max_delay_seconds)
        delay = self._retry_base_delay_seconds * (2 ** max(retry_count - 1, 0))
        jittered_delay = max(int(delay * self._retry_jitter_multiplier(action, retry_count)), 1)
        return min(jittered_delay, self._retry_max_delay_seconds)

    def _retry_jitter_multiplier(self, action: LiveActionRecord, retry_count: int) -> float:
        key = "|".join(
            [
                action.account_id,
                action.action_type.value,
                action.conversation_id,
                action.action_id,
                str(retry_count),
            ]
        )
        digest = hashlib.sha256(key.encode("utf-8")).digest()
        sample = int.from_bytes(digest[:2], byteorder="big") / 65535
        return 0.8 + (sample * 0.4)

    def _record_outbound_conversation_delivery(
        self,
        action: LiveActionRecord,
        outcome: DispatchOutcome,
    ) -> None:
        if self._conversation_manager is None or not action.conversation_id:
            return
        message_id = str(outcome.result_data.get("message_id", "")).strip()
        raw_sent_at = str(outcome.result_data.get("date", "")).strip()
        sent_at = parse_datetime(raw_sent_at) or datetime.now(UTC)
        if not message_id:
            return
        conversation = self._conversation_manager.record_outbound_delivery(
            action.campaign_id,
            action.conversation_id,
            message_id=message_id,
            sent_at=sent_at,
            next_action_type="wait_for_inbound",
            next_action_reason="Await the next external response before sending anything else.",
        )
        if conversation is None or self._conversation_timing_service is None:
            self._record_delivered_handoff(action)
            return
        self._refresh_follow_up_window_after_outbound_delivery(conversation=conversation, sent_at=sent_at)
        self._record_delivered_handoff(action)

    def _refresh_follow_up_window_after_outbound_delivery(
        self,
        *,
        conversation,
        sent_at: datetime,
    ) -> None:
        if self._conversation_timing_service is None:
            return

        if conversation.follow_up_window_type is not None and conversation.follow_up_due_at is not None:
            conversation = (
                self._conversation_timing_service.mark_follow_up_sent(
                    conversation.campaign_id,
                    conversation.conversation_id,
                )
                or conversation
            )

        if conversation.thread_origin is ThreadOrigin.GROUP_REPLY:
            self._conversation_timing_service.schedule_group_follow_up(
                conversation.campaign_id,
                conversation.conversation_id,
                silence_started_at=sent_at,
            )
            return

        self._conversation_timing_service.schedule_dm_follow_up(
            conversation.campaign_id,
            conversation.conversation_id,
            silence_started_at=sent_at,
        )

    def _community_chat_id_for_action(self, action: LiveActionRecord) -> str:
        if action.action_type not in {LiveActionType.SEND_GROUP_MESSAGE, LiveActionType.SEND_GROUP_REPLY}:
            return ""
        payload_chat_id = str(action.payload.get("chat_id", "")).strip()
        if payload_chat_id:
            return payload_chat_id
        if self._conversation_manager is None or not action.conversation_id:
            return ""
        conversation = self._conversation_manager.get(action.campaign_id, action.conversation_id)
        if conversation is None:
            return ""
        return conversation.chat_id.strip()

    def _community_id_for_action(self, action: LiveActionRecord) -> str:
        payload_community_id = str(action.payload.get("community_id", "")).strip()
        if payload_community_id:
            return payload_community_id
        if self._conversation_manager is None or not action.conversation_id:
            return ""
        conversation = self._conversation_manager.get(action.campaign_id, action.conversation_id)
        if conversation is None:
            return ""
        return conversation.community_id.strip()

    def _handle_success_outcome(self, action: LiveActionRecord) -> None:
        if self._policy_state_manager is not None:
            self._policy_state_manager.clear_account_cooldown(action.account_id)

    def _handle_rate_limited_outcome(
        self,
        action: LiveActionRecord,
        outcome: DispatchOutcome,
        *,
        finished_at: datetime,
    ) -> None:
        if self._policy_state_manager is not None and outcome.wait_seconds is not None:
            self._policy_state_manager.record_account_rate_limit(
                action.account_id,
                wait_seconds=outcome.wait_seconds,
                reason=outcome.error or outcome.summary,
                now=finished_at,
            )
        wait_seconds = outcome.wait_seconds or 0
        self._append_operational_note(
            action.campaign_id,
            destination=EXECUTION_LOG_DESTINATION,
            line=(
                f"Managed account `{action.account_id}` hit a rate limit for {wait_seconds} seconds "
                f"while running `{action.action_type.value}`."
            ),
            category="rate_limited",
            dedupe_key=f"rate-limited:{action.action_id}",
            recorded_at=finished_at,
        )
        self._record_campaign_signal(
            action,
            signal_type="account_rate_limited",
            severity=CampaignSignalSeverity.MEDIUM,
            summary=(
                f"Managed account `{action.account_id}` hit a rate limit for {wait_seconds} seconds "
                f"while running `{action.action_type.value}`."
            ),
            happened_at=finished_at,
            review_eligible=False,
        )

    def _handle_account_health_outcome(
        self,
        action: LiveActionRecord,
        outcome: DispatchOutcome,
        *,
        finished_at: datetime,
    ) -> None:
        if self._policy_state_manager is not None:
            self._policy_state_manager.pause_account(action.account_id, reason=outcome.error or outcome.summary)
        status_word = "flagged" if outcome.outcome_code == "account_flagged" else "banned"
        self._append_operational_note(
            action.campaign_id,
            destination=EXECUTION_LOG_DESTINATION,
            line=(
                f"Managed account `{action.account_id}` was marked {status_word} during "
                f"`{action.action_type.value}`."
            ),
            category=outcome.outcome_code,
            dedupe_key=f"{outcome.outcome_code}:{action.action_id}",
            recorded_at=finished_at,
        )
        self._append_operational_note(
            action.campaign_id,
            destination=NEXT_ACTIONS_DESTINATION,
            line=f"Review whether managed account `{action.account_id}` should be rested or replaced before more live engagement.",
            category=outcome.outcome_code,
            dedupe_key=f"{outcome.outcome_code}:account:{action.account_id}",
            recorded_at=finished_at,
        )
        self._record_campaign_signal(
            action,
            signal_type="account_flagged_or_banned",
            severity=CampaignSignalSeverity.CRITICAL,
            summary=(
                f"Managed account `{action.account_id}` was marked {status_word} during "
                f"`{action.action_type.value}`."
            ),
            happened_at=finished_at,
            review_eligible=True,
        )

    def _handle_write_forbidden_outcome(
        self,
        action: LiveActionRecord,
        outcome: DispatchOutcome,
        *,
        finished_at: datetime,
    ) -> None:
        community_chat_id = self._community_chat_id_for_action(action)
        if not community_chat_id:
            return

        community_id = self._community_id_for_action(action)
        community_state = None
        if self._policy_state_manager is not None:
            community_state = self._policy_state_manager.record_community_write_friction(
                action.campaign_id,
                community_chat_id,
                reason=outcome.error or outcome.summary,
                community_id=community_id,
                now=finished_at,
            )

        self._append_operational_note(
            action.campaign_id,
            destination=EXECUTION_LOG_DESTINATION,
            line=(
                f"Community path `{community_chat_id}` rejected a managed-account write during "
                f"`{action.action_type.value}`."
            ),
            category="write_forbidden",
            dedupe_key=f"write-forbidden:{action.action_id}",
            recorded_at=finished_at,
        )
        self._record_campaign_signal(
            action,
            signal_type="community_write_friction",
            severity=CampaignSignalSeverity.MEDIUM,
            summary=(
                f"Community path `{community_id or community_chat_id}` rejected a managed-account write during "
                f"`{action.action_type.value}`."
            ),
            community_id=community_id or community_chat_id,
            happened_at=finished_at,
            review_eligible=False,
            context_refs=[f"community_chat:{community_chat_id}"],
        )
        if community_state is not None and community_state.is_paused:
            self._append_operational_note(
                action.campaign_id,
                destination=NEXT_ACTIONS_DESTINATION,
                line=(
                    f"Pause or avoid community `{community_state.community_id or community_state.chat_id}` "
                    "because repeated moderation friction has triggered a risk pause."
                ),
                category="community_risk_pause",
                dedupe_key=f"community-risk-pause:{action.campaign_id}:{community_chat_id}",
                recorded_at=finished_at,
            )
            self._append_operational_note(
                action.campaign_id,
                destination=EXECUTION_LOG_DESTINATION,
                line=(
                    f"Community path `{community_state.community_id or community_state.chat_id}` was risk-paused "
                    "after repeated write-forbidden outcomes."
                ),
                category="community_risk_pause",
                dedupe_key=f"community-risk-pause-log:{action.campaign_id}:{community_chat_id}",
                recorded_at=finished_at,
            )
            self._record_campaign_signal(
                action,
                signal_type="community_paused_for_risk",
                severity=CampaignSignalSeverity.HIGH,
                summary=(
                    f"Community path `{community_state.community_id or community_state.chat_id}` was risk-paused "
                    "after repeated write-forbidden outcomes."
                ),
                community_id=community_state.community_id or community_state.chat_id,
                happened_at=finished_at,
                review_eligible=True,
                context_refs=[f"community_chat:{community_chat_id}"],
            )

    def _handle_generic_policy_block(
        self,
        action: LiveActionRecord,
        outcome: DispatchOutcome,
        *,
        finished_at: datetime,
    ) -> None:
        self._append_operational_note(
            action.campaign_id,
            destination=EXECUTION_LOG_DESTINATION,
            line=outcome.summary or "A live action was blocked by policy.",
            category="policy_blocked",
            dedupe_key=f"policy-blocked:{action.action_id}",
            recorded_at=finished_at,
        )
        self._append_operational_note(
            action.campaign_id,
            destination=NEXT_ACTIONS_DESTINATION,
            line="Review campaign guidance because a live action was blocked by policy in a way that may require a workflow adjustment.",
            category="policy_blocked",
            dedupe_key=f"policy-blocked:{action.campaign_id}",
            recorded_at=finished_at,
        )
        self._record_campaign_signal(
            action,
            signal_type="policy_block_repeated",
            severity=CampaignSignalSeverity.MEDIUM,
            summary=outcome.summary or "A live action was blocked by policy.",
            happened_at=finished_at,
            review_eligible=True,
        )

    def _record_campaign_signal(
        self,
        action: LiveActionRecord,
        *,
        signal_type: str,
        severity: CampaignSignalSeverity,
        summary: str,
        happened_at: datetime,
        review_eligible: bool,
        community_id: str = "",
        context_refs: list[str] | None = None,
    ) -> None:
        if self._signal_bridge is None:
            return
        self._signal_bridge.record(
            campaign_id=action.campaign_id,
            source_kind="live_execution",
            source_ref=action.action_id,
            signal_type=signal_type,
            severity=severity,
            summary=summary,
            context_refs=list(context_refs or []),
            account_id=action.account_id,
            community_id=community_id.strip(),
            conversation_id=action.conversation_id,
            happened_at=happened_at,
            review_eligible=review_eligible,
            trigger_source="live_execution",
        )

    def _append_operational_note(
        self,
        campaign_id: str,
        *,
        destination: str,
        line: str,
        category: str,
        dedupe_key: str,
        recorded_at: datetime,
    ) -> None:
        if self._campaign_manager is None or not campaign_id.strip():
            return
        self._campaign_manager.append_operational_note(
            campaign_id,
            destination=destination,
            line=line,
            category=category,
            dedupe_key=dedupe_key,
            recorded_at=recorded_at,
        )

    def _approval_context_for_action(self, action: LiveActionRecord) -> dict[str, object]:
        raw_approval_context = action.payload.get("approval_context", {})
        return dict(raw_approval_context) if isinstance(raw_approval_context, dict) else {}

    def _should_track_handoff(self, action: LiveActionRecord) -> bool:
        if self._qualification_service is None or not action.conversation_id:
            return False
        return bool(self._approval_context_for_action(action).get("handoff_intent", False))

    def _handoff_target_summary(self, action: LiveActionRecord) -> str:
        approval_context = self._approval_context_for_action(action)
        summary = str(approval_context.get("handoff_target_summary", "")).strip()
        return summary or "the campaign conversion target"

    def _record_delivered_handoff(self, action: LiveActionRecord) -> None:
        if not self._should_track_handoff(action):
            return
        self._qualification_service.mark_handoff_delivered(
            action.campaign_id,
            action.conversation_id,
            action_id=action.action_id,
            summary=f"Delivered a conversion handoff toward {self._handoff_target_summary(action)}.",
        )

    def _record_blocked_handoff(self, action: LiveActionRecord, outcome: DispatchOutcome) -> None:
        if not self._should_track_handoff(action):
            return
        self._qualification_service.mark_handoff_blocked(
            action.campaign_id,
            action.conversation_id,
            action_id=action.action_id,
            summary=(
                f"Blocked a conversion handoff toward {self._handoff_target_summary(action)}. "
                f"Reason: {outcome.summary or outcome.error or outcome.outcome_code}."
            ),
        )

    def _record_failed_handoff(self, action: LiveActionRecord, outcome: DispatchOutcome) -> None:
        if not self._should_track_handoff(action):
            return
        self._qualification_service.mark_handoff_failed(
            action.campaign_id,
            action.conversation_id,
            action_id=action.action_id,
            summary=(
                f"Failed to deliver a conversion handoff toward {self._handoff_target_summary(action)}. "
                f"Reason: {outcome.summary or outcome.error or outcome.outcome_code}."
            ),
        )
