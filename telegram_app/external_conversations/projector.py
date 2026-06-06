"""Project campaign-resolved inbound events into durable conversation threads."""

from __future__ import annotations

from dataclasses import replace
from uuid import NAMESPACE_URL, uuid5

from telegram_app.campaign_signals import CampaignSignalBridge, CampaignSignalSeverity
from telegram_app.engagement.models import EngagementEventKind, EngagementEventRecord
from telegram_app.external_conversations.manager import ExternalConversationManager
from telegram_app.external_conversations.models import (
    ConsentPosture,
    ExternalConversationRecord,
    ExternalConversationStatus,
    ThreadOrigin,
)

DEFAULT_RECENT_MESSAGE_REF_LIMIT = 12
_PRESERVE_STATUS_ON_INBOUND = frozenset(
    {
        ExternalConversationStatus.BLOCKED,
        ExternalConversationStatus.CLOSED,
        ExternalConversationStatus.ESCALATED,
        ExternalConversationStatus.PAUSED,
    }
)


class ExternalConversationProjector:
    """Translate persisted inbound engagement events into campaign conversation state."""

    def __init__(
        self,
        manager: ExternalConversationManager,
        *,
        recent_message_ref_limit: int = DEFAULT_RECENT_MESSAGE_REF_LIMIT,
        signal_bridge: CampaignSignalBridge | None = None,
    ) -> None:
        self._manager = manager
        self._recent_message_ref_limit = max(recent_message_ref_limit, 1)
        self._signal_bridge = signal_bridge

    def project_inbound_event(self, event: EngagementEventRecord) -> ExternalConversationRecord | None:
        """Create or refresh a durable conversation thread from one inbound event."""
        campaign_id = event.campaign_id.strip()
        if not campaign_id:
            return None

        existing_for_event = self._manager.get_for_event(campaign_id, event.event_id)
        if existing_for_event is not None:
            return existing_for_event

        existing = self._resolve_existing_conversation(event)
        if event.event_kind is EngagementEventKind.GROUP_REPLY:
            conversation = self._project_group_reply(event, existing=existing)
        elif event.event_kind is EngagementEventKind.INBOUND_DM:
            conversation = self._project_inbound_dm(event, existing=existing)
        else:
            return None

        if conversation is None:
            return None
        saved = self._manager.save(conversation)
        self._manager.bind_event(campaign_id, event.event_id, saved.conversation_id)
        self._record_campaign_signal(previous=existing, updated=saved, event=event)
        return saved

    def _resolve_existing_conversation(self, event: EngagementEventRecord) -> ExternalConversationRecord | None:
        if event.event_kind is EngagementEventKind.GROUP_REPLY:
            if not event.chat_id or not event.reply_to_message_id:
                return None
            return self._manager.find_group_reply_thread(
                event.campaign_id,
                account_id=event.account_id,
                chat_id=event.chat_id,
                reply_target_message_id=event.reply_to_message_id,
            )

        if event.event_kind is EngagementEventKind.INBOUND_DM:
            peer_id = event.sender_id or event.peer_id or event.chat_id
            if not peer_id:
                return None
            return self._manager.find_by_account_peer(
                event.campaign_id,
                account_id=event.account_id,
                peer_id=peer_id,
            )

        return None

    def _project_group_reply(
        self,
        event: EngagementEventRecord,
        *,
        existing: ExternalConversationRecord | None = None,
    ) -> ExternalConversationRecord | None:
        if not event.chat_id or not event.reply_to_message_id:
            return None

        conversation = existing or self._build_group_reply_thread(event)
        return self._apply_inbound_event(conversation, event)

    def _project_inbound_dm(
        self,
        event: EngagementEventRecord,
        *,
        existing: ExternalConversationRecord | None = None,
    ) -> ExternalConversationRecord | None:
        peer_id = event.sender_id or event.peer_id or event.chat_id
        if not peer_id:
            return None

        conversation = existing or self._build_inbound_dm_thread(event, peer_id=peer_id)
        return self._apply_inbound_event(conversation, event)

    def _build_group_reply_thread(self, event: EngagementEventRecord) -> ExternalConversationRecord:
        conversation_key = "|".join(
            [
                event.campaign_id,
                event.account_id,
                "group_reply",
                event.chat_id,
                event.reply_to_message_id,
            ]
        )
        return ExternalConversationRecord(
            conversation_id=str(uuid5(NAMESPACE_URL, conversation_key)),
            campaign_id=event.campaign_id,
            account_id=event.account_id,
            peer_id=event.sender_id or event.peer_id or event.chat_id,
            chat_id=event.chat_id,
            community_id=event.community_id or event.chat_id,
            thread_origin=ThreadOrigin.GROUP_REPLY,
            external_user_id=event.sender_id,
            consent_posture=ConsentPosture.GROUP_CONTEXT_ONLY,
            reply_target_message_id=event.reply_to_message_id,
            next_action_type="review_inbound",
            next_action_reason="New group reply matched a managed-account post.",
        )

    def _build_inbound_dm_thread(self, event: EngagementEventRecord, *, peer_id: str) -> ExternalConversationRecord:
        conversation_key = "|".join(
            [
                event.campaign_id,
                event.account_id,
                "direct_inbound_dm",
                peer_id,
            ]
        )
        return ExternalConversationRecord(
            conversation_id=str(uuid5(NAMESPACE_URL, conversation_key)),
            campaign_id=event.campaign_id,
            account_id=event.account_id,
            peer_id=peer_id,
            chat_id=event.chat_id or peer_id,
            thread_origin=ThreadOrigin.DIRECT_INBOUND_DM,
            external_user_id=event.sender_id or peer_id,
            consent_posture=ConsentPosture.INBOUND_ONLY,
            external_user_messaged_first=True,
            next_action_type="review_inbound",
            next_action_reason="New inbound DM was attached to this campaign conversation.",
        )

    def _apply_inbound_event(
        self,
        conversation: ExternalConversationRecord,
        event: EngagementEventRecord,
    ) -> ExternalConversationRecord:
        recent_message_ref = f"event:{event.event_id}"
        recent_message_refs = [value for value in conversation.recent_message_refs if value != recent_message_ref]
        recent_message_refs.append(recent_message_ref)

        updated = replace(
            conversation,
            peer_id=conversation.peer_id or event.sender_id or event.peer_id or event.chat_id,
            chat_id=conversation.chat_id or event.chat_id,
            community_id=conversation.community_id or event.community_id or event.chat_id,
            external_user_id=conversation.external_user_id or event.sender_id or event.peer_id,
            last_event_id=event.event_id,
            last_inbound_at=event.occurred_at,
            last_inbound_message_id=event.message_id,
            next_action_type="review_inbound",
            next_action_reason=self._build_next_action_reason(conversation.thread_origin),
            follow_up_due_at=None,
            follow_up_window_type=None,
            follow_up_attempt_count=0,
            recent_message_refs=recent_message_refs[-self._recent_message_ref_limit :],
            summary=self._build_summary(conversation, event),
        )
        if updated.status not in _PRESERVE_STATUS_ON_INBOUND:
            updated.status = ExternalConversationStatus.ACTIVE
        if updated.thread_origin is ThreadOrigin.DIRECT_INBOUND_DM:
            updated.external_user_messaged_first = True
        return updated

    def _build_summary(self, conversation: ExternalConversationRecord, event: EngagementEventRecord) -> str:
        preview = " ".join(event.text.split())
        if len(preview) > 160:
            preview = f"{preview[:157]}..."

        if conversation.thread_origin is ThreadOrigin.GROUP_REPLY:
            summary = (
                f"Group reply thread in chat {event.chat_id or conversation.chat_id} "
                f"from {event.sender_id or conversation.external_user_id or conversation.peer_id}."
            )
        else:
            summary = f"Direct inbound DM thread with {event.sender_id or conversation.external_user_id or conversation.peer_id}."

        if preview:
            return f"{summary} Latest inbound: {preview}"
        return summary

    def _build_next_action_reason(self, origin: ThreadOrigin) -> str:
        if origin is ThreadOrigin.GROUP_REPLY:
            return "New group reply matched a managed-account post."
        return "New inbound DM arrived from the external side."

    def _record_campaign_signal(
        self,
        *,
        previous: ExternalConversationRecord | None,
        updated: ExternalConversationRecord,
        event: EngagementEventRecord,
    ) -> None:
        if previous is None or self._signal_bridge is None:
            return

        signal_type = ""
        summary = ""

        if (
            event.event_kind is EngagementEventKind.INBOUND_DM
            and previous.thread_origin is ThreadOrigin.GROUP_REPLY
        ):
            summary = (
                f"Conversation `{updated.conversation_id}` moved from a public group reply into a direct DM "
                "with the same external contact."
            )
            signal_type = "public_to_dm_transition"
        elif previous.status in _PRESERVE_STATUS_ON_INBOUND:
            summary = (
                f"Conversation `{updated.conversation_id}` received new inbound while it remained "
                f"`{previous.status.value}`."
            )
            if previous.status_reason:
                summary = f"{summary} Existing status reason: {previous.status_reason}"
            signal_type = "conversation_escalated"
        elif previous.last_inbound_message_id and previous.last_inbound_message_id != event.message_id:
            origin_label = "group reply thread" if updated.thread_origin is ThreadOrigin.GROUP_REPLY else "direct thread"
            summary = (
                f"Conversation `{updated.conversation_id}` received repeated inbound on the same "
                f"{origin_label} before the runtime responded."
            )
            signal_type = "conversation_high_intent_shift"

        if not signal_type:
            return

        self._signal_bridge.record(
            campaign_id=updated.campaign_id,
            source_kind="external_conversation",
            source_ref=updated.conversation_id,
            signal_type=signal_type,
            severity=CampaignSignalSeverity.HIGH,
            summary=summary,
            context_refs=[f"conversation:{updated.conversation_id}", f"event:{event.event_id}"],
            account_id=updated.account_id,
            community_id=updated.community_id,
            conversation_id=updated.conversation_id,
            happened_at=event.occurred_at,
            review_eligible=signal_type != "public_to_dm_transition",
            trigger_source="external_conversation",
        )
