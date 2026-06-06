"""Campaign-backed persistence for operator-owned live-ops controls."""

from __future__ import annotations

from pathlib import Path
from threading import RLock

from telegram_app.json_store import load_json_file, write_json_file
from telegram_app.live_ops.models import LiveOpsControlProfile, utc_now


class LiveOpsControlManager:
    """Persist operator-managed live-ops controls per campaign."""

    def __init__(self, campaigns_root: str | Path) -> None:
        self._campaigns_root = Path(campaigns_root).resolve()
        self._lock = RLock()

    def get_profile(self, campaign_id: str) -> LiveOpsControlProfile:
        """Return the current control profile for one campaign."""
        normalized_campaign_id = campaign_id.strip()
        if not normalized_campaign_id:
            return LiveOpsControlProfile(campaign_id="")
        payload = load_json_file(self.profile_path(normalized_campaign_id), default={})
        profile = LiveOpsControlProfile.from_dict(payload)
        if profile.campaign_id:
            return profile
        return LiveOpsControlProfile(campaign_id=normalized_campaign_id)

    def save_profile(self, profile: LiveOpsControlProfile) -> LiveOpsControlProfile:
        """Persist one control profile."""
        with self._lock:
            profile.updated_at = utc_now()
            write_json_file(self.profile_path(profile.campaign_id), profile.to_dict())
        return profile

    def profile_path(self, campaign_id: str) -> Path:
        """Return the campaign-local control-profile path."""
        return self._campaign_root(campaign_id) / "live-ops" / "controls.json"

    def _campaign_root(self, campaign_id: str) -> Path:
        return self._campaigns_root / campaign_id
