"""Backward-compatibility shim: AgencyOrchestratorAdapter is now PurposeBuiltOrchestrator."""

from telegram_app.orchestrator import PurposeBuiltOrchestrator

AgencyOrchestratorAdapter = PurposeBuiltOrchestrator  # backward compat alias

__all__ = ["AgencyOrchestratorAdapter", "PurposeBuiltOrchestrator"]
