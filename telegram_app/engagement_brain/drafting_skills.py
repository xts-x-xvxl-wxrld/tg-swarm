"""Bounded drafting-skill selection and retrieval for copy-writing surfaces."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Protocol

try:
    import anthropic
except ImportError:  # pragma: no cover - exercised only in stripped-down environments.
    anthropic = None

from telegram_app.engagement_brain.models import (
    EngagementBrainCommunityRiskLevel,
    EngagementBrainContext,
    EngagementBrainConversationRiskLevel,
    EngagementBrainDecision,
    EngagementBrainMode,
    EngagementBrainQualificationState,
    EngagementBrainRiskLevel,
)
from telegram_app.llm import resolve_model
from telegram_app.workflow_validation import parse_marked_json_block

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROMPTS_ROOT = REPO_ROOT / "prompts"
SALES_SKILLS_ROOT = PROMPTS_ROOT / "sales_skills"
DRAFTING_SKILL_SELECTION_JSON_MARKER = "DRAFTING_SKILL_SELECTION_JSON"
_MAX_PRIMARY_PACKET_CHARS = 1800
_MAX_SECONDARY_PACKET_CHARS = 800


@dataclass(frozen=True, slots=True)
class DraftingSkillCard:
    """Static metadata for one drafting skill."""

    skill_name: str
    relative_path: str
    summary: str
    primary_use_cases: tuple[str, ...]
    avoid_cases: tuple[str, ...]
    preferred_sections: tuple[str, ...]

    @property
    def path(self) -> Path:
        """Resolve the skill file path."""
        return SALES_SKILLS_ROOT / self.relative_path / "SKILL.md"

    def catalog_entry(self) -> dict[str, object]:
        """Return compact metadata safe for selector prompts."""
        return {
            "skill_name": self.skill_name,
            "summary": self.summary,
            "primary_use_cases": list(self.primary_use_cases),
            "avoid_cases": list(self.avoid_cases),
        }


@dataclass(slots=True)
class DraftingSkillPacket:
    """Compact retrieved guidance packet injected into the writer."""

    skill_name: str
    summary: str
    instruction_excerpt: str

    def normalized_dict(self) -> dict[str, str]:
        """Return a JSON-safe representation."""
        return {
            "skill_name": self.skill_name.strip(),
            "summary": self.summary.strip(),
            "instruction_excerpt": self.instruction_excerpt.strip(),
        }


@dataclass(slots=True)
class DraftingSkillSelection:
    """Primary and optional secondary drafting skill chosen for one draft."""

    primary_skill: DraftingSkillPacket | None = None
    secondary_skill: DraftingSkillPacket | None = None
    selection_reason: str = ""
    confidence: float = 0.0

    def normalized_dict(self) -> dict[str, object]:
        """Return a JSON-safe representation for the drafting payload."""
        return {
            "primary_skill": self.primary_skill.normalized_dict() if self.primary_skill is not None else {},
            "secondary_skill": self.secondary_skill.normalized_dict() if self.secondary_skill is not None else {},
            "selection_reason": self.selection_reason.strip(),
            "confidence": round(max(self.confidence, 0.0), 2),
        }


class DraftingSkillSelector(Protocol):
    """Protocol for selecting bounded drafting-skill packets."""

    def select(
        self,
        context: EngagementBrainContext,
        *,
        decision: EngagementBrainDecision,
        qualification_state: EngagementBrainQualificationState,
        goal: str,
        missing_facts: list[str],
        risk_level: EngagementBrainRiskLevel,
        conversation_risk_level: EngagementBrainConversationRiskLevel,
    ) -> DraftingSkillSelection | None:
        """Choose the most relevant drafting skill packet for this draft."""


class DraftingSkillLibrary:
    """Load compact drafting guidance packets from repo-native skill files."""

    _CARDS = {
        "sales-telegram-outbound-draft": DraftingSkillCard(
            skill_name="sales-telegram-outbound-draft",
            relative_path="sales-telegram-outbound-draft",
            summary="First-touch or proactive Telegram DM drafting with low-pressure CTAs.",
            primary_use_cases=("first_touch_dm", "proactive_dm", "lightweight_fit_check"),
            avoid_cases=("public_group_replies", "objection_replies", "generic_strategy"),
            preferred_sections=("Objective", "Telegram Writing Rules", "Message Shape", "Openers", "Hard Bans"),
        ),
        "sales-telegram-followup-draft": DraftingSkillCard(
            skill_name="sales-telegram-followup-draft",
            relative_path="sales-telegram-followup-draft",
            summary="Telegram follow-ups that add a new angle instead of repeating the same ask.",
            primary_use_cases=("follow_up", "stalled_thread", "second_touch"),
            avoid_cases=("first_touch", "hard_objection_replies", "public_first_post"),
            preferred_sections=("Objective", "Telegram Follow-Up Rules", "Follow-Up Types", "Hard Bans", "Output Logic"),
        ),
        "sales-telegram-objection-reply": DraftingSkillCard(
            skill_name="sales-telegram-objection-reply",
            relative_path="sales-telegram-objection-reply",
            summary="Telegram replies to objections or pushback without becoming defensive or pushy.",
            primary_use_cases=("objection_reply", "pushback", "pricing_or_trust_concern"),
            avoid_cases=("cold_first_touch", "public_group_post", "hard_close"),
            preferred_sections=("Objective", "Core Principles", "Supported Objection Types", "Reply Patterns", "Hard Bans", "Decision Rule"),
        ),
        "sales-telegram-group-outbound": DraftingSkillCard(
            skill_name="sales-telegram-group-outbound",
            relative_path="sales-telegram-group-outbound",
            summary="Public first-post Telegram group outbound with value-first framing and controlled CTA strength.",
            primary_use_cases=("group_first_post", "public_outbound", "community_safe_post"),
            avoid_cases=("dm_replies", "objection_replies", "thread_reply_only"),
            preferred_sections=("Objective", "Telegram Group Writing Rules", "Post Modes", "CTA Rules", "Hard Bans", "Risk Adjustment", "Output Logic"),
        ),
    }

    def catalog(self) -> list[dict[str, object]]:
        """Return the compact selector catalog."""
        return [card.catalog_entry() for card in self._CARDS.values()]

    def load_packet(self, skill_name: str, *, secondary: bool = False) -> DraftingSkillPacket | None:
        """Load a compact packet for one selected skill."""
        card = self._CARDS.get(skill_name.strip())
        if card is None or not card.path.exists():
            return None

        content = card.path.read_text(encoding="utf-8")
        section_map = _parse_skill_sections(content)
        excerpt_parts = [f"Skill: {card.skill_name}", f"Summary: {card.summary}"]
        for section_name in card.preferred_sections:
            section_text = section_map.get(section_name, "").strip()
            if section_text:
                excerpt_parts.append(f"{section_name}:\n{section_text}")
        excerpt = "\n\n".join(part for part in excerpt_parts if part.strip())
        max_chars = _MAX_SECONDARY_PACKET_CHARS if secondary else _MAX_PRIMARY_PACKET_CHARS
        return DraftingSkillPacket(
            skill_name=card.skill_name,
            summary=card.summary,
            instruction_excerpt=_trim_excerpt(excerpt, max_chars=max_chars),
        )


class AnthropicDraftingSkillSelector:
    """Use a small LLM call to choose the best drafting skill from a tiny registry."""

    def __init__(self, library: DraftingSkillLibrary | None = None) -> None:
        self._client = anthropic.Anthropic() if anthropic is not None else None
        self._library = library or DraftingSkillLibrary()

    def select(
        self,
        context: EngagementBrainContext,
        *,
        decision: EngagementBrainDecision,
        qualification_state: EngagementBrainQualificationState,
        goal: str,
        missing_facts: list[str],
        risk_level: EngagementBrainRiskLevel,
        conversation_risk_level: EngagementBrainConversationRiskLevel,
    ) -> DraftingSkillSelection | None:
        if self._client is None or not os.getenv("ANTHROPIC_API_KEY", "").strip():
            return None

        payload = {
            "conversation_mode": context.mode.value,
            "decision": decision.value,
            "goal": goal,
            "qualification_state": qualification_state.value,
            "community_risk_level": context.community_risk_level.value,
            "conversation_risk_level": conversation_risk_level.value,
            "risk_level": risk_level.value,
            "missing_facts": list(missing_facts),
            "latest_inbound_text": context.latest_inbound_text(),
            "recent_messages": [
                {
                    "direction": message.direction.value,
                    "text": message.text,
                }
                for message in context.recent_messages[-4:]
            ],
            "conversation_posture": context.conversation_posture,
            "community_guidance": (
                context.community_guidance.normalized_dict()
                if context.community_guidance is not None
                else {}
            ),
            "skill_catalog": self._library.catalog(),
            "allowed_values": {
                "primary_skill": ["none", *self._library._CARDS.keys()],
                "secondary_skill": ["none", *self._library._CARDS.keys()],
            },
        }
        try:
            response = self._client.messages.create(
                model=resolve_model("summary"),
                max_tokens=500,
                system=[
                    {"type": "text", "text": _load_prompt("live_engagement_skill_selector.md")},
                ],
                messages=[
                    {
                        "role": "user",
                        "content": json.dumps(payload, ensure_ascii=True),
                    }
                ],
            )
        except Exception:  # pragma: no cover - network/runtime failures are environment-specific.
            return None

        output_text = "".join(block.text for block in response.content if hasattr(block, "text")).strip()
        parsed = parse_marked_json_block(output_text, DRAFTING_SKILL_SELECTION_JSON_MARKER)
        if not isinstance(parsed, dict):
            return None
        return _selection_from_payload(parsed, self._library)


class DeterministicDraftingSkillSelector:
    """Conservative fallback selector used when no LLM-based selector is available."""

    def __init__(self, library: DraftingSkillLibrary | None = None) -> None:
        self._library = library or DraftingSkillLibrary()

    def select(
        self,
        context: EngagementBrainContext,
        *,
        decision: EngagementBrainDecision,
        qualification_state: EngagementBrainQualificationState,
        goal: str,
        missing_facts: list[str],
        risk_level: EngagementBrainRiskLevel,
        conversation_risk_level: EngagementBrainConversationRiskLevel,
    ) -> DraftingSkillSelection | None:
        goal_text = goal.lower().strip()
        inbound_text = context.latest_inbound_text().lower().strip()
        has_outbound_history = any(message.direction.value == "outbound" for message in context.recent_messages)

        if qualification_state is EngagementBrainQualificationState.OBJECTION_OR_UNCLEAR:
            return _build_selection(
                self._library,
                primary_skill_name="sales-telegram-objection-reply",
                reason="The thread contains objection or uncertainty signals, so objection-reply guidance is the best fit.",
                confidence=0.88,
            )

        if "follow_up" in goal_text or "follow-up" in goal_text or (has_outbound_history and not inbound_text):
            return _build_selection(
                self._library,
                primary_skill_name="sales-telegram-followup-draft",
                reason="The thread looks like a follow-up situation, so the follow-up drafting guidance is the best fit.",
                confidence=0.82,
            )

        if (
            context.mode is EngagementBrainMode.GROUP
            and decision is EngagementBrainDecision.REPLY
            and not inbound_text
            and context.community_risk_level in {EngagementBrainCommunityRiskLevel.LOW, EngagementBrainCommunityRiskLevel.GUARDED}
        ):
            return _build_selection(
                self._library,
                primary_skill_name="sales-telegram-group-outbound",
                reason="This looks closer to a first public group post than a thread reply, so the group-outbound guidance is the best fit.",
                confidence=0.75,
            )

        if (
            context.mode is EngagementBrainMode.DIRECT_DM
            and decision is EngagementBrainDecision.REPLY
            and not has_outbound_history
            and not inbound_text
        ):
            return _build_selection(
                self._library,
                primary_skill_name="sales-telegram-outbound-draft",
                reason="The draft looks like a proactive first-touch DM, so outbound drafting guidance is the best fit.",
                confidence=0.72,
            )

        return None


def _load_prompt(name: str) -> str:
    return (PROMPTS_ROOT / name).read_text(encoding="utf-8")


def _parse_skill_sections(content: str) -> dict[str, str]:
    section_map: dict[str, list[str]] = {}
    current_section = ""
    current_lines: list[str] = []

    for raw_line in content.splitlines():
        line = raw_line.rstrip()
        if line.startswith("## "):
            if current_section:
                section_map[current_section] = current_lines
            current_section = line[3:].strip()
            current_lines = []
            continue
        if current_section:
            current_lines.append(line)

    if current_section:
        section_map[current_section] = current_lines

    return {
        section: "\n".join(lines).strip()
        for section, lines in section_map.items()
        if "\n".join(lines).strip()
    }


def _trim_excerpt(text: str, *, max_chars: int) -> str:
    normalized = text.strip()
    if len(normalized) <= max_chars:
        return normalized
    clipped = normalized[:max_chars].rsplit("\n", 1)[0].strip()
    return f"{clipped}\n\n[truncated]"


def _selection_from_payload(
    payload: dict[str, object],
    library: DraftingSkillLibrary,
) -> DraftingSkillSelection | None:
    primary_skill_name = _normalize_selected_skill_name(payload.get("primary_skill"), library)
    secondary_skill_name = _normalize_selected_skill_name(payload.get("secondary_skill"), library)
    if primary_skill_name == secondary_skill_name:
        secondary_skill_name = ""

    if not primary_skill_name:
        return None

    return _build_selection(
        library,
        primary_skill_name=primary_skill_name,
        secondary_skill_name=secondary_skill_name or None,
        reason=str(payload.get("reason", "")).strip(),
        confidence=_normalize_confidence(payload.get("confidence")),
    )


def _build_selection(
    library: DraftingSkillLibrary,
    *,
    primary_skill_name: str,
    reason: str,
    confidence: float,
    secondary_skill_name: str | None = None,
) -> DraftingSkillSelection | None:
    primary_packet = library.load_packet(primary_skill_name)
    if primary_packet is None:
        return None
    secondary_packet = library.load_packet(secondary_skill_name, secondary=True) if secondary_skill_name else None
    return DraftingSkillSelection(
        primary_skill=primary_packet,
        secondary_skill=secondary_packet,
        selection_reason=reason.strip(),
        confidence=confidence,
    )


def _normalize_selected_skill_name(value: object, library: DraftingSkillLibrary) -> str:
    normalized = str(value or "").strip()
    if not normalized or normalized == "none":
        return ""
    if normalized in library._CARDS:
        return normalized
    return ""


def _normalize_confidence(value: object) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(max(parsed, 0.0), 1.0)
