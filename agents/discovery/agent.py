"""Discovery specialist agent for Telegram community shortlist generation."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import anthropic

from telegram_app.approvals import ApprovalManager
from telegram_app.discovery import (
    parse_discovery_shortlist,
    persist_discovery_shortlist,
    strip_discovery_json_block,
)
from telegram_app.models import ApprovalRecord, SessionRecord, WorkflowArtifact
from telegram_app.orchestrator.context_builder import build_runtime_context
from telegram_app.sessions import SessionManager

logger = logging.getLogger(__name__)

# agents/discovery/agent.py -> agents/discovery/ -> agents/ -> tg-swarm/ (repo root)
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _load_prompt(name: str) -> str:
    return (REPO_ROOT / "prompts" / name).read_text(encoding="utf-8")


def _resolve_model() -> str:
    model = os.getenv("DEFAULT_MODEL", "claude-sonnet-4-6").strip()
    if "/" in model:
        model = model.split("/", 1)[1]
    if not model.startswith("claude-"):
        model = "claude-sonnet-4-6"
    return model


class DiscoveryAgent:
    """Specialist agent for Telegram community discovery and shortlist generation."""

    def __init__(
        self,
        session_manager: SessionManager | None = None,
        approval_manager: ApprovalManager | None = None,
    ) -> None:
        self._session_manager = session_manager
        self._approval_manager = approval_manager
        self._client = anthropic.Anthropic()

    def run(
        self,
        session: SessionRecord,
        operator_message: str,
    ) -> tuple[str, WorkflowArtifact | None, ApprovalRecord | None]:
        """Run one discovery turn. Returns (operator_text, artifact, approval)."""
        system = [
            {"type": "text", "text": _load_prompt("discovery.md")},
            {"type": "text", "text": _load_prompt("shared_runtime.md")},
            {"type": "text", "text": build_runtime_context(session, pending_approval=None, discovery_mode=True)},
        ]
        messages = [{"role": "user", "content": operator_message}]

        model = _resolve_model()
        logger.info("DiscoveryAgent calling Anthropic API model=%s", model)

        api_response = self._client.messages.create(
            model=model,
            max_tokens=4096,
            system=system,
            messages=messages,
        )

        final_output = "".join(
            block.text for block in api_response.content if hasattr(block, "text")
        ).strip()

        artifact: WorkflowArtifact | None = None
        approval: ApprovalRecord | None = None

        if self._session_manager is not None and self._approval_manager is not None:
            shortlist_payload = parse_discovery_shortlist(final_output)
            if shortlist_payload is not None:
                artifact, approval = persist_discovery_shortlist(
                    session_manager=self._session_manager,
                    approval_manager=self._approval_manager,
                    session=session,
                    shortlist_payload=shortlist_payload,
                )

        operator_text = strip_discovery_json_block(final_output)
        return operator_text, artifact, approval
