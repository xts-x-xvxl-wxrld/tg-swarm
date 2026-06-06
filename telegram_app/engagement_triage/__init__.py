"""Cheap inbound triage seam for live engagement review routing."""

from .models import (
    ConversationTriageState,
    InboundTriageResult,
    TriageInterestLevel,
    TriagePromotionDecision,
    TriageReviewPriority,
    TriageUrgencyLevel,
)


def __getattr__(name: str):  # pragma: no cover - trivial lazy export helper.
    if name == "CheapInboundTriageService":
        from .service import CheapInboundTriageService

        return CheapInboundTriageService
    raise AttributeError(name)

__all__ = [
    "CheapInboundTriageService",
    "ConversationTriageState",
    "InboundTriageResult",
    "TriageInterestLevel",
    "TriagePromotionDecision",
    "TriageReviewPriority",
    "TriageUrgencyLevel",
]
