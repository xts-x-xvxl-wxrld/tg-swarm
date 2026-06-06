"""Campaign-scoped compiled-intent persistence."""

from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Any

from telegram_app.compiled_intents.models import CompiledIntentRecord, CompiledIntentStatus
from telegram_app.json_store import load_json_file, write_json_file


class CompiledIntentStore:
    """Persist compiled-intent records under each campaign workspace."""

    def __init__(self, campaigns_root: str | Path) -> None:
        self._campaigns_root = Path(campaigns_root).resolve()
        self._lock = RLock()

    def get(self, campaign_id: str, intent_id: str) -> CompiledIntentRecord | None:
        """Fetch one compiled intent by identifier."""
        for intent in self.list_for_campaign(campaign_id):
            if intent.intent_id == intent_id:
                return intent
        return None

    def list_for_campaign(self, campaign_id: str) -> list[CompiledIntentRecord]:
        """Return all compiled intents saved for one campaign."""
        payload = load_json_file(self._file_path(campaign_id), default={"compiled_intents": []})
        raw_intents = payload.get("compiled_intents", [])
        if not isinstance(raw_intents, list):
            return []
        return [
            intent
            for intent in (
                CompiledIntentRecord.from_dict(raw_intent)
                for raw_intent in raw_intents
                if isinstance(raw_intent, dict)
            )
            if intent.intent_id
        ]

    def list_by_status(
        self,
        campaign_id: str,
        *,
        status: CompiledIntentStatus,
    ) -> list[CompiledIntentRecord]:
        """Return compiled intents filtered by lifecycle status."""
        return [intent for intent in self.list_for_campaign(campaign_id) if intent.status is status]

    def summarize_recent_outcomes(
        self,
        campaign_id: str,
        *,
        limit: int = 6,
        work_type: str | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        """Return compact prompt-safe recent proposal outcomes for one campaign."""
        intents = [
            intent
            for intent in self.list_for_campaign(campaign_id)
            if _matches_filters(
                intent,
                work_type=work_type,
                conversation_id=conversation_id,
            )
        ]
        ordered = sorted(intents, key=lambda intent: intent.updated_at, reverse=True)
        recent = ordered[: max(limit, 0)]
        counts: dict[str, int] = {}
        items: list[dict[str, Any]] = []
        for intent in recent:
            counts[intent.status.value] = counts.get(intent.status.value, 0) + 1
            item = {
                "intent_id": intent.intent_id,
                "kind": intent.kind,
                "status": intent.status.value,
                "source_role": intent.source_role,
                "summary": intent.summary,
                "created_at": intent.created_at.isoformat(),
            }
            resolved_work_type = _work_type_for_intent(intent)
            if resolved_work_type:
                item["work_type"] = resolved_work_type
            resolved_conversation_id = _conversation_id_for_intent(intent)
            if resolved_conversation_id:
                item["conversation_id"] = resolved_conversation_id
            outcome = _outcome_for_intent(intent)
            if outcome:
                item["outcome"] = outcome
            items.append(item)
        return {
            "counts": counts,
            "items": items,
        }

    def save(self, intent: CompiledIntentRecord) -> CompiledIntentRecord:
        """Insert or replace one compiled-intent record."""
        with self._lock:
            intent.touch()
            intents = self.list_for_campaign(intent.campaign_id)
            updated = False
            payloads: list[dict[str, object]] = []
            for existing_intent in intents:
                if existing_intent.intent_id == intent.intent_id:
                    payloads.append(intent.to_dict())
                    updated = True
                else:
                    payloads.append(existing_intent.to_dict())
            if not updated:
                payloads.append(intent.to_dict())
            write_json_file(self._file_path(intent.campaign_id), {"compiled_intents": payloads})
            return intent

    def _file_path(self, campaign_id: str) -> Path:
        return self._campaigns_root / campaign_id / "compiled-intents.json"


def _matches_filters(
    intent: CompiledIntentRecord,
    *,
    work_type: str | None,
    conversation_id: str | None,
) -> bool:
    if work_type and _work_type_for_intent(intent) != work_type:
        return False
    if conversation_id and _conversation_id_for_intent(intent) != conversation_id:
        return False
    return True


def _work_type_for_intent(intent: CompiledIntentRecord) -> str:
    payload = intent.payload
    for key in ("work_type", "current_work_type", "recommended_next_work_type"):
        value = str(payload.get(key, "")).strip()
        if value:
            return value
    return ""


def _conversation_id_for_intent(intent: CompiledIntentRecord) -> str:
    return str(intent.payload.get("conversation_id", "")).strip()


def _outcome_for_intent(intent: CompiledIntentRecord) -> str:
    if intent.status is CompiledIntentStatus.REJECTED:
        return intent.rejection_reason
    if intent.status is CompiledIntentStatus.BLOCKED:
        return intent.blocked_reason
    if intent.status is CompiledIntentStatus.APPLIED:
        return intent.application_result
    return ""
