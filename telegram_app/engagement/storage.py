"""Account-scoped persistence for inbound managed-account engagement events."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from threading import RLock
from typing import Any

from telegram_app.engagement.models import EngagementEventRecord, ListenerState, OutboundMessageReference
from telegram_app.json_store import load_json_file, write_json_file

DEFAULT_RECENT_DEDUPE_LIMIT = 500
DEFAULT_OUTBOUND_REFERENCE_LIMIT = 1000


class ManagedAccountEngagementStore:
    """Persist engagement evidence and resume-safe listener state per account."""

    def __init__(
        self,
        data_root: str | Path,
        *,
        recent_dedupe_limit: int = DEFAULT_RECENT_DEDUPE_LIMIT,
        outbound_reference_limit: int = DEFAULT_OUTBOUND_REFERENCE_LIMIT,
    ) -> None:
        self._managed_accounts_root = Path(data_root) / "managed_accounts"
        self._recent_dedupe_limit = max(recent_dedupe_limit, 1)
        self._outbound_reference_limit = max(outbound_reference_limit, 1)
        self._lock = RLock()
        self._managed_accounts_root.mkdir(parents=True, exist_ok=True)

    def append_inbound_event(self, event: EngagementEventRecord) -> bool:
        """Persist one inbound event unless its dedupe key was already recorded."""
        with self._lock:
            state = self.get_listener_state(event.account_id)
            if event.dedupe_key in state.recent_dedupe_keys:
                return False

            self._append_jsonl_line(self.inbound_events_path(event.account_id), event.to_dict())
            state.remember(
                event.dedupe_key,
                event_id=event.event_id,
                recorded_at=event.recorded_at,
                max_keys=self._recent_dedupe_limit,
            )
            self._write_listener_state(state)
            return True

    def list_inbound_events(self, account_id: str) -> list[EngagementEventRecord]:
        """Return persisted inbound events for one managed account."""
        path = self.inbound_events_path(account_id)
        if not path.exists():
            return []

        events: list[EngagementEventRecord] = []
        with self._lock:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                payload = json.loads(line)
                if isinstance(payload, dict):
                    events.append(EngagementEventRecord.from_dict(payload))
        return events

    def find_inbound_event(self, account_id: str, event_id: str) -> EngagementEventRecord | None:
        """Resolve one persisted inbound event by identifier for bounded context reuse."""
        normalized_event_id = event_id.strip()
        if not account_id or not normalized_event_id:
            return None

        for event in reversed(self.list_inbound_events(account_id)):
            if event.event_id == normalized_event_id:
                return event
        return None

    def get_listener_state(self, account_id: str) -> ListenerState:
        """Load the compact dedupe and resume state for one account."""
        payload = load_json_file(
            self.listener_state_path(account_id),
            default={
                "account_id": account_id.strip(),
                "recent_dedupe_keys": [],
                "last_event_id": "",
                "last_recorded_at": "",
            },
        )
        return ListenerState.from_dict(payload, account_id=account_id.strip())

    def record_outbound_message(
        self,
        account_id: str,
        chat_id: str,
        message_id: str | int,
        *,
        sent_at: datetime,
        campaign_id: str = "",
        conversation_id: str = "",
        text: str = "",
        asset_refs: list[str] | None = None,
    ) -> OutboundMessageReference:
        """Persist one outbound message reference for later reply matching."""
        reference = OutboundMessageReference(
            account_id=account_id.strip(),
            chat_id=str(chat_id).strip(),
            message_id=str(message_id).strip(),
            sent_at=sent_at,
            campaign_id=campaign_id.strip(),
            conversation_id=conversation_id.strip(),
            text=text,
            asset_refs=[str(value).strip() for value in asset_refs or [] if str(value).strip()],
        )
        if not reference.account_id or not reference.chat_id or not reference.message_id:
            raise ValueError("Outbound message references require account_id, chat_id, and message_id.")

        with self._lock:
            references = self.list_outbound_messages(reference.account_id)
            references = [
                item
                for item in references
                if not (
                    item.chat_id == reference.chat_id
                    and item.message_id == reference.message_id
                )
            ]
            references.append(reference)
            self._write_outbound_messages(reference.account_id, references[-self._outbound_reference_limit :])
        return reference

    def list_outbound_messages(self, account_id: str) -> list[OutboundMessageReference]:
        """Return the compact outbound reply-matching index for one account."""
        payload = load_json_file(self.outbound_index_path(account_id), default={"messages": []})
        raw_messages = payload.get("messages", [])
        if not isinstance(raw_messages, list):
            return []
        return [OutboundMessageReference.from_dict(item) for item in raw_messages if isinstance(item, dict)]

    def find_outbound_message(
        self,
        account_id: str,
        chat_id: str,
        reply_to_message_id: str | int,
    ) -> OutboundMessageReference | None:
        """Resolve one outbound message reference for group-reply classification."""
        normalized_chat_id = str(chat_id).strip()
        normalized_message_id = str(reply_to_message_id).strip()
        if not normalized_chat_id or not normalized_message_id:
            return None

        with self._lock:
            for reference in reversed(self.list_outbound_messages(account_id)):
                if reference.chat_id == normalized_chat_id and reference.message_id == normalized_message_id:
                    return reference
        return None

    def listener_state_path(self, account_id: str) -> Path:
        """Return the JSON listener-state path for one account."""
        return self._account_root(account_id) / "listener-state.json"

    def inbound_events_path(self, account_id: str) -> Path:
        """Return the append-only JSONL path for one account's inbound events."""
        return self._account_root(account_id) / "inbound-events.jsonl"

    def outbound_index_path(self, account_id: str) -> Path:
        """Return the compact outbound-message index path for one account."""
        return self._account_root(account_id) / "outbound-message-index.json"

    def _write_listener_state(self, state: ListenerState) -> None:
        write_json_file(self.listener_state_path(state.account_id), state.to_dict())

    def _write_outbound_messages(self, account_id: str, references: list[OutboundMessageReference]) -> None:
        payload = {"messages": [item.to_dict() for item in references]}
        write_json_file(self.outbound_index_path(account_id), payload)

    def _append_jsonl_line(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True, sort_keys=True))
            handle.write("\n")

    def _account_root(self, account_id: str) -> Path:
        safe_account_id = "".join(
            character if character.isalnum() or character in {"-", "_", "."} else "_"
            for character in account_id.strip()
        )
        return self._managed_accounts_root / safe_account_id
