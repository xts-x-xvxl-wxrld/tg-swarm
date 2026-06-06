"""Runtime policy service for humanized reply timing and suppression."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from hashlib import sha256
import random
from typing import TYPE_CHECKING, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from telegram_app.engagement_policy.manager import CampaignEngagementPolicyManager
from telegram_app.engagement_policy.models import (
    CampaignEngagementPolicy,
    CommunityBehaviorPolicy,
    NegativeSignalPolicy,
    QuietHoursPolicy,
    ReplyLatencyTier,
    ReplyTimingDecision,
    ReplyTimingDecisionType,
)

if TYPE_CHECKING:
    from telegram_app.engagement_brain.models import EngagementBrainContext, EngagementBrainProposal
    from telegram_app.external_conversations.models import ConversationReviewTrigger


class CampaignEngagementPolicyService:
    """Resolve reply timing, quiet-hours deferral, and suppression explicitly."""

    def __init__(
        self,
        manager: CampaignEngagementPolicyManager,
        *,
        sample_int: Callable[[int, int], int] | None = None,
    ) -> None:
        self._manager = manager
        self._sample_int = sample_int

    @property
    def manager(self) -> CampaignEngagementPolicyManager:
        """Expose the backing manager for targeted runtime composition and tests."""
        return self._manager

    def plan_reply(
        self,
        context: EngagementBrainContext,
        proposal: EngagementBrainProposal,
        *,
        trigger: ConversationReviewTrigger | None = None,
        now: datetime | None = None,
    ) -> ReplyTimingDecision:
        """Resolve whether to send now, delay, or suppress one drafted reply."""
        current_time = _ensure_utc(now or datetime.now(UTC))
        policy = self._manager.get_policy(context.conversation.campaign_id)
        community_key = self._community_key(context)
        objection_hints = list(context.conversation.triage_state.objection_hints)

        suppression_reason = self._suppression_reason(
            context,
            trigger=trigger,
            policy=policy,
        )
        if suppression_reason:
            decision = ReplyTimingDecision(
                decision_type=ReplyTimingDecisionType.SUPPRESS,
                latency_tier=ReplyLatencyTier.NO_REPLY,
                quiet_hours_profile=policy.quiet_hours.profile_name(),
                suppression_reason=suppression_reason,
                evidence={
                    "community_key": community_key,
                    "follow_up_attempt_count": context.conversation.follow_up_attempt_count,
                    "thread_origin": context.conversation.thread_origin.value,
                },
            )
            self._manager.record_timing_decision(
                context.conversation.campaign_id,
                decision=decision,
                community_key=community_key,
                objection_hints=objection_hints,
            )
            return decision

        latency_tier = self._resolve_latency_tier(context, proposal, policy=policy)
        delay_seconds = self._sample_delay_seconds(
            context,
            tier=latency_tier,
            proposal=proposal,
            trigger=trigger,
            policy=policy,
        )
        execute_at = current_time + timedelta(seconds=delay_seconds)
        execute_at, quiet_hours_profile, quiet_hours_applied = self.apply_quiet_hours(
            context.conversation.campaign_id,
            execute_at,
            jitter_key=self._jitter_key(context, proposal, trigger, suffix="quiet_hours"),
        )
        decision_type = (
            ReplyTimingDecisionType.SEND_NOW
            if execute_at <= current_time + timedelta(seconds=15)
            else ReplyTimingDecisionType.DELAY
        )
        decision = ReplyTimingDecision(
            decision_type=decision_type,
            latency_tier=latency_tier,
            execute_at=execute_at,
            quiet_hours_profile=quiet_hours_profile,
            evidence={
                "community_key": community_key,
                "delay_seconds": delay_seconds,
                "quiet_hours_applied": quiet_hours_applied,
                "community_type": self._community_type(context),
            },
        )
        self._manager.record_timing_decision(
            context.conversation.campaign_id,
            decision=decision,
            community_key=community_key,
            objection_hints=objection_hints,
        )
        return decision

    def apply_quiet_hours(
        self,
        campaign_id: str,
        due_at: datetime,
        *,
        jitter_key: str,
        sample_int: Callable[[int, int], int] | None = None,
    ) -> tuple[datetime, str, bool]:
        """Shift a chosen due time out of campaign quiet hours when needed."""
        policy = self._manager.get_policy(campaign_id).quiet_hours
        resolved_due_at = _ensure_utc(due_at)
        zone = _zoneinfo(policy.timezone_name)
        local_due_at = resolved_due_at.astimezone(zone)
        if not _is_inside_quiet_hours(local_due_at.timetz().replace(tzinfo=None), policy):
            return resolved_due_at, policy.profile_name(), False

        next_allowed_local = _next_allowed_local_time(local_due_at, policy)
        wakeup_delay_seconds = self._sample_value(
            policy.wakeup_min_delay_seconds,
            policy.wakeup_max_delay_seconds,
            key=f"{campaign_id}|{jitter_key}|wakeup",
            sample_int=sample_int,
        )
        adjusted = next_allowed_local + timedelta(seconds=wakeup_delay_seconds)
        return adjusted.astimezone(UTC), policy.profile_name(), True

    def record_execution_outcome(
        self,
        campaign_id: str,
        *,
        outcome_code: str,
        policy_context: dict[str, object],
    ) -> None:
        """Persist a lightweight execution outcome tied back to a timing decision."""
        latency_tier = ReplyLatencyTier._value2member_map_.get(
            str(policy_context.get("latency_tier", "")).strip().lower(),
            ReplyLatencyTier.SHORT_DELAY,
        )
        community_key = str(policy_context.get("community_key", "")).strip()
        raw_objection_hints = policy_context.get("objection_hints", [])
        objection_hints = [
            str(value).strip()
            for value in raw_objection_hints
            if isinstance(raw_objection_hints, list) and str(value).strip()
        ]
        self._manager.record_execution_outcome(
            campaign_id,
            outcome_code=outcome_code,
            latency_tier=latency_tier,
            community_key=community_key,
            objection_hints=objection_hints,
        )

    def _suppression_reason(
        self,
        context: EngagementBrainContext,
        *,
        trigger: ConversationReviewTrigger | None,
        policy: CampaignEngagementPolicy,
    ) -> str:
        triage_state = context.conversation.triage_state
        community_behavior = self._community_behavior(context, policy)
        negative_signal_tolerance = community_behavior.negative_signal_tolerance
        negative_signal_policy = policy.negative_signal_policy

        if (
            triage_state.low_signal_chatter
            and negative_signal_policy.suppress_low_signal_chatter
            and negative_signal_tolerance != "high"
        ):
            return "low_signal_chatter"

        if (
            triage_state.hostile_signal
            and negative_signal_policy.suppress_hostile_signal
        ):
            return "hostile_signal"

        if trigger is not None and getattr(trigger.trigger_type, "value", "") == "follow_up_due":
            follow_up_limit = self._follow_up_limit(context, negative_signal_policy)
            if context.conversation.follow_up_attempt_count >= follow_up_limit:
                return "follow_up_limit_reached"

        return ""

    def _resolve_latency_tier(
        self,
        context: EngagementBrainContext,
        proposal: EngagementBrainProposal,
        *,
        policy: CampaignEngagementPolicy,
    ) -> ReplyLatencyTier:
        community_behavior = self._community_behavior(context, policy)
        if community_behavior.reply_latency_tier is not None:
            tier = community_behavior.reply_latency_tier
        else:
            tier = policy.default_reply_latency_tier

        triage_state = context.conversation.triage_state
        if proposal.qualification_state.value == "conversion_ready":
            return ReplyLatencyTier.NEAR_IMMEDIATE
        if triage_state.urgency_level.value == "high":
            return ReplyLatencyTier.NEAR_IMMEDIATE
        if triage_state.objection_present and tier is ReplyLatencyTier.LONG_DELAY:
            return ReplyLatencyTier.SHORT_DELAY
        return tier

    def _community_behavior(
        self,
        context: EngagementBrainContext,
        policy: CampaignEngagementPolicy,
    ) -> CommunityBehaviorPolicy:
        guidance = context.community_guidance
        if guidance is not None:
            for key in [guidance.community_id.strip(), guidance.chat_id.strip()]:
                if key and key in policy.community_overrides:
                    return policy.community_overrides[key]
        community_type = self._community_type(context)
        if community_type and community_type in policy.community_type_defaults:
            return policy.community_type_defaults[community_type]
        return CommunityBehaviorPolicy()

    def _community_type(self, context: EngagementBrainContext) -> str:
        if context.community_guidance is None:
            return ""
        return context.community_guidance.community_type.strip().lower()

    def _community_key(self, context: EngagementBrainContext) -> str:
        if context.community_guidance is not None:
            for key in [context.community_guidance.community_id, context.community_guidance.chat_id]:
                if str(key).strip():
                    return str(key).strip()
        return context.conversation.community_id.strip() or context.conversation.chat_id.strip()

    def _follow_up_limit(
        self,
        context: EngagementBrainContext,
        policy: NegativeSignalPolicy,
    ) -> int:
        if context.conversation.thread_origin.value == "group_reply":
            return policy.max_group_follow_ups_without_inbound
        return policy.max_dm_follow_ups_without_inbound

    def _sample_delay_seconds(
        self,
        context: EngagementBrainContext,
        *,
        tier: ReplyLatencyTier,
        proposal: EngagementBrainProposal,
        trigger: ConversationReviewTrigger | None,
        policy: CampaignEngagementPolicy,
    ) -> int:
        if tier is ReplyLatencyTier.NO_REPLY:
            return 0
        window = policy.latency_window_for(tier)
        return self._sample_value(
            window.minimum_seconds,
            window.maximum_seconds,
            key=self._jitter_key(context, proposal, trigger, suffix=tier.value),
        )

    def _jitter_key(
        self,
        context: EngagementBrainContext,
        proposal: EngagementBrainProposal,
        trigger: ConversationReviewTrigger | None,
        *,
        suffix: str,
    ) -> str:
        return "|".join(
            [
                context.conversation.campaign_id,
                context.conversation.conversation_id,
                trigger.trigger_key if trigger is not None else context.conversation.last_event_id,
                proposal.decision.value,
                proposal.goal,
                suffix,
            ]
        )

    def _sample_value(
        self,
        minimum_value: int,
        maximum_value: int,
        *,
        key: str,
        sample_int: Callable[[int, int], int] | None = None,
    ) -> int:
        minimum = min(int(minimum_value), int(maximum_value))
        maximum = max(int(minimum_value), int(maximum_value))
        sampler = sample_int or self._sample_int
        if sampler is not None:
            return sampler(minimum, maximum)
        seed = int.from_bytes(sha256(key.encode("utf-8")).digest()[:8], byteorder="big")
        return random.Random(seed).randint(minimum, maximum)


def _zoneinfo(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _is_inside_quiet_hours(local_time: time, policy: QuietHoursPolicy) -> bool:
    start = time(hour=policy.start_hour, minute=policy.start_minute)
    end = time(hour=policy.end_hour, minute=policy.end_minute)
    if start < end:
        return start <= local_time < end
    return local_time >= start or local_time < end


def _next_allowed_local_time(local_due_at: datetime, policy: QuietHoursPolicy) -> datetime:
    end = time(hour=policy.end_hour, minute=policy.end_minute)
    if policy.start_hour < policy.end_hour or (
        policy.start_hour == policy.end_hour and policy.start_minute < policy.end_minute
    ):
        return datetime.combine(local_due_at.date(), end, tzinfo=local_due_at.tzinfo)
    if local_due_at.timetz().replace(tzinfo=None) >= time(hour=policy.start_hour, minute=policy.start_minute):
        return datetime.combine(local_due_at.date() + timedelta(days=1), end, tzinfo=local_due_at.tzinfo)
    return datetime.combine(local_due_at.date(), end, tzinfo=local_due_at.tzinfo)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
