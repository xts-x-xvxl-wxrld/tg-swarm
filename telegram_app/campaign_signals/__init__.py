"""Campaign signal persistence and observation-pressure helpers."""

from .bridge import CampaignSignalBridge
from .manager import CampaignSignalManager
from .models import (
    CampaignSignalCategory,
    CampaignSignalCandidate,
    CampaignSignalRecord,
    CampaignSignalSeverity,
    CampaignSignalState,
    ObservationMaterialChange,
    ObservationOperatorAttention,
    ObservationPostureUpdateKind,
    ObservationPriorityPressure,
    ObservationRecommendedNextStep,
    ObservationReviewBrief,
    ObservationReviewCursor,
    ObservationReviewResult,
    ObservationSuggestedPostureUpdate,
    ObservationSuggestedWorkItemChange,
    ObservationWorkItemChangeAction,
    ObservationWorkItemType,
    infer_signal_category,
)
from .review import (
    OBSERVATION_OWNER_ROLE,
    OBSERVATION_WORK_GOAL,
    OBSERVATION_WORK_TYPE,
    ObservationWorkRefresher,
)

__all__ = [
    "CampaignSignalBridge",
    "CampaignSignalCategory",
    "CampaignSignalCandidate",
    "CampaignSignalManager",
    "CampaignSignalRecord",
    "CampaignSignalSeverity",
    "CampaignSignalState",
    "OBSERVATION_OWNER_ROLE",
    "OBSERVATION_WORK_GOAL",
    "OBSERVATION_WORK_TYPE",
    "ObservationMaterialChange",
    "ObservationOperatorAttention",
    "ObservationPostureUpdateKind",
    "ObservationPriorityPressure",
    "ObservationRecommendedNextStep",
    "ObservationReviewBrief",
    "ObservationReviewCursor",
    "ObservationReviewResult",
    "ObservationSuggestedPostureUpdate",
    "ObservationSuggestedWorkItemChange",
    "ObservationWorkRefresher",
    "ObservationWorkItemChangeAction",
    "ObservationWorkItemType",
    "infer_signal_category",
]
