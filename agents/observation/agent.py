"""Observation-surface agent for bounded campaign-signal review."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import anthropic

from telegram_app.agent_runtime import AgentRuntimeBroker
from telegram_app.campaign_signals import ObservationReviewBrief
from telegram_app.llm import resolve_model
from telegram_app.monitoring import NullRuntimeEventLogger, RuntimeEventLogger, RuntimeTraceContext
from telegram_app.models import SessionRecord
from telegram_app.orchestrator.context_builder import build_runtime_context
from telegram_app.workflow_validation import parse_marked_json_block, validate_observation_review

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OBSERVATION_REVIEW_JSON_MARKER = "OBSERVATION_REVIEW_JSON"


def _load_prompt(name: str) -> str:
    return (REPO_ROOT / "prompts" / name).read_text(encoding="utf-8")


class ObservationReviewAgent:
    """Observation-surface agent that converts compact signal digests into steering advice."""

    def __init__(
        self,
        monitor: RuntimeEventLogger | None = None,
        runtime_broker: AgentRuntimeBroker | None = None,
    ) -> None:
        self._monitor = monitor or NullRuntimeEventLogger()
        self._runtime_broker = runtime_broker
        self._client = anthropic.Anthropic()

    def run(
        self,
        session: SessionRecord,
        *,
        review_reason: str,
        signal_digests: list[dict[str, Any]],
        current_planning_work_summary: list[dict[str, Any]],
        last_review_summary: str = "",
        trace_context: RuntimeTraceContext | None = None,
    ) -> tuple[str, ObservationReviewBrief | None]:
        """Run one bounded observation review and return operator text plus the parsed brief."""
        trace_context = (
            trace_context
            or RuntimeTraceContext(trace_id="", session_id=session.session_id, user_id=session.operator_id)
        ).with_session(session)
        observation_context = {
            "observation_review_reason": review_reason.strip(),
            "signal_digest_count": len(signal_digests),
            "last_observation_review_summary": last_review_summary.strip(),
            "current_planning_work_summary": current_planning_work_summary,
        }
        system = [
            {"type": "text", "text": _load_prompt("observation.md")},
            {"type": "text", "text": _load_prompt("shared_runtime.md")},
            {
                "type": "text",
                "text": build_runtime_context(
                    session,
                    pending_approval=None,
                    observation_context=observation_context,
                    work_type="observation",
                    agent_runtime_broker=self._runtime_broker,
                ),
            },
        ]
        user_content = "\n".join(
            [
                "Observation review context:",
                f"Review reason: {review_reason.strip() or 'Observation review was requested by runtime pressure.'}",
                f"Signal digest count: {len(signal_digests)}",
                "Current planning work summary:",
                json.dumps(current_planning_work_summary, ensure_ascii=True, sort_keys=True),
                "Latest observation review summary:",
                last_review_summary.strip() or "none",
                "Signal digests:",
                json.dumps(signal_digests, ensure_ascii=True, sort_keys=True),
                "",
                "Please produce the bounded observation review.",
            ]
        )
        messages = [{"role": "user", "content": user_content}]

        model = resolve_model("summary")
        logger.info("ObservationReviewAgent calling Anthropic API model=%s", model)
        self._monitor.record_event(
            component="observation_agent",
            event_type="llm_request",
            trace_context=trace_context,
            session=session,
            payload={
                "model": model,
                "prompt_assets": ["observation.md", "shared_runtime.md"],
                "messages": messages,
            },
        )

        try:
            api_response = self._client.messages.create(
                model=model,
                max_tokens=2048,
                system=system,
                messages=messages,
            )
        except Exception as exc:
            self._monitor.record_event(
                component="observation_agent",
                event_type="llm_failed",
                trace_context=trace_context,
                session=session,
                payload={"model": model, "error": str(exc), "error_type": type(exc).__name__},
            )
            raise

        final_output = "".join(
            block.text for block in api_response.content if hasattr(block, "text")
        ).strip()
        payload = parse_marked_json_block(final_output, OBSERVATION_REVIEW_JSON_MARKER) or {}
        operator_text = self._strip_json_block(final_output)
        validation_error = validate_observation_review(payload)
        brief = ObservationReviewBrief.from_dict(payload) if validation_error is None else None
        if validation_error is not None:
            operator_text = self._build_invalid_review_response(operator_text, validation_error)

        self._monitor.record_event(
            component="observation_agent",
            event_type="llm_response",
            trace_context=trace_context,
            session=session,
            payload={
                "model": model,
                "output_text": final_output,
                "operator_text": operator_text,
                "validation_error": validation_error or "",
            },
        )
        return operator_text, brief

    def _strip_json_block(self, output: str) -> str:
        if OBSERVATION_REVIEW_JSON_MARKER not in output:
            return output.strip()
        operator_text, _, _ = output.partition(OBSERVATION_REVIEW_JSON_MARKER)
        return operator_text.strip()

    def _build_invalid_review_response(self, operator_text: str, validation_error: str) -> str:
        summary = operator_text.strip() or "I generated an observation review, but I could not trust its structured output."
        return (
            f"{summary}\n\n"
            "I did not save this observation review because its machine-readable payload was incomplete. "
            f"{validation_error} Please ask me to retry observation review."
        )
