"""Normalized live-engagement policy checks for queued execution actions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from telegram_app.campaigns import CampaignManager
from telegram_app.capabilities.mtproto.registry import AccountRegistry, parse_iso8601
from telegram_app.external_conversations import (
    ConsentPosture,
    ExternalConversationManager,
    ExternalConversationRecord,
    ExternalConversationStatus,
    ThreadOrigin,
)
from telegram_app.models import CampaignStatus
from telegram_app.live_execution.models import LiveActionRecord, LiveActionType
from telegram_app.live_execution.policy_state import LiveExecutionPolicyStateManager

_MESSAGE_ACTION_TYPES = frozenset(
    {
        LiveActionType.SEND_GROUP_MESSAGE,
        LiveActionType.SEND_GROUP_REPLY,
        LiveActionType.SEND_DM_REPLY,
    }
)
_BLOCKING_CONVERSATION_STATUSES = {
    ExternalConversationStatus.BLOCKED: "conversation_blocked",
    ExternalConversationStatus.CLOSED: "conversation_closed",
}
_REGISTRY_ACTION_BY_LIVE_ACTION = {
    LiveActionType.JOIN_COMMUNITY: "join",
    LiveActionType.SEND_GROUP_MESSAGE: "send_group_message",
    LiveActionType.SEND_GROUP_REPLY: "send_group_reply",
    LiveActionType.SEND_DM_REPLY: "send_dm_reply",
    LiveActionType.MARK_READ: "mark_read",
    LiveActionType.LEAVE_DIALOG: "leave_dialog",
}


class LiveActionPolicyDecisionType(StrEnum):
    """Normalized policy decisions for live engagement actions."""

    ALLOWED = "allowed"
    SUGGESTED_ADJUSTMENT = "suggested_adjustment"
    COOLDOWN = "cooldown"
    BLOCKED = "blocked"


@dataclass(slots=True)
class LiveActionPolicyDecision:
    """Machine-readable live-engagement policy output."""

    decision: LiveActionPolicyDecisionType
    reason_codes: list[str] = field(default_factory=list)
    summary: str = ""
    risk_level: str = "low"
    cooldown_until: datetime | None = None
    recommended_action: str = ""
    recommended_adjustment: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def allowed(cls) -> "LiveActionPolicyDecision":
        """Build an allow decision with the default low-risk payload."""
        return cls(decision=LiveActionPolicyDecisionType.ALLOWED)

    @classmethod
    def blocked(
        cls,
        *,
        reason_codes: list[str],
        summary: str,
        evidence: dict[str, Any] | None = None,
        risk_level: str = "high",
    ) -> "LiveActionPolicyDecision":
        """Build a hard-stop policy decision."""
        return cls(
            decision=LiveActionPolicyDecisionType.BLOCKED,
            reason_codes=list(reason_codes),
            summary=summary,
            risk_level=risk_level,
            evidence=dict(evidence or {}),
        )

    def primary_reason_code(self) -> str:
        """Return the most important reason code for compact status fields."""
        return self.reason_codes[0] if self.reason_codes else self.decision.value

    def wait_seconds(self, *, now: datetime | None = None) -> int | None:
        """Return a bounded wait duration when the decision carries a cooldown."""
        if self.cooldown_until is None or now is None:
            return None
        return max(int((self.cooldown_until - now).total_seconds()), 0)

    def to_result_data(self, *, now: datetime | None = None) -> dict[str, Any]:
        """Convert the policy output into JSON-safe execution metadata."""
        payload: dict[str, Any] = {
            "policy_decision": self.decision.value,
            "reason_codes": list(self.reason_codes),
            "summary": self.summary,
            "risk_level": self.risk_level,
            "evidence": dict(self.evidence),
        }
        if self.cooldown_until is not None:
            payload["cooldown_until"] = self.cooldown_until.isoformat()
        wait_seconds = self.wait_seconds(now=now)
        if wait_seconds is not None:
            payload["wait_seconds"] = wait_seconds
        if self.recommended_action:
            payload["recommended_action"] = self.recommended_action
        if self.recommended_adjustment:
            payload["recommended_adjustment"] = self.recommended_adjustment
        return payload


class LiveActionPolicyEvaluator:
    """Evaluate deterministic MVP policy rules for one queued live action."""

    def __init__(
        self,
        *,
        campaign_manager: CampaignManager | None = None,
        account_registry: AccountRegistry | None = None,
        conversation_manager: ExternalConversationManager | None = None,
        policy_state_manager: LiveExecutionPolicyStateManager | None = None,
    ) -> None:
        self._campaign_manager = campaign_manager
        self._account_registry = account_registry
        self._conversation_manager = conversation_manager
        self._policy_state_manager = policy_state_manager

    def evaluate(
        self,
        action: LiveActionRecord,
        *,
        now: datetime | None = None,
    ) -> LiveActionPolicyDecision:
        """Return the execution-time policy decision for one queued action."""
        current_time = now or datetime.now(UTC)
        if not action.campaign_id or not action.account_id:
            return LiveActionPolicyDecision.blocked(
                reason_codes=["invalid_action_payload"],
                summary="Blocked a malformed live action without required ids.",
                evidence={"campaign_id_present": bool(action.campaign_id), "account_id_present": bool(action.account_id)},
            )

        campaign_decision = self._evaluate_campaign_state(action)
        if campaign_decision is not None:
            return campaign_decision

        approval_decision = self._evaluate_approval_context(action)
        if approval_decision is not None:
            return approval_decision

        account_decision = self._evaluate_account_state(action, now=current_time)
        if account_decision is not None:
            return account_decision

        community_decision = self._evaluate_community_state(action)
        if community_decision is not None:
            return community_decision

        if action.action_type not in _MESSAGE_ACTION_TYPES:
            return LiveActionPolicyDecision.allowed()

        if not action.conversation_id:
            if action.action_type is LiveActionType.SEND_DM_REPLY:
                return LiveActionPolicyDecision.blocked(
                    reason_codes=["conversation_not_found"],
                    summary="Blocked a DM reply because no persisted conversation was attached.",
                    evidence={"action_type": action.action_type.value},
                )
            return LiveActionPolicyDecision.allowed()

        if self._conversation_manager is None:
            return LiveActionPolicyDecision.blocked(
                reason_codes=["conversation_state_unavailable"],
                summary="Blocked a conversation-linked action because conversation state is unavailable.",
                evidence={"conversation_id": action.conversation_id},
            )

        conversation = self._conversation_manager.get(action.campaign_id, action.conversation_id)
        if conversation is None:
            return LiveActionPolicyDecision.blocked(
                reason_codes=["conversation_not_found"],
                summary="Blocked a conversation-linked action because the conversation could not be loaded.",
                evidence={"conversation_id": action.conversation_id},
            )

        status_decision = self._evaluate_conversation(action, conversation)
        if status_decision is not None:
            return status_decision
        return LiveActionPolicyDecision.allowed()

    def _evaluate_approval_context(self, action: LiveActionRecord) -> LiveActionPolicyDecision | None:
        if action.action_type not in _MESSAGE_ACTION_TYPES:
            return None

        raw_approval_context = action.payload.get("approval_context", {})
        if not isinstance(raw_approval_context, dict):
            return LiveActionPolicyDecision.blocked(
                reason_codes=["approval_context_missing"],
                summary="Blocked a live send because no structured approval context was attached.",
                evidence={"action_type": action.action_type.value},
            )

        approval_context = dict(raw_approval_context)
        if approval_context.get("approved") is not True:
            return LiveActionPolicyDecision.blocked(
                reason_codes=["approval_context_invalid"],
                summary="Blocked a live send because the approval context was not marked approved.",
                evidence={"action_type": action.action_type.value},
            )

        approval_mode = str(approval_context.get("approval_mode", "")).strip().lower()
        approval_source = str(approval_context.get("approval_source", "")).strip()
        campaign_id = str(approval_context.get("campaign_id", "")).strip()
        if not approval_mode or not approval_source or not campaign_id:
            return LiveActionPolicyDecision.blocked(
                reason_codes=["approval_context_invalid"],
                summary="Blocked a live send because required approval metadata was incomplete.",
                evidence={"action_type": action.action_type.value},
            )

        if action.conversation_id:
            approved_conversation_id = str(approval_context.get("conversation_id", "")).strip()
            if approved_conversation_id != action.conversation_id:
                return LiveActionPolicyDecision.blocked(
                    reason_codes=["approval_context_invalid"],
                    summary="Blocked a live send because its approval context targeted a different conversation.",
                    evidence={
                        "action_type": action.action_type.value,
                        "action_conversation_id": action.conversation_id,
                        "approved_conversation_id": approved_conversation_id,
                    },
                )

        if approval_mode == "autonomous":
            return self._evaluate_autonomous_approval_context(action, approval_context)
        if approval_mode == "operator":
            return self._evaluate_operator_approval_context(action, approval_context)

        return LiveActionPolicyDecision.blocked(
            reason_codes=["approval_context_invalid"],
            summary="Blocked a live send because the approval mode was not recognized.",
            evidence={"approval_mode": approval_mode, "action_type": action.action_type.value},
        )

    def _evaluate_autonomous_approval_context(
        self,
        action: LiveActionRecord,
        approval_context: dict[str, Any],
    ) -> LiveActionPolicyDecision | None:
        required_values = {
            "authorization_decision": str(approval_context.get("authorization_decision", "")).strip().lower(),
            "authorized_action_type": str(approval_context.get("authorized_action_type", "")).strip(),
            "authorized_at": str(approval_context.get("authorized_at", "")).strip(),
            "context_fingerprint": str(approval_context.get("context_fingerprint", "")).strip(),
            "autonomous_send_mode": str(approval_context.get("autonomous_send_mode", "")).strip(),
            "community_risk_level": str(approval_context.get("community_risk_level", "")).strip(),
            "conversation_risk_level": str(approval_context.get("conversation_risk_level", "")).strip(),
            "tone_contract_fingerprint": str(approval_context.get("tone_contract_fingerprint", "")).strip(),
        }
        if required_values["authorization_decision"] != "allowed" or any(
            not value for key, value in required_values.items() if key != "authorization_decision"
        ):
            return LiveActionPolicyDecision.blocked(
                reason_codes=["approval_context_invalid"],
                summary="Blocked an autonomous send because its approval context was incomplete.",
                evidence={"action_type": action.action_type.value},
            )

        if required_values["authorized_action_type"] != action.action_type.value:
            return LiveActionPolicyDecision.blocked(
                reason_codes=["approval_action_type_mismatch"],
                summary="Blocked an autonomous send because its approval context did not match the action type.",
                evidence={
                    "action_type": action.action_type.value,
                    "authorized_action_type": required_values["authorized_action_type"],
                },
            )

        if required_values["autonomous_send_mode"] != "autonomous_allowed":
            return LiveActionPolicyDecision.blocked(
                reason_codes=["autonomous_send_posture_blocked"],
                summary="Blocked an autonomous send because the stored posture does not allow it.",
                evidence={"autonomous_send_mode": required_values["autonomous_send_mode"]},
            )

        if action.conversation_id:
            approved_conversation_id = str(approval_context.get("conversation_id", "")).strip()
            if approved_conversation_id and approved_conversation_id != action.conversation_id:
                return LiveActionPolicyDecision.blocked(
                    reason_codes=["approval_context_invalid"],
                    summary="Blocked an autonomous send because its approval context targeted a different conversation.",
                    evidence={
                        "action_conversation_id": action.conversation_id,
                        "approved_conversation_id": approved_conversation_id,
                    },
                )

        if required_values["community_risk_level"] == "restricted":
            return LiveActionPolicyDecision.blocked(
                reason_codes=["autonomous_restricted_community"],
                summary="Blocked an autonomous send because the community is risk-restricted.",
                evidence={"community_risk_level": required_values["community_risk_level"]},
            )

        if required_values["conversation_risk_level"] == "high_stakes":
            return LiveActionPolicyDecision.blocked(
                reason_codes=["autonomous_high_stakes_conversation"],
                summary="Blocked an autonomous send because the conversation is high-stakes.",
                evidence={"conversation_risk_level": required_values["conversation_risk_level"]},
            )
        return None

    def _evaluate_operator_approval_context(
        self,
        action: LiveActionRecord,
        approval_context: dict[str, Any],
    ) -> LiveActionPolicyDecision | None:
        if any(
            str(approval_context.get(field, "")).strip()
            for field in ("approval_id", "source_plan_artifact_id", "approved_by")
        ):
            return None
        return LiveActionPolicyDecision.blocked(
            reason_codes=["approval_context_invalid"],
            summary="Blocked a live send because the operator approval context was incomplete.",
            evidence={"action_type": action.action_type.value},
        )

    def _evaluate_campaign_state(self, action: LiveActionRecord) -> LiveActionPolicyDecision | None:
        if self._campaign_manager is None:
            return None
        campaign = self._campaign_manager.get(action.campaign_id)
        if campaign is None or campaign.status is not CampaignStatus.PAUSED:
            return None
        return LiveActionPolicyDecision.blocked(
            reason_codes=["campaign_paused"],
            summary="Blocked an action because the campaign is paused.",
            evidence={"campaign_id": action.campaign_id, "campaign_status": campaign.status.value},
        )

    def _evaluate_account_state(
        self,
        action: LiveActionRecord,
        *,
        now: datetime,
    ) -> LiveActionPolicyDecision | None:
        if self._policy_state_manager is not None:
            account_state = self._policy_state_manager.get_account_state(action.account_id)
            if account_state is not None:
                if account_state.is_paused:
                    return LiveActionPolicyDecision.blocked(
                        reason_codes=["account_paused"],
                        summary="Blocked an action because this managed account is paused.",
                        evidence={"account_id": action.account_id, "pause_reason": account_state.pause_reason},
                    )
                if account_state.cooldown_until is not None and account_state.cooldown_until > now:
                    return LiveActionPolicyDecision(
                        decision=LiveActionPolicyDecisionType.COOLDOWN,
                        reason_codes=["account_rate_limited", "cooldown_active"],
                        summary="Deferred an action because this managed account is cooling down after a recent rate limit.",
                        risk_level="medium",
                        cooldown_until=account_state.cooldown_until,
                        recommended_adjustment="use_a_different_account_later",
                        evidence={
                            "account_id": action.account_id,
                            "cooldown_reason": account_state.cooldown_reason,
                            "recent_rate_limit_count": account_state.recent_rate_limit_count,
                        },
                    )

        if self._account_registry is None:
            return None
        record = self._account_registry.get_account(action.account_id)
        if record is None:
            return None
        if record.health == "banned":
            return LiveActionPolicyDecision.blocked(
                reason_codes=["account_banned"],
                summary="Blocked an action because this managed account is banned.",
                evidence={"account_id": action.account_id, "health": record.health},
            )
        if record.health == "flagged":
            return LiveActionPolicyDecision.blocked(
                reason_codes=["account_flagged"],
                summary="Blocked an action because this managed account is flagged.",
                evidence={"account_id": action.account_id, "health": record.health},
            )
        rate_limit_until = parse_iso8601(record.rate_limit_until)
        if rate_limit_until is not None and rate_limit_until > now:
            return LiveActionPolicyDecision(
                decision=LiveActionPolicyDecisionType.COOLDOWN,
                reason_codes=["account_rate_limited", "cooldown_active"],
                summary="Deferred an action because this managed account is currently rate-limited.",
                risk_level="medium",
                cooldown_until=rate_limit_until,
                recommended_adjustment="use_a_different_account_later",
                evidence={"account_id": action.account_id, "health": record.health},
            )
        registry_action = _REGISTRY_ACTION_BY_LIVE_ACTION.get(action.action_type)
        if not registry_action:
            return None
        allowed, reason, status = self._account_registry.can_perform_action(
            action.account_id,
            action=registry_action,
            now=now,
        )
        if allowed:
            return None
        if status is not None and status.window_expires_at > now:
            return LiveActionPolicyDecision(
                decision=LiveActionPolicyDecisionType.COOLDOWN,
                reason_codes=[f"{registry_action}_warmup_budget_reached", "warmup_budget_active"],
                summary=reason,
                risk_level="low",
                cooldown_until=status.window_expires_at,
                recommended_adjustment="use_a_different_account_or_wait",
                evidence={
                    "account_id": action.account_id,
                    "action_type": action.action_type.value,
                    "warmup_action_class": status.action_class.value,
                    "warmup_stage": status.stage_label,
                    "warmup_remaining_count": status.remaining_count,
                    "warmup_budget_limit": status.budget_limit,
                },
            )
        return LiveActionPolicyDecision.blocked(
            reason_codes=[f"{registry_action}_blocked"],
            summary=reason or "Blocked an action because the account is not currently eligible for it.",
            evidence={"account_id": action.account_id, "action_type": action.action_type.value},
        )

    def _evaluate_community_state(self, action: LiveActionRecord) -> LiveActionPolicyDecision | None:
        if self._policy_state_manager is None:
            return None
        if action.action_type not in {LiveActionType.SEND_GROUP_MESSAGE, LiveActionType.SEND_GROUP_REPLY}:
            return None

        chat_id = str(action.payload.get("chat_id", "")).strip()
        if not chat_id:
            return None

        community_state = self._policy_state_manager.get_community_state(action.campaign_id, chat_id)
        if community_state is None or not community_state.is_paused:
            return None

        return LiveActionPolicyDecision.blocked(
            reason_codes=["community_risk_pause"],
            summary="Blocked an action because this community path is paused after recent moderation friction.",
            evidence={
                "campaign_id": action.campaign_id,
                "chat_id": chat_id,
                "community_id": community_state.community_id,
                "pause_reason": community_state.pause_reason,
                "recent_write_forbidden_count": community_state.recent_write_forbidden_count,
            },
            risk_level="high",
        )

    def _evaluate_conversation(
        self,
        action: LiveActionRecord,
        conversation: ExternalConversationRecord,
    ) -> LiveActionPolicyDecision | None:
        if conversation.account_id != action.account_id:
            return LiveActionPolicyDecision.blocked(
                reason_codes=["conversation_account_mismatch"],
                summary="Blocked a conversation-linked action because it targeted the wrong managed account.",
                evidence={
                    "action_account_id": action.account_id,
                    "conversation_account_id": conversation.account_id,
                    "conversation_id": conversation.conversation_id,
                },
            )

        blocking_reason = _BLOCKING_CONVERSATION_STATUSES.get(conversation.status)
        if blocking_reason is not None:
            return LiveActionPolicyDecision.blocked(
                reason_codes=[blocking_reason],
                summary=f"Blocked an action because the conversation is {conversation.status.value}.",
                evidence={
                    "conversation_id": conversation.conversation_id,
                    "conversation_status": conversation.status.value,
                    "status_reason": conversation.status_reason,
                },
            )

        if conversation.status is ExternalConversationStatus.PAUSED:
            return LiveActionPolicyDecision.blocked(
                reason_codes=["conversation_paused"],
                summary="Blocked an action because the conversation is paused.",
                evidence={
                    "conversation_id": conversation.conversation_id,
                    "conversation_status": conversation.status.value,
                    "status_reason": conversation.status_reason,
                },
            )

        if conversation.status is ExternalConversationStatus.ESCALATED:
            return LiveActionPolicyDecision.blocked(
                reason_codes=["conversation_escalated"],
                summary="Blocked an action because the conversation is escalated.",
                evidence={
                    "conversation_id": conversation.conversation_id,
                    "conversation_status": conversation.status.value,
                    "status_reason": conversation.status_reason,
                },
            )

        if action.action_type is LiveActionType.SEND_DM_REPLY:
            return self._evaluate_dm_reply(conversation)

        if action.action_type is LiveActionType.SEND_GROUP_REPLY:
            return self._evaluate_group_reply(conversation)

        return None

    def _evaluate_dm_reply(
        self,
        conversation: ExternalConversationRecord,
    ) -> LiveActionPolicyDecision | None:
        if not conversation.external_user_messaged_first:
            return LiveActionPolicyDecision.blocked(
                reason_codes=["dm_inbound_required"],
                summary="Blocked a DM reply because inbound-first consent was not proven.",
                evidence={
                    "conversation_id": conversation.conversation_id,
                    "consent_posture": conversation.consent_posture.value,
                    "external_user_messaged_first": conversation.external_user_messaged_first,
                },
                risk_level="critical",
            )

        if conversation.consent_posture not in {ConsentPosture.INBOUND_ONLY, ConsentPosture.OPERATOR_OVERRIDE}:
            return LiveActionPolicyDecision.blocked(
                reason_codes=["consent_posture_blocked"],
                summary="Blocked a DM reply because the conversation posture does not allow it.",
                evidence={
                    "conversation_id": conversation.conversation_id,
                    "consent_posture": conversation.consent_posture.value,
                },
            )
        return None

    def _evaluate_group_reply(
        self,
        conversation: ExternalConversationRecord,
    ) -> LiveActionPolicyDecision | None:
        if conversation.thread_origin is ThreadOrigin.GROUP_REPLY and conversation.reply_target_message_id:
            return None

        return LiveActionPolicyDecision.blocked(
            reason_codes=["group_reply_lineage_required"],
            summary="Blocked a group reply because the conversation was not a valid reply thread.",
            evidence={
                "conversation_id": conversation.conversation_id,
                "reply_target_message_id": conversation.reply_target_message_id,
                "thread_origin": conversation.thread_origin.value,
            },
        )
