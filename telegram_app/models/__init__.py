"""Structured runtime records for the Telegram-native app."""

from .approval import ApprovalRecord, ApprovalStatus
from .asset import CampaignAssetKind, CampaignAssetRecord, CampaignAssetRole
from .campaign import CampaignRecord, CampaignStatus
from .conversion_target import (
    ConversionTargetFamily,
    ConversionTargetKind,
    ConversionTargetRecord,
)
from .schedule import ScheduleRecord, ScheduleStatus
from .session import SessionRecord, SessionStatus
from .work_item import WorkItemPriority, WorkItemRecord, WorkItemStatus
from .workflow import (
    WorkflowArtifact,
    WorkflowArtifactKind,
    WorkflowSnapshot,
    WorkflowStage,
)

__all__ = [
    "ApprovalRecord",
    "ApprovalStatus",
    "CampaignAssetKind",
    "CampaignAssetRecord",
    "CampaignAssetRole",
    "CampaignRecord",
    "CampaignStatus",
    "ConversionTargetFamily",
    "ConversionTargetKind",
    "ConversionTargetRecord",
    "ScheduleRecord",
    "ScheduleStatus",
    "SessionRecord",
    "SessionStatus",
    "WorkItemPriority",
    "WorkItemRecord",
    "WorkItemStatus",
    "WorkflowArtifact",
    "WorkflowArtifactKind",
    "WorkflowSnapshot",
    "WorkflowStage",
]
