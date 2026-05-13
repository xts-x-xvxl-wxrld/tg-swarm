"""Structured runtime records for the Telegram-native app."""

from .approval import ApprovalRecord, ApprovalStatus
from .campaign import CampaignRecord, CampaignStatus
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
    "CampaignRecord",
    "CampaignStatus",
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
