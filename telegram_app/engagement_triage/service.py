"""Cheap bounded inbound triage service."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import json
import logging
import os
from pathlib import Path
from typing import Any

try:
    import anthropic
except ImportError:  # pragma: no cover - exercised only in stripped-down environments.
    anthropic = None

from telegram_app.campaign_signals import CampaignSignalBridge, CampaignSignalSeverity
from telegram_app.engagement_brain.context_builder import EngagementBrainContextBuilder
from telegram_app.engagement_brain.models import EngagementBrainContext
from telegram_app.engagement_triage.models import (
    ConversationTriageState,
    InboundTriageResult,
    TriageInterestLevel,
    TriagePromotionDecision,
    TriageReviewPriority,
    TriageUrgencyLevel,
)
from telegram_app.external_conversations import ConversationReviewTrigger, ExternalConversationManager
from telegram_app.llm import resolve_model
from telegram_app.workflow_validation import parse_marked_json_block

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ENGAGEMENT_TRIAGE_JSON_MARKER = "ENGAGEMENT_TRIAGE_JSON"
_LOW_SIGNAL_MESSAGES = frozenset(
    {
        "k",
        "kk",
        "ok",
        "okay",
        "nice",
        "cool",
        "thanks",
        "thank you",
        "thx",
        "yes",
        "yep",
        "sure",
    }
)
_HIGH_INTEREST_KEYWORDS = (
    "price",
    "pricing",
    "cost",
    "how much",
    "interested",
    "details",
    "link",
    "demo",
    "call",
    "start",
    "join",
    "sign up",
    "buy",
    "book",
    "ready",
)
_MEDIUM_INTEREST_KEYWORDS = (
    "how does",
    "can you help",
    "does this",
    "does it work",
    "tell me more",
    "what is",
    "what's",
    "curious",
    "wondering",
)
_OBJECTION_KEYWORDS = (
    "expensive",
    "too much",
    "scam",
    "legit",
    "skeptical",
    "not sure",
    "unsure",
    "confused",
    "unclear",
    "why should",
    "don't trust",
)
_HOSTILE_KEYWORDS = (
    "stop messaging",
    "leave me alone",
    "go away",
    "annoying",
    "spam",
    "not interested",
    "don't message",
    "quit texting",
    "block you",
)
_HIGH_URGENCY_KEYWORDS = (
    "today",
    "asap",
    "right now",
    "urgent",
    "soon",
    "this week",
    "immediately",
)
_MEDIUM_URGENCY_KEYWORDS = (
    "tomorrow",
    "later today",
    "next week",
    "when can",
)


def _load_prompt(name: str) -> str:
    return (REPO_ROOT / "prompts" / name).read_text(encoding="utf-8")


class CheapInboundTriageService:
    """Run low-cost triage, persist compact state, and decide promotion."""

    def __init__(
        self,
        context_builder: EngagementBrainContextBuilder,
        conversation_manager: ExternalConversationManager,
        *,
        signal_bridge: CampaignSignalBridge | None = None,
    ) -> None:
        self._context_builder = context_builder
        self._conversation_manager = conversation_manager
        self._signal_bridge = signal_bridge
        self._client = anthropic.Anthropic() if anthropic is not None else None

    def triage_review(
        self,
        campaign_id: str,
        conversation_id: str,
        *,
        trigger: ConversationReviewTrigger,
        now: datetime | None = None,
    ) -> InboundTriageResult | None:
        """Run cheap triage for one claimed review moment and persist the result."""
        context = self._context_builder.build(campaign_id, conversation_id)
        if context is None:
            return None

        triage_state = self._llm_triage(context)
        if triage_state is None:
            triage_state = self._fallback_triage(context)

        triage_state = replace(
            triage_state,
            last_triaged_at=now or datetime.now(UTC),
            last_trigger_key=trigger.trigger_key,
            last_trigger_source=trigger.trigger_source,
        )
        saved = self._conversation_manager.update_triage_state(
            campaign_id,
            conversation_id,
            triage_state=triage_state,
            next_action_type=(
                "promoted_for_deep_review"
                if triage_state.promotion_decision is TriagePromotionDecision.PROMOTE_TO_DEEP_REVIEW
                else "await_new_inbound"
            ),
            next_action_reason=triage_state.triage_summary,
        )
        if saved is None:
            return None

        if self._signal_bridge is not None:
            self._maybe_record_signal(saved.campaign_id, saved.account_id, saved.community_id, saved.conversation_id, triage_state)

        return InboundTriageResult(
            triage_state=triage_state,
            should_promote=triage_state.promotion_decision is TriagePromotionDecision.PROMOTE_TO_DEEP_REVIEW,
            summary=triage_state.triage_summary,
            reasons=self._reasons_for(triage_state),
        )

    def _llm_triage(self, context: EngagementBrainContext) -> ConversationTriageState | None:
        if self._client is None or not os.getenv("ANTHROPIC_API_KEY", "").strip():
            return None

        payload = {
            "conversation_mode": context.mode.value,
            "campaign_brief": context.campaign_brief,
            "conversation_summary": context.conversation_summary,
            "latest_inbound_text": context.latest_inbound_text(),
            "recent_messages": [
                {
                    "direction": message.direction.value,
                    "text": message.text,
                }
                for message in context.recent_messages[-4:]
            ],
            "community_notes": list(context.community_notes[-4:]),
            "strategy_notes": list(context.strategy_notes[-4:]),
        }
        try:
            response = self._client.messages.create(
                model=resolve_model("summary"),
                max_tokens=500,
                system=[{"type": "text", "text": _load_prompt("live_engagement_triage.md")}],
                messages=[
                    {
                        "role": "user",
                        "content": json.dumps(payload, ensure_ascii=True),
                    }
                ],
            )
        except Exception as exc:  # pragma: no cover - network/runtime failures are environment-specific.
            logger.warning("Cheap inbound triage fell back after Anthropic error: %s", exc)
            return None

        output_text = "".join(block.text for block in response.content if hasattr(block, "text")).strip()
        parsed = parse_marked_json_block(output_text, ENGAGEMENT_TRIAGE_JSON_MARKER)
        if not isinstance(parsed, dict):
            return None
        return self._state_from_payload(parsed)

    def _fallback_triage(self, context: EngagementBrainContext) -> ConversationTriageState:
        latest_inbound_text = context.latest_inbound_text()
        normalized_text = self._normalize_text(latest_inbound_text)
        low_signal_chatter = self._is_low_signal_chatter(normalized_text)
        objection_present = self._contains_any(normalized_text, _OBJECTION_KEYWORDS)
        hostile_signal = self._contains_any(normalized_text, _HOSTILE_KEYWORDS)
        interest_level = self._infer_interest_level(normalized_text, low_signal_chatter=low_signal_chatter)
        urgency_level = self._infer_urgency_level(normalized_text)
        review_priority = self._infer_review_priority(
            normalized_text,
            interest_level=interest_level,
            urgency_level=urgency_level,
            objection_present=objection_present,
            hostile_signal=hostile_signal,
            low_signal_chatter=low_signal_chatter,
        )
        promotion_decision = (
            TriagePromotionDecision.PROMOTE_TO_DEEP_REVIEW
            if review_priority is not TriageReviewPriority.LOW
            else TriagePromotionDecision.COMPLETE_IN_TRIAGE
        )
        summary = self._build_summary(
            interest_level=interest_level,
            urgency_level=urgency_level,
            objection_present=objection_present,
            hostile_signal=hostile_signal,
            low_signal_chatter=low_signal_chatter,
            promotion_decision=promotion_decision,
        )
        return ConversationTriageState(
            interest_level=interest_level,
            urgency_level=urgency_level,
            objection_present=objection_present,
            objection_hints=self._extract_objection_hints(normalized_text),
            hostile_signal=hostile_signal,
            negative_signal_labels=self._extract_negative_signal_labels(
                normalized_text,
                low_signal_chatter=low_signal_chatter,
                hostile_signal=hostile_signal,
            ),
            low_signal_chatter=low_signal_chatter,
            review_priority=review_priority,
            promotion_decision=promotion_decision,
            promoted_to_deep_review=promotion_decision is TriagePromotionDecision.PROMOTE_TO_DEEP_REVIEW,
            triage_summary=summary,
        )

    def _state_from_payload(self, payload: dict[str, Any]) -> ConversationTriageState:
        state = ConversationTriageState.from_dict(payload)
        if state.objection_present and not state.objection_hints:
            state.objection_hints = ["objection_or_unclear"]
        if state.hostile_signal and "hostile_signal" not in state.negative_signal_labels:
            state.negative_signal_labels.append("hostile_signal")
        if state.low_signal_chatter and "low_signal_chatter" not in state.negative_signal_labels:
            state.negative_signal_labels.append("low_signal_chatter")
        if not state.triage_summary:
            state.triage_summary = self._build_summary(
                interest_level=state.interest_level,
                urgency_level=state.urgency_level,
                objection_present=state.objection_present,
                hostile_signal=state.hostile_signal,
                low_signal_chatter=state.low_signal_chatter,
                promotion_decision=state.promotion_decision,
            )
        return state

    def _infer_interest_level(
        self,
        normalized_text: str,
        *,
        low_signal_chatter: bool,
    ) -> TriageInterestLevel:
        if low_signal_chatter or not normalized_text:
            return TriageInterestLevel.LOW
        if self._contains_any(normalized_text, _HIGH_INTEREST_KEYWORDS):
            return TriageInterestLevel.HIGH
        if "?" in normalized_text or self._contains_any(normalized_text, _MEDIUM_INTEREST_KEYWORDS):
            return TriageInterestLevel.MEDIUM
        return TriageInterestLevel.LOW

    def _infer_urgency_level(self, normalized_text: str) -> TriageUrgencyLevel:
        if self._contains_any(normalized_text, _HIGH_URGENCY_KEYWORDS):
            return TriageUrgencyLevel.HIGH
        if self._contains_any(normalized_text, _MEDIUM_URGENCY_KEYWORDS):
            return TriageUrgencyLevel.MEDIUM
        return TriageUrgencyLevel.LOW

    def _infer_review_priority(
        self,
        normalized_text: str,
        *,
        interest_level: TriageInterestLevel,
        urgency_level: TriageUrgencyLevel,
        objection_present: bool,
        hostile_signal: bool,
        low_signal_chatter: bool,
    ) -> TriageReviewPriority:
        if low_signal_chatter:
            return TriageReviewPriority.LOW
        if hostile_signal:
            return TriageReviewPriority.HIGH
        if (
            urgency_level is TriageUrgencyLevel.HIGH
            or objection_present
            or interest_level is TriageInterestLevel.HIGH
        ):
            return TriageReviewPriority.HIGH
        if interest_level is TriageInterestLevel.MEDIUM or "?" in normalized_text:
            return TriageReviewPriority.MEDIUM
        return TriageReviewPriority.LOW

    def _build_summary(
        self,
        *,
        interest_level: TriageInterestLevel,
        urgency_level: TriageUrgencyLevel,
        objection_present: bool,
        hostile_signal: bool,
        low_signal_chatter: bool,
        promotion_decision: TriagePromotionDecision,
    ) -> str:
        if low_signal_chatter:
            return "Low-signal chatter did not warrant deeper commercial review."
        if hostile_signal:
            return "The inbound carried a hostile or do-not-contact signal and needs cautious handling."

        parts = [f"Interest looks {interest_level.value}."]
        if urgency_level is not TriageUrgencyLevel.LOW:
            parts.append(f"Urgency looks {urgency_level.value}.")
        if objection_present:
            parts.append("An objection or trust concern is present.")
        if promotion_decision is TriagePromotionDecision.PROMOTE_TO_DEEP_REVIEW:
            parts.append("Promoted into deeper commercial review.")
        else:
            parts.append("Completed in cheap triage without deeper review.")
        return " ".join(parts)

    def _reasons_for(self, triage_state: ConversationTriageState) -> list[str]:
        reasons: list[str] = []
        if triage_state.low_signal_chatter:
            reasons.append("low_signal_chatter")
        if triage_state.interest_level is TriageInterestLevel.HIGH:
            reasons.append("high_interest")
        elif triage_state.interest_level is TriageInterestLevel.MEDIUM:
            reasons.append("moderate_interest")
        if triage_state.urgency_level is TriageUrgencyLevel.HIGH:
            reasons.append("high_urgency")
        elif triage_state.urgency_level is TriageUrgencyLevel.MEDIUM:
            reasons.append("moderate_urgency")
        if triage_state.objection_present:
            reasons.append("objection_present")
        if triage_state.hostile_signal:
            reasons.append("hostile_signal")
        return reasons

    def _maybe_record_signal(
        self,
        campaign_id: str,
        account_id: str,
        community_id: str,
        conversation_id: str,
        triage_state: ConversationTriageState,
    ) -> None:
        if triage_state.promotion_decision is not TriagePromotionDecision.PROMOTE_TO_DEEP_REVIEW:
            return
        if triage_state.review_priority is TriageReviewPriority.HIGH:
            severity = CampaignSignalSeverity.HIGH
        else:
            severity = CampaignSignalSeverity.MEDIUM
        self._signal_bridge.record(
            campaign_id=campaign_id,
            source_kind="conversation_triage",
            source_ref=conversation_id,
            signal_type="conversation_promoted_for_deep_review",
            severity=severity,
            summary=triage_state.triage_summary,
            context_refs=[f"conversation:{conversation_id}"],
            account_id=account_id,
            community_id=community_id,
            conversation_id=conversation_id,
            review_eligible=True,
            dedupe_key_hint=f"triage:{conversation_id}:{triage_state.last_trigger_key}",
            trigger_source="engagement_triage",
        )

    def _normalize_text(self, value: str) -> str:
        return " ".join(value.lower().split())

    def _is_low_signal_chatter(self, normalized_text: str) -> bool:
        if normalized_text in _LOW_SIGNAL_MESSAGES:
            return True
        tokens = [token for token in normalized_text.split() if token]
        return bool(tokens) and len(tokens) <= 3 and all(token in _LOW_SIGNAL_MESSAGES for token in tokens)

    def _contains_any(self, normalized_text: str, keywords: tuple[str, ...]) -> bool:
        return any(keyword in normalized_text for keyword in keywords)

    def _extract_objection_hints(self, normalized_text: str) -> list[str]:
        hints: list[str] = []
        hint_rules = (
            (("expensive", "too much"), "pricing_concern"),
            (("scam", "legit", "trust", "skeptical", "don't trust"), "trust_concern"),
            (("not sure", "unsure", "confused", "unclear", "why should"), "clarity_concern"),
        )
        for keywords, label in hint_rules:
            if any(keyword in normalized_text for keyword in keywords):
                hints.append(label)
        return hints

    def _extract_negative_signal_labels(
        self,
        normalized_text: str,
        *,
        low_signal_chatter: bool,
        hostile_signal: bool,
    ) -> list[str]:
        labels: list[str] = []
        if low_signal_chatter:
            labels.append("low_signal_chatter")
        if hostile_signal:
            labels.append("hostile_signal")
        if "not interested" in normalized_text:
            labels.append("disinterest")
        return labels
