"""Campaign-scoped persistence and lookup helpers for external conversations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
from threading import RLock
import time

from telegram_app.external_conversations.models import (
    ConversationBeliefState,
    ConsentPosture,
    ConversationReviewTrigger,
    ConversationReviewTriggerType,
    ExternalConversationRecord,
    ExternalConversationStatus,
    FollowUpWindowType,
    utc_now,
)
from telegram_app.engagement_triage.models import ConversationTriageState
from telegram_app.json_store import load_json_file, write_json_file

DEFAULT_GUARD_STALE_SECONDS = 10.0
DEFAULT_GUARD_WAIT_SECONDS = 0.05
DEFAULT_GUARD_ATTEMPTS = 5


class ExternalConversationManager:
    """Own durable conversation records and lookup indexes per campaign."""

    def __init__(self, campaigns_root: str | Path) -> None:
        self._campaigns_root = Path(campaigns_root).resolve()
        self._lock = RLock()
        self._guard_path = self._campaigns_root / ".external-conversations.lock"

    def get(self, campaign_id: str, conversation_id: str) -> ExternalConversationRecord | None:
        """Load one conversation record by id."""
        if not campaign_id or not conversation_id:
            return None
        payload = self._load_conversations_payload(campaign_id)
        raw_conversation = payload.get("conversations", {}).get(conversation_id)
        if not isinstance(raw_conversation, dict):
            return None
        conversation = ExternalConversationRecord.from_dict(raw_conversation)
        return conversation if conversation.conversation_id else None

    def list_for_campaign(self, campaign_id: str) -> list[ExternalConversationRecord]:
        """Return all known conversations for one campaign."""
        payload = self._load_conversations_payload(campaign_id)
        raw_conversations = payload.get("conversations", {})
        if not isinstance(raw_conversations, dict):
            return []
        conversations = [
            ExternalConversationRecord.from_dict(item)
            for item in raw_conversations.values()
            if isinstance(item, dict)
        ]
        return sorted(conversations, key=lambda item: item.updated_at, reverse=True)

    def save(self, conversation: ExternalConversationRecord) -> ExternalConversationRecord:
        """Persist one conversation record and refresh its lookup indexes."""
        with self._lock:
            return self._with_guard(lambda: self._save_locked(conversation))

    def bind_event(self, campaign_id: str, event_id: str, conversation_id: str) -> None:
        """Persist the event-to-conversation mapping for idempotent projection."""
        if not campaign_id or not event_id or not conversation_id:
            return
        with self._lock:
            self._with_guard(
                lambda: self._bind_event_locked(
                    campaign_id,
                    event_id,
                    conversation_id,
                )
            )

    def get_for_event(self, campaign_id: str, event_id: str) -> ExternalConversationRecord | None:
        """Resolve the conversation already linked to one inbound event."""
        if not campaign_id or not event_id:
            return None
        payload = self._load_event_links_payload(campaign_id)
        links = payload.get("event_to_conversation", {})
        if not isinstance(links, dict):
            return None
        conversation_id = str(links.get(event_id, "")).strip()
        return self.get(campaign_id, conversation_id)

    def find_by_account_peer(
        self,
        campaign_id: str,
        *,
        account_id: str,
        peer_id: str,
    ) -> ExternalConversationRecord | None:
        """Resolve the latest conversation for one account-plus-peer pair."""
        conversation_id = self._lookup_index(
            campaign_id,
            index_name="by_account_peer",
            key=self._account_peer_key(account_id, peer_id),
        )
        return self.get(campaign_id, conversation_id)

    def find_by_account_chat(
        self,
        campaign_id: str,
        *,
        account_id: str,
        chat_id: str,
    ) -> ExternalConversationRecord | None:
        """Resolve the latest conversation seen in one account-plus-chat pair."""
        conversation_id = self._lookup_index(
            campaign_id,
            index_name="latest_by_account_chat",
            key=self._account_chat_key(account_id, chat_id),
        )
        return self.get(campaign_id, conversation_id)

    def find_group_reply_thread(
        self,
        campaign_id: str,
        *,
        account_id: str,
        chat_id: str,
        reply_target_message_id: str,
    ) -> ExternalConversationRecord | None:
        """Resolve one group thread by the managed-account message lineage it replied to."""
        conversation_id = self._lookup_index(
            campaign_id,
            index_name="by_group_reply_target",
            key=self._group_reply_target_key(account_id, chat_id, reply_target_message_id),
        )
        return self.get(campaign_id, conversation_id)

    def find_by_outbound_message(
        self,
        campaign_id: str,
        *,
        account_id: str,
        chat_id: str,
        message_id: str,
    ) -> ExternalConversationRecord | None:
        """Resolve one conversation from a previously persisted outbound message id."""
        conversation_id = self._lookup_index(
            campaign_id,
            index_name="by_outbound_message",
            key=self._outbound_message_key(account_id, chat_id, message_id),
        )
        return self.get(campaign_id, conversation_id)

    def record_outbound_delivery(
        self,
        campaign_id: str,
        conversation_id: str,
        *,
        message_id: str,
        sent_at,
        next_action_type: str = "wait_for_inbound",
        next_action_reason: str = "Await the next external response before sending anything else.",
    ) -> ExternalConversationRecord | None:
        """Update the durable conversation state after a successful outbound send."""
        conversation = self.get(campaign_id, conversation_id)
        if conversation is None:
            return None

        recent_message_ref = f"outbound:{message_id.strip()}"
        recent_message_refs = [value for value in conversation.recent_message_refs if value != recent_message_ref]
        recent_message_refs.append(recent_message_ref)
        conversation.last_outbound_at = sent_at
        conversation.last_outbound_message_id = message_id.strip()
        conversation.next_action_type = next_action_type.strip()
        conversation.next_action_reason = next_action_reason.strip()
        conversation.recent_message_refs = recent_message_refs[-12:]
        return self.save(conversation)

    def update_status(
        self,
        campaign_id: str,
        conversation_id: str,
        *,
        status,
        operator_hold_reason: str = "",
        status_reason: str | None = None,
        next_action_type: str = "",
        next_action_reason: str = "",
    ) -> ExternalConversationRecord | None:
        """Persist an explicit operator or policy status change for one conversation."""
        conversation = self.get(campaign_id, conversation_id)
        if conversation is None:
            return None
        conversation.status = status
        conversation.operator_hold_reason = operator_hold_reason.strip()
        if status_reason is not None:
            conversation.status_reason = status_reason.strip()
        conversation.next_action_type = next_action_type.strip()
        conversation.next_action_reason = next_action_reason.strip()
        return self.save(conversation)

    def update_next_action(
        self,
        campaign_id: str,
        conversation_id: str,
        *,
        next_action_type: str,
        next_action_reason: str,
        status_reason: str | None = None,
    ) -> ExternalConversationRecord | None:
        """Persist a new advisory next-action state without changing conversation status."""
        conversation = self.get(campaign_id, conversation_id)
        if conversation is None:
            return None
        conversation.next_action_type = next_action_type.strip()
        conversation.next_action_reason = next_action_reason.strip()
        if status_reason is not None:
            conversation.status_reason = status_reason.strip()
        return self.save(conversation)

    def update_qualification(
        self,
        campaign_id: str,
        conversation_id: str,
        *,
        qualification_status: str,
        qualification_summary: str,
        handoff_status: str = "",
        handoff_summary: str = "",
    ) -> ExternalConversationRecord | None:
        """Persist the latest qualification and handoff readiness view."""
        conversation = self.get(campaign_id, conversation_id)
        if conversation is None:
            return None
        conversation.qualification_status = qualification_status.strip()
        conversation.qualification_summary = qualification_summary.strip()
        if handoff_status.strip():
            conversation.handoff_status = handoff_status.strip()
        if handoff_summary.strip() or conversation.handoff_status in {"blocked", "failed", "delivered"}:
            conversation.handoff_summary = handoff_summary.strip()
        return self.save(conversation)

    def update_handoff(
        self,
        campaign_id: str,
        conversation_id: str,
        *,
        handoff_status: str,
        handoff_summary: str,
        action_id: str,
        completed: bool,
    ) -> ExternalConversationRecord | None:
        """Persist the latest durable conversion handoff outcome."""
        conversation = self.get(campaign_id, conversation_id)
        if conversation is None:
            return None
        now = utc_now()
        conversation.handoff_status = handoff_status.strip()
        conversation.handoff_summary = handoff_summary.strip()
        conversation.last_handoff_action_id = action_id.strip()
        conversation.last_handoff_attempted_at = now
        if completed:
            conversation.last_handoff_completed_at = now
        return self.save(conversation)

    def update_triage_state(
        self,
        campaign_id: str,
        conversation_id: str,
        *,
        triage_state: ConversationTriageState,
        next_action_type: str = "",
        next_action_reason: str = "",
        summary: str | None = None,
    ) -> ExternalConversationRecord | None:
        """Persist the latest cheap-triage state and compatibility fields."""
        conversation = self.get(campaign_id, conversation_id)
        if conversation is None:
            return None
        conversation.triage_state = triage_state
        if next_action_type.strip():
            conversation.next_action_type = next_action_type.strip()
        if next_action_reason.strip():
            conversation.next_action_reason = next_action_reason.strip()
        if summary is not None:
            conversation.summary = summary.strip()
        return self.save(conversation)

    def update_belief_state(
        self,
        campaign_id: str,
        conversation_id: str,
        *,
        belief_state: ConversationBeliefState,
        summary: str | None = None,
    ) -> ExternalConversationRecord | None:
        """Persist the latest deeper belief state and compatibility summary."""
        conversation = self.get(campaign_id, conversation_id)
        if conversation is None:
            return None
        conversation.belief_state = belief_state
        if summary is not None:
            conversation.summary = summary.strip()
        return self.save(conversation)

    def clear_pending_autonomous_review(
        self,
        campaign_id: str,
        conversation_id: str,
    ) -> ExternalConversationRecord | None:
        """Clear any pending autonomous review linkage from the conversation state."""
        conversation = self.get(campaign_id, conversation_id)
        if conversation is None:
            return None
        if not conversation.pending_autonomous_review_id:
            return conversation
        conversation.pending_autonomous_review_id = ""
        return self.save(conversation)

    def set_pending_autonomous_review(
        self,
        campaign_id: str,
        conversation_id: str,
        *,
        review_id: str,
    ) -> ExternalConversationRecord | None:
        """Persist the current pending autonomous-review linkage for a conversation."""
        conversation = self.get(campaign_id, conversation_id)
        if conversation is None:
            return None
        conversation.pending_autonomous_review_id = review_id.strip()
        return self.save(conversation)

    def claim_next_review(
        self,
        *,
        owner_id: str,
        claim_ttl_seconds: int,
        now: datetime | None = None,
    ) -> ConversationReviewTrigger | None:
        """Atomically claim the oldest eligible conversation review trigger."""
        normalized_owner_id = owner_id.strip()
        if not normalized_owner_id:
            raise ValueError("owner_id is required to claim conversation reviews.")

        with self._lock:
            return self._with_guard(
                lambda: self._claim_next_review_locked(
                    owner_id=normalized_owner_id,
                    claim_ttl_seconds=max(claim_ttl_seconds, 1),
                    now=now or utc_now(),
                )
            )

    def release_review_claim(
        self,
        campaign_id: str,
        conversation_id: str,
        *,
        trigger_key: str = "",
    ) -> ExternalConversationRecord | None:
        """Release an in-flight review claim without recording completion."""
        with self._lock:
            return self._with_guard(
                lambda: self._release_review_claim_locked(
                    campaign_id,
                    conversation_id,
                    trigger_key=trigger_key,
                )
            )

    def complete_review_claim(
        self,
        campaign_id: str,
        conversation_id: str,
        *,
        trigger: ConversationReviewTrigger,
        disposition: str,
        summary: str,
        action_id: str = "",
    ) -> ExternalConversationRecord | None:
        """Persist completion for one claimed review trigger and clear its active claim."""
        with self._lock:
            return self._with_guard(
                lambda: self._complete_review_claim_locked(
                    campaign_id,
                    conversation_id,
                    trigger=trigger,
                    disposition=disposition,
                    summary=summary,
                    action_id=action_id,
                )
            )

    def conversations_path(self, campaign_id: str) -> Path:
        """Return the conversations state path for one campaign."""
        return self._campaign_root(campaign_id) / "external-conversations" / "conversations.json"

    def indexes_path(self, campaign_id: str) -> Path:
        """Return the conversation indexes path for one campaign."""
        return self._campaign_root(campaign_id) / "external-conversations" / "indexes.json"

    def event_links_path(self, campaign_id: str) -> Path:
        """Return the event-to-conversation mapping path for one campaign."""
        return self._campaign_root(campaign_id) / "external-conversations" / "events-to-conversations.json"

    def _save_locked(self, conversation: ExternalConversationRecord) -> ExternalConversationRecord:
        payload = self._load_conversations_payload(conversation.campaign_id)
        raw_conversations = payload.setdefault("conversations", {})
        if not isinstance(raw_conversations, dict):
            raw_conversations = {}
            payload["conversations"] = raw_conversations
        conversation.updated_at = utc_now()
        raw_conversations[conversation.conversation_id] = conversation.to_dict()
        payload["updated_at"] = conversation.updated_at.isoformat()
        self._write_conversations_payload(conversation.campaign_id, payload)
        self._update_indexes(conversation)
        return conversation

    def _bind_event_locked(self, campaign_id: str, event_id: str, conversation_id: str) -> None:
        payload = self._load_event_links_payload(campaign_id)
        links = payload.setdefault("event_to_conversation", {})
        if not isinstance(links, dict):
            links = {}
            payload["event_to_conversation"] = links
        links[event_id] = conversation_id
        payload["updated_at"] = utc_now().isoformat()
        write_json_file(self.event_links_path(campaign_id), payload)

    def _claim_next_review_locked(
        self,
        *,
        owner_id: str,
        claim_ttl_seconds: int,
        now: datetime,
    ) -> ConversationReviewTrigger | None:
        best_trigger: ConversationReviewTrigger | None = None

        for campaign_id in self._list_campaign_ids():
            payload = self._load_conversations_payload(campaign_id)
            raw_conversations = payload.get("conversations", {})
            if not isinstance(raw_conversations, dict):
                continue

            payload_changed = False
            for conversation_id, raw_conversation in raw_conversations.items():
                if not isinstance(raw_conversation, dict):
                    continue

                conversation = ExternalConversationRecord.from_dict(raw_conversation)
                if not conversation.conversation_id:
                    conversation.conversation_id = str(conversation_id).strip()
                if not conversation.campaign_id:
                    conversation.campaign_id = campaign_id

                if self._claim_active(conversation, now=now):
                    continue

                if self._claim_expired(conversation, now=now):
                    self._clear_review_claim_fields(conversation)
                    raw_conversations[conversation.conversation_id] = conversation.to_dict()
                    payload_changed = True

                trigger = self._build_review_trigger(conversation, now=now)
                if trigger is None:
                    continue
                if trigger.trigger_key == conversation.last_completed_review_trigger_key:
                    continue
                if best_trigger is None or self._trigger_sort_key(trigger) < self._trigger_sort_key(best_trigger):
                    best_trigger = trigger

            if payload_changed:
                payload["updated_at"] = now.isoformat()
                self._write_conversations_payload(campaign_id, payload)

        if best_trigger is None:
            return None

        conversation = self.get(best_trigger.campaign_id, best_trigger.conversation_id)
        if conversation is None:
            return None

        conversation.review_claimed_by = owner_id
        conversation.review_claimed_at = now
        conversation.review_claim_expires_at = datetime.fromtimestamp(
            now.timestamp() + claim_ttl_seconds,
            tz=UTC,
        )
        conversation.review_claim_trigger_key = best_trigger.trigger_key
        self._save_locked(conversation)
        return best_trigger

    def _release_review_claim_locked(
        self,
        campaign_id: str,
        conversation_id: str,
        *,
        trigger_key: str,
    ) -> ExternalConversationRecord | None:
        conversation = self.get(campaign_id, conversation_id)
        if conversation is None:
            return None
        if trigger_key and conversation.review_claim_trigger_key and trigger_key != conversation.review_claim_trigger_key:
            return conversation
        self._clear_review_claim_fields(conversation)
        return self._save_locked(conversation)

    def _complete_review_claim_locked(
        self,
        campaign_id: str,
        conversation_id: str,
        *,
        trigger: ConversationReviewTrigger,
        disposition: str,
        summary: str,
        action_id: str,
    ) -> ExternalConversationRecord | None:
        conversation = self.get(campaign_id, conversation_id)
        if conversation is None:
            return None
        if (
            conversation.review_claim_trigger_key
            and conversation.review_claim_trigger_key != trigger.trigger_key
        ):
            return None

        self._clear_review_claim_fields(conversation)
        conversation.last_completed_review_trigger_key = trigger.trigger_key
        conversation.last_completed_review_at = utc_now()
        conversation.last_completed_review_source = trigger.trigger_source.strip()
        conversation.last_completed_review_disposition = disposition.strip()
        conversation.last_completed_review_summary = summary.strip()
        conversation.last_completed_review_action_id = action_id.strip()
        return self._save_locked(conversation)

    def _build_review_trigger(
        self,
        conversation: ExternalConversationRecord,
        *,
        now: datetime,
    ) -> ConversationReviewTrigger | None:
        if conversation.status is not ExternalConversationStatus.ACTIVE:
            return None

        inbound_trigger = self._build_inbound_trigger(conversation)
        if inbound_trigger is not None:
            return inbound_trigger
        return self._build_follow_up_due_trigger(conversation, now=now)

    def _build_inbound_trigger(
        self,
        conversation: ExternalConversationRecord,
    ) -> ConversationReviewTrigger | None:
        if conversation.next_action_type != "review_inbound" or not conversation.last_event_id:
            return None
        return ConversationReviewTrigger(
            campaign_id=conversation.campaign_id,
            conversation_id=conversation.conversation_id,
            trigger_type=ConversationReviewTriggerType.INBOUND,
            trigger_source="review_inbound",
            trigger_key=f"inbound:{conversation.last_event_id}",
            eligible_at=conversation.last_inbound_at or conversation.updated_at,
            summary=conversation.next_action_reason.strip() or "Fresh inbound activity needs bounded review.",
        )

    def _build_follow_up_due_trigger(
        self,
        conversation: ExternalConversationRecord,
        *,
        now: datetime,
    ) -> ConversationReviewTrigger | None:
        if conversation.follow_up_due_at is None or conversation.follow_up_due_at > now:
            return None
        if conversation.follow_up_window_type is None:
            return None

        if conversation.follow_up_window_type is FollowUpWindowType.GROUP_FOLLOW_UP:
            trigger_source = "scheduled_group_follow_up_window"
        else:
            trigger_source = "scheduled_dm_follow_up_window"

        return ConversationReviewTrigger(
            campaign_id=conversation.campaign_id,
            conversation_id=conversation.conversation_id,
            trigger_type=ConversationReviewTriggerType.FOLLOW_UP_DUE,
            trigger_source=trigger_source,
            trigger_key=(
                "follow_up:"
                f"{conversation.follow_up_window_type.value}:"
                f"{conversation.follow_up_due_at.isoformat()}:"
                f"{conversation.follow_up_attempt_count}"
            ),
            eligible_at=conversation.follow_up_due_at,
            summary=conversation.next_action_reason.strip() or "A pending follow-up review window is due.",
        )

    def _trigger_sort_key(self, trigger: ConversationReviewTrigger) -> tuple[datetime, str, str]:
        return trigger.eligible_at, trigger.campaign_id, trigger.conversation_id

    def _claim_active(
        self,
        conversation: ExternalConversationRecord,
        *,
        now: datetime,
    ) -> bool:
        return (
            bool(conversation.review_claimed_by)
            and conversation.review_claim_expires_at is not None
            and conversation.review_claim_expires_at > now
        )

    def _claim_expired(
        self,
        conversation: ExternalConversationRecord,
        *,
        now: datetime,
    ) -> bool:
        return (
            bool(conversation.review_claimed_by)
            and conversation.review_claim_expires_at is not None
            and conversation.review_claim_expires_at <= now
        )

    def _clear_review_claim_fields(self, conversation: ExternalConversationRecord) -> None:
        conversation.review_claimed_by = ""
        conversation.review_claimed_at = None
        conversation.review_claim_expires_at = None
        conversation.review_claim_trigger_key = ""

    def _update_indexes(self, conversation: ExternalConversationRecord) -> None:
        payload = self._load_indexes_payload(conversation.campaign_id)

        by_account_peer = payload.setdefault("by_account_peer", {})
        latest_by_account_chat = payload.setdefault("latest_by_account_chat", {})
        by_group_reply_target = payload.setdefault("by_group_reply_target", {})
        by_outbound_message = payload.setdefault("by_outbound_message", {})
        if not isinstance(by_account_peer, dict):
            by_account_peer = {}
            payload["by_account_peer"] = by_account_peer
        if not isinstance(latest_by_account_chat, dict):
            latest_by_account_chat = {}
            payload["latest_by_account_chat"] = latest_by_account_chat
        if not isinstance(by_group_reply_target, dict):
            by_group_reply_target = {}
            payload["by_group_reply_target"] = by_group_reply_target
        if not isinstance(by_outbound_message, dict):
            by_outbound_message = {}
            payload["by_outbound_message"] = by_outbound_message

        if conversation.peer_id:
            by_account_peer[self._account_peer_key(conversation.account_id, conversation.peer_id)] = conversation.conversation_id
        if conversation.chat_id:
            latest_by_account_chat[self._account_chat_key(conversation.account_id, conversation.chat_id)] = conversation.conversation_id
        if conversation.reply_target_message_id:
            by_group_reply_target[
                self._group_reply_target_key(
                    conversation.account_id,
                    conversation.chat_id,
                    conversation.reply_target_message_id,
                )
            ] = conversation.conversation_id
        if conversation.chat_id and conversation.last_outbound_message_id:
            by_outbound_message[
                self._outbound_message_key(
                    conversation.account_id,
                    conversation.chat_id,
                    conversation.last_outbound_message_id,
                )
            ] = conversation.conversation_id

        payload["updated_at"] = utc_now().isoformat()
        write_json_file(self.indexes_path(conversation.campaign_id), payload)

    def _lookup_index(self, campaign_id: str, *, index_name: str, key: str) -> str:
        if not campaign_id or not key:
            return ""
        payload = self._load_indexes_payload(campaign_id)
        index = payload.get(index_name, {})
        if not isinstance(index, dict):
            return ""
        return str(index.get(key, "")).strip()

    def _load_conversations_payload(self, campaign_id: str) -> dict[str, object]:
        return load_json_file(
            self.conversations_path(campaign_id),
            default={"conversations": {}, "updated_at": ""},
        )

    def _write_conversations_payload(self, campaign_id: str, payload: dict[str, object]) -> None:
        write_json_file(self.conversations_path(campaign_id), payload)

    def _load_indexes_payload(self, campaign_id: str) -> dict[str, object]:
        return load_json_file(
            self.indexes_path(campaign_id),
            default={
                "by_account_peer": {},
                "by_group_reply_target": {},
                "by_outbound_message": {},
                "latest_by_account_chat": {},
                "updated_at": "",
            },
        )

    def _load_event_links_payload(self, campaign_id: str) -> dict[str, object]:
        return load_json_file(
            self.event_links_path(campaign_id),
            default={"event_to_conversation": {}, "updated_at": ""},
        )

    def _list_campaign_ids(self) -> list[str]:
        if not self._campaigns_root.exists():
            return []
        return sorted(path.name for path in self._campaigns_root.iterdir() if path.is_dir())

    def _campaign_root(self, campaign_id: str) -> Path:
        return self._campaigns_root / campaign_id

    def _account_peer_key(self, account_id: str, peer_id: str) -> str:
        return "|".join([account_id.strip(), peer_id.strip()])

    def _account_chat_key(self, account_id: str, chat_id: str) -> str:
        return "|".join([account_id.strip(), chat_id.strip()])

    def _group_reply_target_key(self, account_id: str, chat_id: str, reply_target_message_id: str) -> str:
        return "|".join([account_id.strip(), chat_id.strip(), reply_target_message_id.strip()])

    def _outbound_message_key(self, account_id: str, chat_id: str, message_id: str) -> str:
        return "|".join([account_id.strip(), chat_id.strip(), message_id.strip()])

    def _with_guard(self, operation):  # noqa: ANN001
        current_time = utc_now()
        if not self._acquire_guard(current_time):
            raise TimeoutError("Could not acquire the external conversation state guard.")
        try:
            return operation()
        finally:
            self._release_guard()

    def _acquire_guard(self, current_time: datetime) -> bool:
        self._campaigns_root.mkdir(parents=True, exist_ok=True)
        for _attempt in range(DEFAULT_GUARD_ATTEMPTS):
            try:
                file_descriptor = os.open(self._guard_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(file_descriptor)
                return True
            except FileExistsError:
                if self._guard_is_stale(current_time):
                    self._guard_path.unlink(missing_ok=True)
                    continue
                time.sleep(DEFAULT_GUARD_WAIT_SECONDS)
        return False

    def _guard_is_stale(self, current_time: datetime) -> bool:
        if not self._guard_path.exists():
            return False
        age_seconds = current_time.timestamp() - self._guard_path.stat().st_mtime
        return age_seconds >= DEFAULT_GUARD_STALE_SECONDS

    def _release_guard(self) -> None:
        self._guard_path.unlink(missing_ok=True)
