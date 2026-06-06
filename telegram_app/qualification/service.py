"""Campaign-aware qualification and handoff state orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

from telegram_app.campaign_intent import QUALIFICATION_POSTURE_KEY
from telegram_app.campaigns import CampaignManager
from telegram_app.campaign_signals import CampaignSignalBridge, CampaignSignalSeverity
from telegram_app.campaign_memory.operational_notes import (
    EXECUTION_LOG_DESTINATION,
    NEXT_ACTIONS_DESTINATION,
)
from telegram_app.conversion_target import build_conversion_target_summary
from telegram_app.external_conversations import ConversationBeliefState, ExternalConversationManager
from telegram_app.intake import OBJECTIVE_KEY, OFFER_KEY, TARGET_AUDIENCE_KEY
from telegram_app.models import WorkflowArtifactKind
from telegram_app.qualification.manager import QualificationManager
from telegram_app.qualification.models import CampaignQualificationFrame, HandoffStatus


@dataclass(slots=True)
class QualificationReviewResult:
    """The persisted qualification view of one engagement-brain proposal."""

    frame: CampaignQualificationFrame
    qualification_status: str
    qualification_summary: str
    handoff_status: HandoffStatus = HandoffStatus.NONE
    handoff_summary: str = ""
    approval_context: dict[str, object] = field(default_factory=dict)
    belief_state: ConversationBeliefState | None = None


class QualificationService:
    """Build campaign qualification frames and persist live conversation outcomes."""

    def __init__(
        self,
        campaign_manager: CampaignManager,
        manager: QualificationManager,
        conversation_manager: ExternalConversationManager,
        signal_bridge: CampaignSignalBridge | None = None,
    ) -> None:
        self._campaign_manager = campaign_manager
        self._manager = manager
        self._conversation_manager = conversation_manager
        self._signal_bridge = signal_bridge

    def record_proposal(  # noqa: ANN001
        self,
        context,
        proposal,
        *,
        belief_state: ConversationBeliefState | None = None,
    ) -> QualificationReviewResult:
        """Persist the latest qualification state for one reviewed conversation."""
        frame = self.ensure_frame(context.conversation.campaign_id)
        previous_conversation = self._conversation_manager.get(
            context.conversation.campaign_id,
            context.conversation.conversation_id,
        )
        handoff_status = self._resolve_handoff_status(frame, proposal)
        qualification_summary = self._build_qualification_summary(frame, proposal)
        handoff_summary = self._build_handoff_summary(frame, handoff_status)
        resolved_belief_state = belief_state or self._build_belief_state(
            frame,
            context,
            proposal,
            handoff_status=handoff_status,
            qualification_summary=qualification_summary,
            handoff_summary=handoff_summary,
        )
        resolved_belief_state = self._apply_handoff_overlay(
            resolved_belief_state,
            frame=frame,
            proposal=proposal,
            handoff_status=handoff_status,
            handoff_summary=handoff_summary,
        )
        self._conversation_manager.update_belief_state(
            context.conversation.campaign_id,
            context.conversation.conversation_id,
            belief_state=resolved_belief_state,
            summary=resolved_belief_state.last_meaningful_shift or qualification_summary,
        )
        self._conversation_manager.update_qualification(
            context.conversation.campaign_id,
            context.conversation.conversation_id,
            qualification_status=proposal.qualification_state.value,
            qualification_summary=qualification_summary,
            handoff_status=handoff_status.value,
            handoff_summary=handoff_summary,
        )
        self._record_commercial_signals(
            context,
            proposal,
            frame=frame,
            handoff_status=handoff_status,
            qualification_summary=qualification_summary,
            handoff_summary=handoff_summary,
            belief_state=resolved_belief_state,
            previous_conversation=previous_conversation,
        )
        if handoff_status is HandoffStatus.CLARIFICATION_REQUIRED:
            self._append_next_action_note(
                context.conversation.campaign_id,
                line=(
                    "A live conversation looks conversion-ready, but the campaign conversion target still "
                    "needs clarification before the runtime can route the lead."
                ),
                dedupe_key=f"handoff-clarification:{context.conversation.conversation_id}",
            )
        return QualificationReviewResult(
            frame=frame,
            qualification_status=proposal.qualification_state.value,
            qualification_summary=qualification_summary,
            handoff_status=handoff_status,
            handoff_summary=handoff_summary,
            approval_context=self._build_approval_context(
                proposal,
                frame=frame,
                qualification_summary=qualification_summary,
                handoff_status=handoff_status,
                handoff_summary=handoff_summary,
            ),
            belief_state=resolved_belief_state,
        )

    def mark_handoff_delivered(
        self,
        campaign_id: str,
        conversation_id: str,
        *,
        action_id: str,
        summary: str,
    ) -> None:
        """Persist a successful conversion handoff delivery."""
        updated = self._conversation_manager.update_handoff(
            campaign_id,
            conversation_id,
            handoff_status=HandoffStatus.DELIVERED.value,
            handoff_summary=summary,
            action_id=action_id,
            completed=True,
        )
        if updated is None:
            return
        self._refresh_belief_state_for_handoff(
            campaign_id,
            conversation_id,
            handoff_status=HandoffStatus.DELIVERED,
            summary=summary,
        )
        self._append_execution_log_note(
            campaign_id,
            line=summary,
            dedupe_key=f"handoff-delivered:{action_id}",
        )
        self._record_handoff_signal(
            campaign_id,
            conversation_id,
            signal_type="handoff_delivered",
            severity=CampaignSignalSeverity.HIGH,
            summary=summary,
            review_eligible=False,
            dedupe_key=f"handoff-delivered:{action_id}",
        )

    def mark_handoff_blocked(
        self,
        campaign_id: str,
        conversation_id: str,
        *,
        action_id: str,
        summary: str,
    ) -> None:
        """Persist a blocked conversion handoff and surface operator follow-up."""
        updated = self._conversation_manager.update_handoff(
            campaign_id,
            conversation_id,
            handoff_status=HandoffStatus.BLOCKED.value,
            handoff_summary=summary,
            action_id=action_id,
            completed=False,
        )
        if updated is None:
            return
        self._refresh_belief_state_for_handoff(
            campaign_id,
            conversation_id,
            handoff_status=HandoffStatus.BLOCKED,
            summary=summary,
        )
        self._append_next_action_note(
            campaign_id,
            line=summary,
            dedupe_key=f"handoff-blocked:{action_id}",
        )

    def mark_handoff_failed(
        self,
        campaign_id: str,
        conversation_id: str,
        *,
        action_id: str,
        summary: str,
    ) -> None:
        """Persist a failed conversion handoff attempt."""
        updated = self._conversation_manager.update_handoff(
            campaign_id,
            conversation_id,
            handoff_status=HandoffStatus.FAILED.value,
            handoff_summary=summary,
            action_id=action_id,
            completed=False,
        )
        if updated is None:
            return
        self._refresh_belief_state_for_handoff(
            campaign_id,
            conversation_id,
            handoff_status=HandoffStatus.FAILED,
            summary=summary,
        )
        self._append_next_action_note(
            campaign_id,
            line=summary,
            dedupe_key=f"handoff-failed:{action_id}",
        )

    def ensure_frame(self, campaign_id: str) -> CampaignQualificationFrame:
        """Build and persist the current campaign qualification frame."""
        artifacts = {
            artifact.kind: artifact
            for artifact in self._campaign_manager.load_compatibility_artifacts(campaign_id)
        }
        brief = artifacts.get(WorkflowArtifactKind.CAMPAIGN_BRIEF)
        intent = artifacts.get(WorkflowArtifactKind.CAMPAIGN_INTENT)
        conversion_target = artifacts.get(WorkflowArtifactKind.CONVERSION_TARGET)

        offer_summary = ""
        target_audience_summary = ""
        qualification_posture = ""
        if brief is not None:
            offer_summary = str(brief.data.get(OFFER_KEY, "")).strip()
            target_audience_summary = str(brief.data.get(TARGET_AUDIENCE_KEY, "")).strip()
        if intent is not None:
            qualification_posture = str(intent.data.get(QUALIFICATION_POSTURE_KEY, "")).strip()
            if not offer_summary:
                offer_summary = str(intent.data.get("offer_summary", "")).strip()
            if not target_audience_summary:
                target_audience_summary = str(intent.data.get("target_audience_summary", "")).strip()

        conversion_payload = conversion_target.data if conversion_target is not None else {}
        conversion_target_summary = build_conversion_target_summary(conversion_payload)
        conversion_target_kind = str(conversion_payload.get("destination_kind", "")).strip()
        conversion_target_value = str(
            conversion_payload.get("normalized_value") or conversion_payload.get("raw_value") or ""
        ).strip()
        handoff_action_types = conversion_payload.get("allowed_action_types", [])
        objective = str(brief.data.get(OBJECTIVE_KEY, "")).strip() if brief is not None else ""

        qualification_signals = [
            signal
            for signal in [
                f"Look for audience fit with {target_audience_summary}." if target_audience_summary else "",
                f"Look for real need around {offer_summary or objective}." if (offer_summary or objective) else "",
                qualification_posture,
                (
                    f"When the lead is ready, route them via {conversion_target_summary}"
                    if conversion_target_summary and conversion_target_summary != "Conversion target is not set."
                    else ""
                ),
            ]
            if signal
        ]
        summary_parts = [
            f"Qualify for fit with {target_audience_summary}." if target_audience_summary else "",
            f"Confirm interest in {offer_summary or objective}." if (offer_summary or objective) else "",
            qualification_posture,
            (
                f"Conversion destination: {conversion_target_summary}"
                if conversion_target_summary and conversion_target_summary != "Conversion target is not set."
                else "Conversion destination still needs clarification."
            ),
        ]
        frame = CampaignQualificationFrame(
            campaign_id=campaign_id,
            summary=" ".join(part for part in summary_parts if part).strip(),
            offer_summary=offer_summary,
            target_audience_summary=target_audience_summary,
            qualification_posture=qualification_posture,
            conversion_target_summary=conversion_target_summary,
            conversion_target_kind=conversion_target_kind,
            conversion_target_value=conversion_target_value,
            handoff_action_types=list(handoff_action_types) if isinstance(handoff_action_types, list) else [],
            qualification_signals=qualification_signals,
        )
        self._manager.save_frame(frame)
        return frame

    def _resolve_handoff_status(self, frame: CampaignQualificationFrame, proposal) -> HandoffStatus:  # noqa: ANN001
        if proposal.qualification_state.value != "conversion_ready":
            return HandoffStatus.NONE
        if not frame.conversion_target_value or not frame.conversion_target_kind:
            return HandoffStatus.CLARIFICATION_REQUIRED
        return HandoffStatus.READY

    def _build_qualification_summary(self, frame: CampaignQualificationFrame, proposal) -> str:  # noqa: ANN001
        status = proposal.qualification_state.value
        if status == "conversion_ready":
            if frame.conversion_target_summary and frame.conversion_target_summary != "Conversion target is not set.":
                return f"Conversation looks conversion-ready. Route toward {frame.conversion_target_summary}"
            return "Conversation looks conversion-ready, but the conversion destination still needs clarification."
        if status == "potential_fit":
            if frame.target_audience_summary:
                return f"Conversation shows potential fit with {frame.target_audience_summary}. Keep qualifying before handoff."
            return "Conversation shows potential fit. Keep qualifying before handoff."
        if status == "objection_or_unclear":
            return "Conversation has objections or unclear buying intent. Resolve concerns before handoff."
        return "Conversation is still early. Keep learning whether there is real fit and intent."

    def _build_handoff_summary(
        self,
        frame: CampaignQualificationFrame,
        handoff_status: HandoffStatus,
    ) -> str:
        if handoff_status is HandoffStatus.READY:
            return f"Ready to route this lead via {frame.conversion_target_summary}"
        if handoff_status is HandoffStatus.CLARIFICATION_REQUIRED:
            return "Lead appears ready, but the campaign conversion target still needs clarification."
        return ""

    def _build_approval_context(
        self,
        proposal,  # noqa: ANN001
        *,
        frame: CampaignQualificationFrame,
        qualification_summary: str,
        handoff_status: HandoffStatus,
        handoff_summary: str,
    ) -> dict[str, object]:
        return {
            "qualification_state": proposal.qualification_state.value,
            "qualification_summary": qualification_summary,
            "handoff_intent": handoff_status is HandoffStatus.READY,
            "handoff_status": handoff_status.value,
            "handoff_summary": handoff_summary,
            "handoff_target_summary": frame.conversion_target_summary,
            "conversion_target_kind": frame.conversion_target_kind,
            "conversion_target_value": frame.conversion_target_value,
        }

    def _build_belief_state(
        self,
        frame: CampaignQualificationFrame,
        context,  # noqa: ANN001
        proposal,  # noqa: ANN001
        *,
        handoff_status: HandoffStatus,
        qualification_summary: str,
        handoff_summary: str,
    ) -> ConversationBeliefState:
        latest_inbound_text = context.latest_inbound_text().lower()
        return ConversationBeliefState(
            intent_posture=self._intent_posture_for(proposal, handoff_status),
            known_objections=self._extract_objection_hints(latest_inbound_text, proposal),
            known_fit_signals=self._extract_fit_signals(latest_inbound_text, proposal, frame),
            unanswered_questions=self._build_unanswered_questions(proposal),
            commercial_stage=self._commercial_stage_for(proposal, handoff_status),
            last_meaningful_shift=handoff_summary or qualification_summary,
            suggested_next_move=self._suggested_next_move_for(frame, proposal, handoff_status),
            last_belief_update_at=datetime.now(UTC),
        )

    def _refresh_belief_state_for_handoff(
        self,
        campaign_id: str,
        conversation_id: str,
        *,
        handoff_status: HandoffStatus,
        summary: str,
    ) -> None:
        conversation = self._conversation_manager.get(campaign_id, conversation_id)
        if conversation is None:
            return
        refreshed = replace(
            conversation.belief_state,
            commercial_stage=f"handoff_{handoff_status.value}",
            last_meaningful_shift=summary,
            suggested_next_move=self._suggested_next_move_for_handoff(handoff_status),
            last_belief_update_at=datetime.now(UTC),
        )
        self._conversation_manager.update_belief_state(
            campaign_id,
            conversation_id,
            belief_state=refreshed,
            summary=summary,
        )

    def _apply_handoff_overlay(
        self,
        belief_state: ConversationBeliefState,
        *,
        frame: CampaignQualificationFrame,
        proposal,  # noqa: ANN001
        handoff_status: HandoffStatus,
        handoff_summary: str,
    ) -> ConversationBeliefState:
        if handoff_status is HandoffStatus.NONE:
            return belief_state
        return replace(
            belief_state,
            intent_posture=self._intent_posture_for(proposal, handoff_status),
            commercial_stage=self._commercial_stage_for(proposal, handoff_status),
            last_meaningful_shift=handoff_summary or belief_state.last_meaningful_shift,
            suggested_next_move=self._suggested_next_move_for(frame, proposal, handoff_status),
            last_belief_update_at=datetime.now(UTC),
        )

    def _intent_posture_for(self, proposal, handoff_status: HandoffStatus) -> str:  # noqa: ANN001
        if handoff_status is HandoffStatus.READY:
            return "ready_to_route"
        if proposal.qualification_state.value == "conversion_ready":
            return "ready_for_conversion"
        if proposal.qualification_state.value == "potential_fit":
            return "evaluating_fit"
        if proposal.qualification_state.value == "objection_or_unclear":
            return "resolve_objection_or_uncertainty"
        return "early_curiosity"

    def _commercial_stage_for(self, proposal, handoff_status: HandoffStatus) -> str:  # noqa: ANN001
        if handoff_status is HandoffStatus.READY:
            return "handoff_ready"
        if handoff_status is HandoffStatus.CLARIFICATION_REQUIRED:
            return "conversion_target_clarification_required"
        return proposal.qualification_state.value

    def _extract_objection_hints(self, latest_inbound_text: str, proposal) -> list[str]:  # noqa: ANN001
        hints: list[str] = []
        hint_rules = (
            (("expensive", "too much", "budget"), "pricing_concern"),
            (("scam", "legit", "trust", "skeptical"), "trust_concern"),
            (("not sure", "unsure", "confused", "unclear"), "clarity_concern"),
        )
        for keywords, label in hint_rules:
            if any(keyword in latest_inbound_text for keyword in keywords):
                hints.append(label)
        if proposal.qualification_state.value == "objection_or_unclear" and not hints:
            hints.append("objection_or_unclear")
        return hints

    def _extract_fit_signals(
        self,
        latest_inbound_text: str,
        proposal,  # noqa: ANN001
        frame: CampaignQualificationFrame,
    ) -> list[str]:
        signals: list[str] = []
        if any(keyword in latest_inbound_text for keyword in ("interested", "ready", "sign up", "start", "connect me")):
            signals.append("explicit buying intent")
        if any(keyword in latest_inbound_text for keyword in ("price", "pricing", "cost", "how much")):
            signals.append("asked about pricing")
        if any(keyword in latest_inbound_text for keyword in ("demo", "call", "link")):
            signals.append("asked for next-step logistics")
        if proposal.qualification_state.value == "potential_fit":
            signals.append("potential fit signal")
        if proposal.qualification_state.value == "conversion_ready":
            signals.append("conversion-ready signal")
        if frame.target_audience_summary and proposal.qualification_state.value in {"potential_fit", "conversion_ready"}:
            signals.append(f"target-audience match: {frame.target_audience_summary}")
        return signals[:4]

    def _build_unanswered_questions(self, proposal) -> list[str]:  # noqa: ANN001
        missing_fact_map = {
            "pricing_details": "What pricing details are approved for this conversation?",
            "refund_policy": "What refund policy details are approved for this conversation?",
        }
        questions = [missing_fact_map[key] for key in proposal.missing_facts if key in missing_fact_map]
        if proposal.goal == "narrow_buying_context":
            questions.append("What outcome is the lead mainly trying to solve right now?")
        return questions[:3]

    def _suggested_next_move_for(
        self,
        frame: CampaignQualificationFrame,
        proposal,  # noqa: ANN001
        handoff_status: HandoffStatus,
    ) -> str:
        if handoff_status is HandoffStatus.READY:
            destination = frame.conversion_target_summary.rstrip(".").strip()
            return f"Route the lead via {destination}."
        if handoff_status is HandoffStatus.CLARIFICATION_REQUIRED:
            return "Clarify the campaign conversion target before routing the lead."
        if proposal.decision.value == "escalate":
            return "Escalate this conversation to the operator."
        goal_map = {
            "advance_to_conversion": "Move the conversation toward the conversion step.",
            "handle_objection": "Resolve the objection before pushing for conversion.",
            "qualify_interest": "Ask one grounded question to confirm fit and buying intent.",
            "narrow_buying_context": "Ask one narrow question to fill the missing commercial context.",
            "keep_public_reply_safe": "Keep the reply public-safe without overpitching.",
            "create_interest_without_overpitching": "Answer helpfully without pushing too hard in public.",
            "protect_high_stakes_conversation": "Pause automation and escalate to the operator.",
        }
        return goal_map.get(proposal.goal, proposal.goal.replace("_", " ").strip().capitalize())

    def _suggested_next_move_for_handoff(self, handoff_status: HandoffStatus) -> str:
        if handoff_status is HandoffStatus.DELIVERED:
            return "Wait for the lead to continue through the conversion path."
        if handoff_status is HandoffStatus.BLOCKED:
            return "Unblock the conversion handoff before pushing this lead further."
        if handoff_status is HandoffStatus.FAILED:
            return "Investigate the failed handoff path before retrying."
        return ""

    def _record_commercial_signals(
        self,
        context,  # noqa: ANN001
        proposal,  # noqa: ANN001
        *,
        frame: CampaignQualificationFrame,
        handoff_status: HandoffStatus,
        qualification_summary: str,
        handoff_summary: str,
        belief_state: ConversationBeliefState,
        previous_conversation,
    ) -> None:
        if self._signal_bridge is None:
            return

        campaign_id = context.conversation.campaign_id
        conversation_id = context.conversation.conversation_id
        latest_inbound_text = context.latest_inbound_text().lower()
        previous_qualification = (
            previous_conversation.qualification_status.strip()
            if previous_conversation is not None
            else ""
        )
        previous_handoff = previous_conversation.handoff_status.strip() if previous_conversation is not None else ""
        previous_fit_signals = (
            set(previous_conversation.belief_state.known_fit_signals)
            if previous_conversation is not None
            else set()
        )

        if proposal.qualification_state.value in {"potential_fit", "conversion_ready"} and previous_qualification not in {
            "potential_fit",
            "conversion_ready",
        }:
            self._record_signal(
                campaign_id,
                conversation_id,
                signal_type="clarified_need",
                severity=CampaignSignalSeverity.MEDIUM,
                summary=qualification_summary,
                review_eligible=False,
            )

        if (
            previous_qualification == "objection_or_unclear"
            and proposal.qualification_state.value in {"potential_fit", "conversion_ready"}
        ):
            self._record_signal(
                campaign_id,
                conversation_id,
                signal_type="objection_resolved",
                severity=CampaignSignalSeverity.HIGH,
                summary="A previously objection-heavy thread now appears back on a constructive commercial path.",
                review_eligible=False,
            )

        if "asked about pricing" in belief_state.known_fit_signals and "asked about pricing" not in previous_fit_signals:
            self._record_signal(
                campaign_id,
                conversation_id,
                signal_type="pricing_interest",
                severity=CampaignSignalSeverity.MEDIUM,
                summary="The lead asked about pricing, which suggests concrete commercial interest.",
                review_eligible=False,
            )

        if (
            any(keyword in latest_inbound_text for keyword in ("demo", "call", "link", "sign up", "start", "connect me"))
            and proposal.qualification_state.value in {"potential_fit", "conversion_ready"}
        ):
            self._record_signal(
                campaign_id,
                conversation_id,
                signal_type="cta_accepted",
                severity=CampaignSignalSeverity.HIGH,
                summary="The lead accepted a concrete next step and is moving toward conversion.",
                review_eligible=False,
            )

        if handoff_status is HandoffStatus.READY and previous_handoff != HandoffStatus.READY.value:
            self._record_signal(
                campaign_id,
                conversation_id,
                signal_type="conversion_ready_thread",
                severity=CampaignSignalSeverity.HIGH,
                summary=handoff_summary or f"Conversation is ready to route via {frame.conversion_target_summary}.",
                review_eligible=False,
            )

    def _record_handoff_signal(
        self,
        campaign_id: str,
        conversation_id: str,
        *,
        signal_type: str,
        severity: CampaignSignalSeverity,
        summary: str,
        review_eligible: bool,
        dedupe_key: str,
    ) -> None:
        if self._signal_bridge is None:
            return
        conversation = self._conversation_manager.get(campaign_id, conversation_id)
        self._signal_bridge.record(
            campaign_id=campaign_id,
            source_kind="qualification_handoff",
            source_ref=conversation_id,
            signal_type=signal_type,
            severity=severity,
            summary=summary,
            context_refs=[f"conversation:{conversation_id}"],
            account_id=conversation.account_id if conversation is not None else "",
            community_id=conversation.community_id if conversation is not None else "",
            conversation_id=conversation_id,
            review_eligible=review_eligible,
            dedupe_key_hint=dedupe_key,
            trigger_source="qualification",
        )

    def _record_signal(
        self,
        campaign_id: str,
        conversation_id: str,
        *,
        signal_type: str,
        severity: CampaignSignalSeverity,
        summary: str,
        review_eligible: bool,
    ) -> None:
        self._record_handoff_signal(
            campaign_id,
            conversation_id,
            signal_type=signal_type,
            severity=severity,
            summary=summary,
            review_eligible=review_eligible,
            dedupe_key=f"{signal_type}:{conversation_id}",
        )

    def _append_next_action_note(
        self,
        campaign_id: str,
        *,
        line: str,
        dedupe_key: str,
    ) -> None:
        self._campaign_manager.append_operational_note(
            campaign_id,
            destination=NEXT_ACTIONS_DESTINATION,
            line=line,
            category="qualification_handoff",
            dedupe_key=dedupe_key,
        )

    def _append_execution_log_note(
        self,
        campaign_id: str,
        *,
        line: str,
        dedupe_key: str,
    ) -> None:
        self._campaign_manager.append_operational_note(
            campaign_id,
            destination=EXECUTION_LOG_DESTINATION,
            line=line,
            category="qualification_handoff",
            dedupe_key=dedupe_key,
        )
