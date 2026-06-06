"""File-backed persistence for campaign qualification frames."""

from __future__ import annotations

from pathlib import Path

from telegram_app.json_store import load_json_file, write_json_file
from telegram_app.qualification.models import CampaignQualificationFrame


class QualificationManager:
    """Own campaign-scoped qualification artifacts outside session state."""

    def __init__(self, campaigns_root: str | Path) -> None:
        self._campaigns_root = Path(campaigns_root).resolve()

    def get_frame(self, campaign_id: str) -> CampaignQualificationFrame | None:
        """Load the latest qualification frame for one campaign."""
        if not campaign_id.strip():
            return None
        payload = load_json_file(self.frame_path(campaign_id), default={})
        if not isinstance(payload, dict):
            return None
        frame = CampaignQualificationFrame.from_dict(payload)
        return frame if frame.campaign_id else None

    def save_frame(self, frame: CampaignQualificationFrame) -> CampaignQualificationFrame:
        """Persist the latest qualification frame for one campaign."""
        write_json_file(self.frame_path(frame.campaign_id), frame.to_dict())
        return frame

    def frame_path(self, campaign_id: str) -> Path:
        """Return the persisted qualification frame path for one campaign."""
        return self._campaigns_root / campaign_id / "qualification" / "frame.json"
