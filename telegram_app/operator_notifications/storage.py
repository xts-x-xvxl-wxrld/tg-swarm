"""JSON-backed storage for campaign operator-intervention state."""

from __future__ import annotations

from pathlib import Path

from telegram_app.json_store import load_json_file, write_json_file
from telegram_app.operator_notifications.models import OperatorInterventionRecord


def file_path_for_workspace(workspace_path: str | Path) -> Path:
    """Return the intervention-state file for one campaign workspace."""
    return Path(workspace_path) / "operator_notifications" / "interventions.json"


def load_interventions_for_workspace(workspace_path: str | Path) -> list[OperatorInterventionRecord]:
    """Load persisted interventions for one workspace."""
    payload = load_json_file(file_path_for_workspace(workspace_path), default={"interventions": []})
    raw_interventions = payload.get("interventions", [])
    if not isinstance(raw_interventions, list):
        return []
    return [
        intervention
        for intervention in (
            OperatorInterventionRecord.from_dict(item)
            for item in raw_interventions
            if isinstance(item, dict)
        )
        if intervention.intervention_id and intervention.campaign_id and intervention.dedupe_key
    ]


def write_interventions_for_workspace(
    workspace_path: str | Path,
    interventions: list[OperatorInterventionRecord],
) -> None:
    """Persist interventions for one workspace."""
    write_json_file(
        file_path_for_workspace(workspace_path),
        {
            "interventions": [intervention.to_dict() for intervention in interventions],
        },
    )
