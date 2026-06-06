"""Humanized follow-up window scheduling for external conversations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta, timezone
import random
from typing import TYPE_CHECKING, Callable

from telegram_app.external_conversations.manager import ExternalConversationManager
from telegram_app.external_conversations.models import (
    ExternalConversationRecord,
    FollowUpWindowType,
    ThreadOrigin,
)

if TYPE_CHECKING:
    from telegram_app.engagement_policy.service import CampaignEngagementPolicyService

DEFAULT_GROUP_FOLLOW_UP_MIN_HOURS = 24
DEFAULT_GROUP_FOLLOW_UP_MAX_HOURS = 48
DEFAULT_DM_FOLLOW_UP_MIN_HOURS = 24
DEFAULT_DM_FOLLOW_UP_MAX_HOURS = 48
DEFAULT_MORNING_OFFSET_MINUTES = 5
DEFAULT_MORNING_OFFSET_MAX_MINUTES = 30
DEFAULT_DM_FOLLOW_UP_LIMIT = 1
DEFAULT_QUIET_HOURS_PROFILE = "cet_0000_0800"
DEFAULT_TIMING_PROFILE = "follow_up_24h_48h"

_CET = timezone(timedelta(hours=1), name="CET")
_QUIET_HOURS_START = time(hour=0, minute=0)
_QUIET_HOURS_END = time(hour=8, minute=0)


@dataclass(slots=True)
class FollowUpTimingPolicy:
    """Choose quiet-hours-aware follow-up due times."""

    sample_int: Callable[[int, int], int] | None = None
    quiet_hours_profile: str = DEFAULT_QUIET_HOURS_PROFILE

    def choose_group_follow_up_due_at(self, silence_started_at: datetime) -> tuple[datetime, str]:
        """Choose the due time for one group follow-up review window."""
        return self._choose_due_at(
            silence_started_at,
            minimum_hours=DEFAULT_GROUP_FOLLOW_UP_MIN_HOURS,
            maximum_hours=DEFAULT_GROUP_FOLLOW_UP_MAX_HOURS,
        )

    def choose_dm_follow_up_due_at(self, silence_started_at: datetime) -> tuple[datetime, str]:
        """Choose the due time for one DM follow-up review window."""
        return self._choose_due_at(
            silence_started_at,
            minimum_hours=DEFAULT_DM_FOLLOW_UP_MIN_HOURS,
            maximum_hours=DEFAULT_DM_FOLLOW_UP_MAX_HOURS,
        )

    def _choose_due_at(
        self,
        silence_started_at: datetime,
        *,
        minimum_hours: int,
        maximum_hours: int,
    ) -> tuple[datetime, str]:
        base_time = _ensure_utc(silence_started_at)
        delay_seconds = self._sample_int(minimum_hours * 3600, maximum_hours * 3600)
        sampled_due_at = base_time + timedelta(seconds=delay_seconds)
        adjusted_due_at = self._shift_out_of_quiet_hours(sampled_due_at)
        return adjusted_due_at.astimezone(UTC), self.quiet_hours_profile

    def _shift_out_of_quiet_hours(self, due_at: datetime) -> datetime:
        local_due_at = _ensure_utc(due_at).astimezone(_CET)
        local_time = local_due_at.timetz().replace(tzinfo=None)
        if not (_QUIET_HOURS_START <= local_time < _QUIET_HOURS_END):
            return local_due_at

        morning_start = datetime.combine(local_due_at.date(), _QUIET_HOURS_END, tzinfo=_CET)
        offset_minutes = self._sample_int(
            DEFAULT_MORNING_OFFSET_MINUTES,
            DEFAULT_MORNING_OFFSET_MAX_MINUTES,
        )
        return morning_start + timedelta(minutes=offset_minutes)

    def _sample_int(self, minimum_value: int, maximum_value: int) -> int:
        sampler = self.sample_int or random.randint
        return sampler(minimum_value, maximum_value)


class ExternalConversationTimingService:
    """Persist humanized follow-up windows on campaign conversations."""

    def __init__(
        self,
        manager: ExternalConversationManager,
        *,
        policy: FollowUpTimingPolicy | None = None,
        engagement_policy_service: CampaignEngagementPolicyService | None = None,
    ) -> None:
        self._manager = manager
        self._policy = policy or FollowUpTimingPolicy()
        self._engagement_policy_service = engagement_policy_service

    def schedule_group_follow_up(
        self,
        campaign_id: str,
        conversation_id: str,
        *,
        silence_started_at: datetime,
        timing_profile: str = DEFAULT_TIMING_PROFILE,
    ) -> ExternalConversationRecord | None:
        """Open or reuse one pending group follow-up review window."""
        conversation = self._manager.get(campaign_id, conversation_id)
        if conversation is None or conversation.thread_origin is not ThreadOrigin.GROUP_REPLY:
            return None
        if self._has_pending_follow_up(conversation, FollowUpWindowType.GROUP_FOLLOW_UP):
            return conversation

        due_at, quiet_hours_profile = self._policy.choose_group_follow_up_due_at(silence_started_at)
        if self._engagement_policy_service is not None:
            due_at, quiet_hours_profile, _quiet_hours_applied = self._engagement_policy_service.apply_quiet_hours(
                campaign_id,
                due_at,
                jitter_key=f"{conversation_id}:group_follow_up",
                sample_int=self._policy._sample_int,
            )
        conversation.follow_up_due_at = due_at
        conversation.follow_up_window_type = FollowUpWindowType.GROUP_FOLLOW_UP
        conversation.timing_profile = timing_profile.strip() or DEFAULT_TIMING_PROFILE
        conversation.quiet_hours_profile = quiet_hours_profile
        conversation.next_action_type = "scheduled_group_follow_up_window"
        conversation.next_action_reason = f"Review this group thread for a follow-up after {due_at.isoformat()}."
        return self._manager.save(conversation)

    def schedule_dm_follow_up(
        self,
        campaign_id: str,
        conversation_id: str,
        *,
        silence_started_at: datetime,
        timing_profile: str = DEFAULT_TIMING_PROFILE,
    ) -> ExternalConversationRecord | None:
        """Open one pending DM follow-up review window when policy allows it."""
        conversation = self._manager.get(campaign_id, conversation_id)
        if conversation is None or conversation.thread_origin is not ThreadOrigin.DIRECT_INBOUND_DM:
            return None
        if not conversation.external_user_messaged_first:
            return None
        if conversation.follow_up_attempt_count >= DEFAULT_DM_FOLLOW_UP_LIMIT:
            return conversation
        if self._has_pending_follow_up(conversation, FollowUpWindowType.DM_FOLLOW_UP):
            return conversation

        due_at, quiet_hours_profile = self._policy.choose_dm_follow_up_due_at(silence_started_at)
        if self._engagement_policy_service is not None:
            due_at, quiet_hours_profile, _quiet_hours_applied = self._engagement_policy_service.apply_quiet_hours(
                campaign_id,
                due_at,
                jitter_key=f"{conversation_id}:dm_follow_up",
                sample_int=self._policy._sample_int,
            )
        conversation.follow_up_due_at = due_at
        conversation.follow_up_window_type = FollowUpWindowType.DM_FOLLOW_UP
        conversation.timing_profile = timing_profile.strip() or DEFAULT_TIMING_PROFILE
        conversation.quiet_hours_profile = quiet_hours_profile
        conversation.next_action_type = "scheduled_dm_follow_up_window"
        conversation.next_action_reason = f"Review this DM thread for a follow-up after {due_at.isoformat()}."
        return self._manager.save(conversation)

    def mark_follow_up_sent(
        self,
        campaign_id: str,
        conversation_id: str,
    ) -> ExternalConversationRecord | None:
        """Consume the pending follow-up window after a real follow-up send succeeds."""
        conversation = self._manager.get(campaign_id, conversation_id)
        if conversation is None or conversation.follow_up_window_type is None:
            return conversation

        conversation.follow_up_attempt_count += 1
        conversation.follow_up_due_at = None
        conversation.follow_up_window_type = None
        conversation.next_action_type = "wait_for_inbound"
        conversation.next_action_reason = "Await the next external response before sending anything else."
        return self._manager.save(conversation)

    def clear_follow_up_window(
        self,
        campaign_id: str,
        conversation_id: str,
        *,
        reset_attempt_count: bool = False,
    ) -> ExternalConversationRecord | None:
        """Clear the pending follow-up window, usually after fresh inbound activity."""
        conversation = self._manager.get(campaign_id, conversation_id)
        if conversation is None:
            return None

        conversation.follow_up_due_at = None
        conversation.follow_up_window_type = None
        if reset_attempt_count:
            conversation.follow_up_attempt_count = 0
        return self._manager.save(conversation)

    def is_follow_up_due(
        self,
        campaign_id: str,
        conversation_id: str,
        *,
        now: datetime | None = None,
    ) -> bool:
        """Return whether a pending follow-up review window is due."""
        conversation = self._manager.get(campaign_id, conversation_id)
        if conversation is None or conversation.follow_up_due_at is None:
            return False
        current_time = _ensure_utc(now or datetime.now(UTC))
        return conversation.follow_up_due_at <= current_time

    def _has_pending_follow_up(
        self,
        conversation: ExternalConversationRecord,
        window_type: FollowUpWindowType,
    ) -> bool:
        return conversation.follow_up_window_type is window_type and conversation.follow_up_due_at is not None


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
