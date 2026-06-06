"""Storage helpers for campaign-local continuous-operations state."""

from __future__ import annotations

from pathlib import Path

from telegram_app.continuous_ops.models import ContinuousOpsState
from telegram_app.json_store import load_json_file, write_json_file


def state_path_for_workspace(workspace_path: str | Path) -> Path:
    """Return the campaign-local state path for continuous operations."""
    return Path(workspace_path) / "continuous_ops" / "state.json"


def load_continuous_ops_state_for_workspace(
    workspace_path: str | Path | None,
) -> ContinuousOpsState | None:
    """Load the campaign-local continuous-ops state when present."""
    if not workspace_path:
        return None
    payload = load_json_file(state_path_for_workspace(workspace_path), default={})
    if not payload:
        return None
    state = ContinuousOpsState.from_dict(payload)
    if not state.campaign_id:
        return None
    return state


def write_continuous_ops_state_for_workspace(
    workspace_path: str | Path,
    state: ContinuousOpsState,
) -> ContinuousOpsState:
    """Persist one campaign-local continuous-ops state."""
    write_json_file(state_path_for_workspace(workspace_path), state.to_dict())
    return state
