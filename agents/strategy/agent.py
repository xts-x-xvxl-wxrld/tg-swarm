"""Strategy specialist agent for community-aware messaging playbook generation."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import anthropic

from telegram_app.models import SessionRecord, WorkflowArtifact, WorkflowArtifactKind
from telegram_app.sessions import SessionManager

logger = logging.getLogger(__name__)

# agents/strategy/agent.py -> agents/strategy/ -> agents/ -> tg-swarm/ (repo root)
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

STRATEGY_PLAYBOOK_JSON_MARKER = "STRATEGY_PLAYBOOK_JSON"


def _load_prompt(name: str) -> str:
    return (REPO_ROOT / "prompts" / name).read_text(encoding="utf-8")


def _resolve_model() -> str:
    model = os.getenv("DEFAULT_MODEL", "claude-sonnet-4-6").strip()
    if "/" in model:
        model = model.split("/", 1)[1]
    if not model.startswith("claude-"):
        model = "claude-sonnet-4-6"
    return model


def _get_latest_artifact_of_kind(
    session_manager: SessionManager,
    session: SessionRecord,
    kind: WorkflowArtifactKind,
) -> WorkflowArtifact | None:
    artifacts = [a for a in session_manager.list_workflow_artifacts(session) if a.kind is kind]
    if not artifacts:
        return None
    return max(artifacts, key=lambda a: a.updated_at)


class StrategyAgent:
    """Specialist agent for community-aware messaging playbook generation."""

    def __init__(
        self,
        session_manager: SessionManager | None = None,
        approval_manager: object = None,
    ) -> None:
        self._session_manager = session_manager
        self._approval_manager = approval_manager
        self._client = anthropic.Anthropic()

    def run(self, session: SessionRecord) -> tuple[str, WorkflowArtifact | None]:
        """Run strategy turn. Returns (operator_text, strategy_artifact)."""
        context_lines = ["Strategy context:"]
        if self._session_manager is not None:
            for kind, label in [
                (WorkflowArtifactKind.CAMPAIGN_BRIEF, "Campaign brief"),
                (WorkflowArtifactKind.COMMUNITY_SHORTLIST, "Community shortlist"),
            ]:
                artifact = _get_latest_artifact_of_kind(self._session_manager, session, kind)
                if artifact is not None:
                    context_lines.append(
                        f"{label}: {json.dumps(artifact.data, ensure_ascii=True)}"
                    )

        user_content = "\n".join(context_lines) + "\n\nPlease produce the strategy playbook."

        system = [
            {"type": "text", "text": _load_prompt("strategy.md")},
            {"type": "text", "text": _load_prompt("shared_runtime.md")},
        ]
        messages = [{"role": "user", "content": user_content}]

        model = _resolve_model()
        logger.info("StrategyAgent calling Anthropic API model=%s", model)

        api_response = self._client.messages.create(
            model=model,
            max_tokens=4096,
            system=system,
            messages=messages,
        )

        final_output = "".join(
            block.text for block in api_response.content if hasattr(block, "text")
        ).strip()

        playbook_data = self._parse_playbook_json(final_output)
        operator_text = self._strip_json_block(final_output)

        artifact: WorkflowArtifact | None = None
        if self._session_manager is not None:
            playbook_summary = str(playbook_data.get("campaign_strategy_summary", "Strategy playbook ready."))
            existing = _get_latest_artifact_of_kind(
                self._session_manager, session, WorkflowArtifactKind.STRATEGY_PLAYBOOK
            )
            if existing is not None:
                existing.data = playbook_data
                existing.summary = playbook_summary
                self._session_manager.save_workflow_artifact(session, existing)
                artifact = existing
            else:
                artifact = self._session_manager.create_workflow_artifact(
                    session=session,
                    kind=WorkflowArtifactKind.STRATEGY_PLAYBOOK,
                    title="Strategy playbook",
                    summary=playbook_summary,
                    data=playbook_data,
                )

        return operator_text, artifact

    def _parse_playbook_json(self, output: str) -> dict:
        if STRATEGY_PLAYBOOK_JSON_MARKER not in output:
            return {"raw_output": output}
        _, _, remainder = output.partition(STRATEGY_PLAYBOOK_JSON_MARKER)
        remainder = remainder.strip()
        if remainder.startswith("```json"):
            remainder = remainder[len("```json"):].strip()
        elif remainder.startswith("```"):
            remainder = remainder[3:].strip()
        if remainder.endswith("```"):
            remainder = remainder[:-3].strip()
        try:
            return json.loads(remainder)
        except json.JSONDecodeError:
            return {"raw_output": output}

    def _strip_json_block(self, output: str) -> str:
        if STRATEGY_PLAYBOOK_JSON_MARKER not in output:
            return output.strip()
        operator_text, _, _ = output.partition(STRATEGY_PLAYBOOK_JSON_MARKER)
        return operator_text.strip()
