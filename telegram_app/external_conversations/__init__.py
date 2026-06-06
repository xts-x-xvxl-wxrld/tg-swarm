"""Campaign-scoped durable conversation state for live engagement."""

from .manager import ExternalConversationManager
from .models import (
    ConversationBeliefState,
    ConsentPosture,
    ConversationTriageState,
    ConversationReviewTrigger,
    ConversationReviewTriggerType,
    ExternalConversationRecord,
    ExternalConversationStatus,
    FollowUpWindowType,
    ThreadOrigin,
)
from .projector import ExternalConversationProjector
from .timing import ExternalConversationTimingService, FollowUpTimingPolicy

__all__ = [
    "ConversationBeliefState",
    "ConsentPosture",
    "ConversationTriageState",
    "ConversationReviewTrigger",
    "ConversationReviewTriggerType",
    "ExternalConversationManager",
    "ExternalConversationProjector",
    "ExternalConversationTimingService",
    "ExternalConversationRecord",
    "ExternalConversationStatus",
    "FollowUpWindowType",
    "FollowUpTimingPolicy",
    "ThreadOrigin",
]
