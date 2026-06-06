"""Campaign-owned persistence for engagement timing policy and outcome metrics."""

from __future__ import annotations

from pathlib import Path
from threading import RLock

from telegram_app.engagement_policy.models import (
    CampaignEngagementMetrics,
    CampaignEngagementPolicy,
    CampaignEngagementPolicyState,
    ReplyLatencyTier,
    ReplyTimingDecision,
)
from telegram_app.json_store import load_json_file, write_json_file


class CampaignEngagementPolicyManager:
    """Persist engagement timing policy and light outcome metrics per campaign."""

    def __init__(self, campaigns_root: str | Path) -> None:
        self._campaigns_root = Path(campaigns_root).resolve()
        self._lock = RLock()

    def get_state(self, campaign_id: str) -> CampaignEngagementPolicyState:
        """Load the current policy-plus-metrics state for one campaign."""
        payload = load_json_file(self.policy_path(campaign_id), default={})
        return CampaignEngagementPolicyState.from_dict(payload)

    def get_policy(self, campaign_id: str) -> CampaignEngagementPolicy:
        """Load only the campaign policy for one campaign."""
        return self.get_state(campaign_id).policy

    def get_metrics(self, campaign_id: str) -> CampaignEngagementMetrics:
        """Load only the stored engagement outcome metrics for one campaign."""
        return self.get_state(campaign_id).metrics

    def save_policy(self, campaign_id: str, policy: CampaignEngagementPolicy) -> CampaignEngagementPolicyState:
        """Persist a replaced policy while preserving accumulated metrics."""
        with self._lock:
            state = self.get_state(campaign_id)
            state.policy = policy
            self._save_state(campaign_id, state)
            return state

    def record_timing_decision(
        self,
        campaign_id: str,
        *,
        decision: ReplyTimingDecision,
        community_key: str = "",
        objection_hints: list[str] | None = None,
    ) -> CampaignEngagementMetrics:
        """Record one queue-time reply decision for later campaign learning."""
        with self._lock:
            state = self.get_state(campaign_id)
            state.metrics.record_decision(
                decision_type=decision.decision_type,
                latency_tier=decision.latency_tier,
                suppression_reason=decision.suppression_reason,
                community_key=community_key,
                objection_hints=objection_hints,
            )
            self._save_state(campaign_id, state)
            return state.metrics

    def record_execution_outcome(
        self,
        campaign_id: str,
        *,
        outcome_code: str,
        latency_tier: ReplyLatencyTier,
        community_key: str = "",
        objection_hints: list[str] | None = None,
    ) -> CampaignEngagementMetrics:
        """Record one live-execution outcome under the campaign's metrics scaffold."""
        with self._lock:
            state = self.get_state(campaign_id)
            state.metrics.record_execution_outcome(
                outcome_code=outcome_code,
                latency_tier=latency_tier,
                community_key=community_key,
                objection_hints=objection_hints,
            )
            self._save_state(campaign_id, state)
            return state.metrics

    def policy_path(self, campaign_id: str) -> Path:
        """Return the durable engagement policy path for one campaign."""
        return self._campaigns_root / campaign_id / "engagement-policy.json"

    def _save_state(self, campaign_id: str, state: CampaignEngagementPolicyState) -> None:
        write_json_file(self.policy_path(campaign_id), state.to_dict())
