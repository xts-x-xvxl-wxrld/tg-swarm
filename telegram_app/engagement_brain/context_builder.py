"""Build bounded live-engagement brain context from persisted runtime state."""

from __future__ import annotations

from telegram_app.autonomous_send import AutonomousSendManager
from telegram_app.campaign_intent import QUALIFICATION_POSTURE_KEY
from telegram_app.campaigns import CampaignManager
from telegram_app.conversion_target import build_conversion_target_summary
from telegram_app.engagement import ManagedAccountEngagementStore
from telegram_app.engagement_brain.models import (
    EngagementBrainApprovedClaim,
    EngagementBrainCommunityGuidance,
    EngagementBrainCommunityRiskLevel,
    EngagementBrainContext,
    EngagementBrainForbiddenClaim,
    EngagementBrainMessage,
    EngagementBrainMessageDirection,
    EngagementBrainVoiceProfile,
)
from telegram_app.external_conversations import ExternalConversationManager, ExternalConversationRecord
from telegram_app.intake import (
    CONSTRAINTS_KEY,
    GEOGRAPHY_KEY,
    LANGUAGE_KEY,
    NOTES_KEY,
    OBJECTIVE_KEY,
    OFFER_KEY,
    TARGET_AUDIENCE_KEY,
)
from telegram_app.models import WorkflowArtifact, WorkflowArtifactKind
from telegram_app.live_execution.policy_state import LiveExecutionPolicyStateManager
from telegram_app.live_ops import LiveOpsControlManager

DEFAULT_RECENT_MESSAGE_LIMIT = 6
DEFAULT_FORBIDDEN_CLAIMS = (
    (
        "guaranteed_outcomes",
        "Do not promise guaranteed results, guaranteed ROI, certainty, or no-risk outcomes.",
    ),
    (
        "legal_or_compliance_assurance",
        "Do not provide legal, compliance, tax, refund, or contract assurances.",
    ),
    (
        "invented_pricing",
        "Do not invent prices, discounts, refund terms, or commercial commitments that are not approved.",
    ),
    (
        "fabricated_proof",
        "Do not claim customer results, testimonials, case studies, or availability that were not explicitly approved.",
    ),
)


class EngagementBrainContextBuilder:
    """Assemble bounded campaign and conversation inputs for the engagement brain."""

    def __init__(
        self,
        campaign_manager: CampaignManager,
        conversation_manager: ExternalConversationManager,
        engagement_store: ManagedAccountEngagementStore,
        policy_state_manager: LiveExecutionPolicyStateManager | None = None,
        autonomous_send_manager: AutonomousSendManager | None = None,
        live_ops_control_manager: LiveOpsControlManager | None = None,
        *,
        recent_message_limit: int = DEFAULT_RECENT_MESSAGE_LIMIT,
    ) -> None:
        self._campaign_manager = campaign_manager
        self._conversation_manager = conversation_manager
        self._engagement_store = engagement_store
        self._policy_state_manager = policy_state_manager
        self._autonomous_send_manager = autonomous_send_manager
        self._live_ops_control_manager = live_ops_control_manager
        self._recent_message_limit = max(recent_message_limit, 1)

    def build(self, campaign_id: str, conversation_id: str) -> EngagementBrainContext | None:
        """Build one bounded engagement-brain context from durable runtime state."""
        conversation = self._conversation_manager.get(campaign_id, conversation_id)
        if conversation is None:
            return None

        artifact_map = self._artifact_map(campaign_id)
        campaign_intent = artifact_map.get(WorkflowArtifactKind.CAMPAIGN_INTENT)
        campaign_brief = artifact_map.get(WorkflowArtifactKind.CAMPAIGN_BRIEF)
        conversion_target = artifact_map.get(WorkflowArtifactKind.CONVERSION_TARGET)
        shortlist = artifact_map.get(WorkflowArtifactKind.COMMUNITY_SHORTLIST)
        strategy = artifact_map.get(WorkflowArtifactKind.STRATEGY_PLAYBOOK)
        live_ops_profile = (
            self._live_ops_control_manager.get_profile(campaign_id)
            if self._live_ops_control_manager is not None
            else None
        )
        voice_profile = self._build_voice_profile(strategy, live_ops_profile)
        approved_claims = self._build_approved_claims(campaign_brief, strategy, live_ops_profile)
        forbidden_claims = self._build_forbidden_claims(strategy, live_ops_profile)
        community_guidance = self._build_community_guidance(
            shortlist,
            strategy,
            conversation=conversation,
            live_ops_profile=live_ops_profile,
        )
        community_risk_level = self._derive_community_risk_level(shortlist, strategy, conversation=conversation)
        conversation_posture = self._build_conversation_posture(conversation)

        return EngagementBrainContext(
            conversation=conversation,
            campaign_brief=self._build_campaign_brief_text(campaign_brief),
            conversion_target_summary=build_conversion_target_summary(conversion_target.data) if conversion_target is not None else "",
            conversion_target_kind=str(conversion_target.data.get("destination_kind", "")).strip() if conversion_target is not None else "",
            conversion_target_value=str(
                conversion_target.data.get("normalized_value") or conversion_target.data.get("raw_value") or ""
            ).strip() if conversion_target is not None else "",
            qualification_posture=str(campaign_intent.data.get(QUALIFICATION_POSTURE_KEY, "")).strip() if campaign_intent is not None else "",
            approved_offer_facts=self._build_approved_offer_facts(campaign_brief),
            strategy_notes=self._build_strategy_notes(strategy, conversation=conversation),
            community_notes=self._build_community_notes(shortlist, strategy, conversation=conversation),
            voice_profile=voice_profile,
            approved_claims=approved_claims,
            forbidden_claims=forbidden_claims,
            community_guidance=community_guidance,
            community_risk_level=community_risk_level,
            conversation_posture=conversation_posture,
            tone_contract_fingerprint=EngagementBrainContext.build_tone_contract_fingerprint(
                voice_profile,
                approved_claims,
                forbidden_claims,
                community_guidance,
            ),
            conversation_summary=self._build_conversation_summary(conversation),
            recent_messages=self._build_recent_messages(conversation),
        )

    def _artifact_map(self, campaign_id: str) -> dict[WorkflowArtifactKind, WorkflowArtifact]:
        artifact_map: dict[WorkflowArtifactKind, WorkflowArtifact] = {}
        for artifact in self._campaign_manager.load_compatibility_artifacts(campaign_id):
            existing = artifact_map.get(artifact.kind)
            if existing is None or artifact.updated_at >= existing.updated_at:
                artifact_map[artifact.kind] = artifact
        return artifact_map

    def _build_campaign_brief_text(self, campaign_brief: WorkflowArtifact | None) -> str:
        if campaign_brief is None:
            return ""
        brief_data = campaign_brief.data
        parts = [
            f"Goal: {str(brief_data.get(OBJECTIVE_KEY, '')).strip()}",
            f"Audience: {str(brief_data.get(TARGET_AUDIENCE_KEY, '')).strip()}",
            f"Offer: {str(brief_data.get(OFFER_KEY, '')).strip()}",
            f"Geography: {str(brief_data.get(GEOGRAPHY_KEY, '')).strip()}",
            f"Language: {str(brief_data.get(LANGUAGE_KEY, '')).strip()}",
        ]
        return "\n".join(part for part in parts if not part.endswith(": "))

    def _build_approved_offer_facts(self, campaign_brief: WorkflowArtifact | None) -> list[str]:
        if campaign_brief is None:
            return []
        brief_data = campaign_brief.data
        facts: list[str] = []
        for key in (OFFER_KEY, OBJECTIVE_KEY, TARGET_AUDIENCE_KEY, GEOGRAPHY_KEY, LANGUAGE_KEY):
            value = str(brief_data.get(key, "")).strip()
            if value:
                facts.append(value)
        for key in (CONSTRAINTS_KEY, NOTES_KEY):
            values = brief_data.get(key, [])
            if isinstance(values, list):
                facts.extend(str(value).strip() for value in values if str(value).strip())
        return facts[:8]

    def _build_voice_profile(
        self,
        strategy: WorkflowArtifact | None,
        live_ops_profile=None,
    ) -> EngagementBrainVoiceProfile:
        if strategy is None:
            profile = EngagementBrainVoiceProfile(
                tone_descriptors=["human", "clear", "contextual"],
                style_do=[
                    "sound like a peer",
                    "sound like a normal person typing in chat",
                    "open plainly",
                    "keep the answer concise",
                    "use minimal punctuation",
                    "frame value around the online service naturally",
                    "ground claims in approved facts",
                ],
                style_avoid=[
                    "robotic phrasing",
                    "generic hype",
                    "hard sells",
                    "polished prose",
                    "writerly phrasing",
                    "em dashes",
                    "emoji greetings",
                    "corny openers",
                    "room-addressing hooks",
                ],
                cta_style="soft_question",
                emoji_policy="community_matched",
                evidence_style="claim_only_what_is_approved",
            )
        else:
            raw_profile = strategy.data.get("voice_profile", {})
            if not isinstance(raw_profile, dict):
                raw_profile = {}
            profile = EngagementBrainVoiceProfile(
                brand_name=str(raw_profile.get("brand_name", "")).strip(),
                tone_descriptors=self._string_list(raw_profile.get("tone_descriptors")),
                style_do=self._string_list(raw_profile.get("style_do")),
                style_avoid=self._string_list(raw_profile.get("style_avoid")),
                cta_style=str(raw_profile.get("cta_style", "")).strip() or "soft_question",
                emoji_policy=str(raw_profile.get("emoji_policy", "")).strip() or "community_matched",
                evidence_style=str(raw_profile.get("evidence_style", "")).strip() or "claim_only_what_is_approved",
            )
        if live_ops_profile is None:
            return profile
        profile.tone_descriptors = self._merge_unique(profile.tone_descriptors, live_ops_profile.voice_profile.tone_descriptors)
        profile.style_do = self._merge_unique(profile.style_do, live_ops_profile.voice_profile.style_do)
        profile.style_avoid = self._merge_unique(profile.style_avoid, live_ops_profile.voice_profile.style_avoid)
        if live_ops_profile.voice_profile.cta_style:
            profile.cta_style = live_ops_profile.voice_profile.cta_style
        if live_ops_profile.voice_profile.emoji_policy:
            profile.emoji_policy = live_ops_profile.voice_profile.emoji_policy
        if live_ops_profile.voice_profile.evidence_style:
            profile.evidence_style = live_ops_profile.voice_profile.evidence_style
        return profile

    def _build_approved_claims(
        self,
        campaign_brief: WorkflowArtifact | None,
        strategy: WorkflowArtifact | None,
        live_ops_profile=None,
    ) -> list[EngagementBrainApprovedClaim]:
        claims: list[EngagementBrainApprovedClaim] = []
        if strategy is not None:
            raw_claims = strategy.data.get("approved_claims", [])
            if isinstance(raw_claims, list):
                for index, raw_claim in enumerate(raw_claims, start=1):
                    if not isinstance(raw_claim, dict):
                        continue
                    claim_id = str(raw_claim.get("claim_id", "")).strip() or f"strategy_claim_{index}"
                    text = str(raw_claim.get("text", "")).strip()
                    if not text:
                        continue
                    claims.append(
                        EngagementBrainApprovedClaim(
                            claim_id=claim_id,
                            text=text,
                            evidence_basis=str(raw_claim.get("evidence_basis", "")).strip(),
                            usage_notes=str(raw_claim.get("usage_notes", "")).strip(),
                        )
                    )

        if live_ops_profile is not None:
            for operator_claim in live_ops_profile.approved_claims:
                if not operator_claim.text.strip():
                    continue
                claims.append(
                    EngagementBrainApprovedClaim(
                        claim_id=operator_claim.claim_id or f"operator_claim_{len(claims) + 1}",
                        text=operator_claim.text,
                        evidence_basis=operator_claim.evidence_basis or "operator_live_ops",
                        usage_notes=operator_claim.usage_notes,
                    )
                )

        for index, fact in enumerate(self._build_approved_offer_facts(campaign_brief), start=1):
            claims.append(
                EngagementBrainApprovedClaim(
                    claim_id=f"brief_fact_{index}",
                    text=fact,
                    evidence_basis="campaign_brief",
                )
            )
        return self._dedupe_claims(claims)[:16]

    def _build_forbidden_claims(
        self,
        strategy: WorkflowArtifact | None,
        live_ops_profile=None,
    ) -> list[EngagementBrainForbiddenClaim]:
        claims: list[EngagementBrainForbiddenClaim] = []
        if strategy is not None:
            raw_claims = strategy.data.get("forbidden_claims", [])
            if isinstance(raw_claims, list):
                for raw_claim in raw_claims:
                    if not isinstance(raw_claim, dict):
                        continue
                    label = str(raw_claim.get("label", "")).strip()
                    instruction = str(raw_claim.get("instruction", "")).strip()
                    if not label or not instruction:
                        continue
                    claims.append(EngagementBrainForbiddenClaim(label=label, instruction=instruction))

        if live_ops_profile is not None:
            for guardrail in live_ops_profile.forbidden_claims:
                if not guardrail.label or not guardrail.instruction:
                    continue
                claims.append(
                    EngagementBrainForbiddenClaim(
                        label=guardrail.label,
                        instruction=guardrail.instruction,
                    )
                )

        existing_labels = {claim.label for claim in claims}
        for label, instruction in DEFAULT_FORBIDDEN_CLAIMS:
            if label not in existing_labels:
                claims.append(EngagementBrainForbiddenClaim(label=label, instruction=instruction))
        return self._dedupe_forbidden_claims(claims)

    def _build_strategy_notes(
        self,
        strategy: WorkflowArtifact | None,
        *,
        conversation: ExternalConversationRecord,
    ) -> list[str]:
        if strategy is None:
            return []
        notes: list[str] = []
        summary = str(strategy.data.get("campaign_strategy_summary", "")).strip() or strategy.summary.strip()
        if summary:
            notes.append(summary)

        community = self._matching_community(strategy, conversation=conversation)
        if community is None:
            return notes

        for field_name in ("messaging_angle", "message_format", "frequency", "timing", "risk_notes"):
            value = str(community.get(field_name, "")).strip()
            if value:
                notes.append(value)
        return notes[:8]

    def _build_community_notes(
        self,
        shortlist: WorkflowArtifact | None,
        strategy: WorkflowArtifact | None,
        *,
        conversation: ExternalConversationRecord,
    ) -> list[str]:
        notes: list[str] = []
        for artifact in (shortlist, strategy):
            if artifact is None:
                continue
            community = self._matching_community(artifact, conversation=conversation)
            if community is None:
                continue
            for field_name in ("evidence_summary", "reason", "verification_state", "risk_notes"):
                value = str(community.get(field_name, "")).strip()
                if value:
                    notes.append(value)
        return notes[:8]

    def _build_community_guidance(
        self,
        shortlist: WorkflowArtifact | None,
        strategy: WorkflowArtifact | None,
        *,
        conversation: ExternalConversationRecord,
        live_ops_profile=None,
    ) -> EngagementBrainCommunityGuidance | None:
        strategy_community = self._matching_community(strategy, conversation=conversation) if strategy is not None else None
        shortlist_community = self._matching_community(shortlist, conversation=conversation) if shortlist is not None else None
        source = strategy_community or shortlist_community
        if source is None and live_ops_profile is None:
            return None

        source = source or {}
        community_risk_level = self._parse_community_risk_level(
            str(source.get("community_risk_level", "")).strip()
        )
        if community_risk_level is None:
            community_risk_level = self._derive_community_risk_level(shortlist, strategy, conversation=conversation)

        tone_guidance = str(source.get("tone_guidance", "")).strip()
        escalation_rule = str(source.get("escalation_rule", "")).strip()
        if live_ops_profile is not None and live_ops_profile.community_tone_guidance and not tone_guidance:
            tone_guidance = live_ops_profile.community_tone_guidance[-1]
        if live_ops_profile is not None and live_ops_profile.escalation_rules and not escalation_rule:
            escalation_rule = live_ops_profile.escalation_rules[-1]

        return EngagementBrainCommunityGuidance(
            community_id=str(source.get("community_id", "")).strip(),
            chat_id=str(source.get("chat_id", "")).strip(),
            community_name=str(source.get("name", "")).strip() or str(source.get("handle", "")).strip(),
            community_type=self._community_policy_value(source, "community_type"),
            tone_guidance=tone_guidance,
            response_posture=str(source.get("response_posture", "")).strip(),
            allowed_cta=str(source.get("allowed_cta", "")).strip(),
            direct_response_rule=str(source.get("direct_response_rule", "")).strip(),
            clarifying_question_rule=str(source.get("clarifying_question_rule", "")).strip(),
            escalation_rule=escalation_rule,
            risk_notes=str(source.get("risk_notes", "")).strip(),
            reply_latency_tier=self._community_policy_value(source, "reply_latency_tier"),
            negative_signal_tolerance=self._community_policy_value(source, "negative_signal_tolerance"),
            risky_topics=self._string_list(source.get("risky_topics")),
            approved_claim_ids=self._string_list(source.get("approved_claim_ids")),
            forbidden_claim_labels=self._string_list(source.get("forbidden_claim_labels")),
            community_risk_level=community_risk_level,
        )

    def _derive_community_risk_level(
        self,
        shortlist: WorkflowArtifact | None,
        strategy: WorkflowArtifact | None,
        *,
        conversation: ExternalConversationRecord,
    ) -> EngagementBrainCommunityRiskLevel:
        if self._policy_state_manager is not None and conversation.chat_id.strip():
            state = self._policy_state_manager.get_community_state(conversation.campaign_id, conversation.chat_id)
            if state is not None and state.is_paused:
                return EngagementBrainCommunityRiskLevel.RESTRICTED

        for artifact in (strategy, shortlist):
            if artifact is None:
                continue
            community = self._matching_community(artifact, conversation=conversation)
            if community is None:
                continue
            explicit = self._parse_community_risk_level(str(community.get("community_risk_level", "")).strip())
            if explicit is not None:
                return explicit

            moderation_risk = str(community.get("moderation_risk", "")).strip().lower()
            promo_tolerance = str(community.get("promo_tolerance", "")).strip().lower()
            restricted = bool(community.get("restricted", False))
            if restricted:
                return EngagementBrainCommunityRiskLevel.RESTRICTED
            if moderation_risk == "high":
                return EngagementBrainCommunityRiskLevel.HIGH
            if moderation_risk == "medium" or promo_tolerance in {"low", "careful"}:
                return EngagementBrainCommunityRiskLevel.GUARDED

        return EngagementBrainCommunityRiskLevel.LOW

    def _build_conversation_posture(self, conversation: ExternalConversationRecord) -> str:
        parts = [
            "public_group_thread" if conversation.thread_origin.value == "group_reply" else "direct_dm_thread",
            f"consent:{conversation.consent_posture.value}",
        ]
        if conversation.triage_state.last_triaged_at is not None:
            parts.append(f"triage_priority:{conversation.triage_state.review_priority.value}")
        if conversation.triage_state.promoted_to_deep_review:
            parts.append("triage:promoted_for_deep_review")
        if conversation.belief_state.intent_posture:
            parts.append(f"intent:{conversation.belief_state.intent_posture}")
        if conversation.belief_state.commercial_stage:
            parts.append(f"stage:{conversation.belief_state.commercial_stage}")
        if conversation.external_user_messaged_first:
            parts.append("inbound_first_proven")
        if conversation.handoff_status.strip():
            parts.append(f"handoff:{conversation.handoff_status.strip()}")
        if conversation.qualification_status.strip():
            parts.append(f"qualification:{conversation.qualification_status.strip()}")
        if self._autonomous_send_manager is not None and conversation.campaign_id:
            posture = self._autonomous_send_manager.get_posture(conversation.campaign_id)
            if conversation.thread_origin.value == "group_reply":
                parts.append(f"autonomous_send:{posture.group_reply_mode.value}")
            else:
                parts.append(f"autonomous_send:{posture.dm_reply_mode.value}")
        return ", ".join(parts)

    def _build_conversation_summary(self, conversation: ExternalConversationRecord) -> str:
        parts: list[str] = []
        summary = conversation.summary.strip()
        if summary:
            parts.append(summary)

        belief_state = conversation.belief_state
        if belief_state.last_meaningful_shift and belief_state.last_meaningful_shift not in parts:
            parts.append(belief_state.last_meaningful_shift)
        if belief_state.known_fit_signals:
            parts.append(f"Fit signals: {', '.join(belief_state.known_fit_signals[:2])}.")
        if belief_state.known_objections:
            parts.append(f"Objections: {', '.join(belief_state.known_objections[:2])}.")
        if belief_state.unanswered_questions:
            parts.append(f"Open questions: {', '.join(belief_state.unanswered_questions[:2])}.")

        triage_summary = conversation.triage_state.triage_summary.strip()
        if not parts and triage_summary:
            parts.append(triage_summary)

        return " ".join(part for part in parts if part).strip()

    def _matching_community(
        self,
        artifact: WorkflowArtifact,
        *,
        conversation: ExternalConversationRecord,
    ) -> dict[str, object] | None:
        communities = artifact.data.get("communities", [])
        if not isinstance(communities, list):
            return None

        conversation_keys = {
            conversation.community_id.strip(),
            conversation.chat_id.strip(),
        }
        conversation_keys = {value for value in conversation_keys if value}

        for community in communities:
            if not isinstance(community, dict):
                continue
            community_keys = {
                str(community.get("community_id", "")).strip(),
                str(community.get("chat_id", "")).strip(),
            }
            if conversation_keys.intersection({value for value in community_keys if value}):
                return community
        return None

    def _parse_community_risk_level(self, value: str) -> EngagementBrainCommunityRiskLevel | None:
        normalized = value.strip().lower()
        if not normalized:
            return None
        return EngagementBrainCommunityRiskLevel._value2member_map_.get(normalized)

    def _community_policy_value(self, source: dict[str, object], field_name: str) -> str:
        direct_value = str(source.get(field_name, "")).strip()
        if direct_value:
            return direct_value
        raw_policy = source.get("engagement_policy", {})
        if not isinstance(raw_policy, dict):
            return ""
        return str(raw_policy.get(field_name, "")).strip()

    def _string_list(self, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    def _merge_unique(self, existing: list[str], new_values: list[str]) -> list[str]:
        merged = [value for value in existing if value.strip()]
        for value in new_values:
            normalized = str(value).strip()
            if normalized and normalized not in merged:
                merged.append(normalized)
        return merged

    def _dedupe_claims(
        self,
        claims: list[EngagementBrainApprovedClaim],
    ) -> list[EngagementBrainApprovedClaim]:
        seen_ids: set[str] = set()
        seen_text: set[str] = set()
        deduped: list[EngagementBrainApprovedClaim] = []
        for claim in claims:
            if claim.claim_id in seen_ids or claim.text in seen_text:
                continue
            seen_ids.add(claim.claim_id)
            seen_text.add(claim.text)
            deduped.append(claim)
        return deduped

    def _dedupe_forbidden_claims(
        self,
        claims: list[EngagementBrainForbiddenClaim],
    ) -> list[EngagementBrainForbiddenClaim]:
        seen_labels: set[str] = set()
        deduped: list[EngagementBrainForbiddenClaim] = []
        for claim in claims:
            if claim.label in seen_labels:
                continue
            seen_labels.add(claim.label)
            deduped.append(claim)
        return deduped

    def _build_recent_messages(self, conversation: ExternalConversationRecord) -> list[EngagementBrainMessage]:
        recent_messages: list[EngagementBrainMessage] = []
        for reference in conversation.recent_message_refs[-self._recent_message_limit :]:
            if reference.startswith("event:"):
                event = self._engagement_store.find_inbound_event(conversation.account_id, reference.removeprefix("event:"))
                if event is None:
                    continue
                recent_messages.append(
                    EngagementBrainMessage(
                        direction=EngagementBrainMessageDirection.INBOUND,
                        text=event.text,
                        message_id=event.message_id,
                        sent_at=event.occurred_at,
                    )
                )
                continue
            if reference.startswith("outbound:"):
                message_id = reference.removeprefix("outbound:").strip()
                if not message_id:
                    continue
                outbound = self._engagement_store.find_outbound_message(
                    conversation.account_id,
                    conversation.chat_id,
                    message_id,
                )
                recent_messages.append(
                    EngagementBrainMessage(
                        direction=EngagementBrainMessageDirection.OUTBOUND,
                        text=outbound.text if outbound is not None else "",
                        message_id=outbound.message_id if outbound is not None else message_id,
                        sent_at=(
                            outbound.sent_at
                            if outbound is not None
                            else (conversation.last_outbound_at if conversation.last_outbound_message_id == message_id else None)
                        ),
                        asset_refs=list(outbound.asset_refs) if outbound is not None else [],
                    )
                )
        return recent_messages
