# Qualification And Handoff Runtime

## Goal

Define how the runtime reasons about lead quality and routes qualified leads toward the campaign's conversion target.

## Core Problem

Qualification is currently implied by strategy and live engagement ideas, but not yet modeled as its own campaign-aware runtime seam.

## Desired Direction

Qualification should be:

- grounded in campaign assets and the real offer
- adaptable per campaign
- durable enough to support later review and improvement
- tightly connected to the conversion destination

## First Questions To Lock

- what the smallest structured qualification output should be
- how much qualification remains pure reasoning versus persisted state
- what counts as a handoff for different conversion target types
- how the runtime records successful, failed, or blocked conversion attempts

## Expected Deliverables

- campaign-specific qualification frames
- durable qualification outcomes or summaries
- conversion-ready handoff actions and status
- operator-visible escalation when handoff is blocked

## File-Level Direction

Expected touchpoints will likely include:

- a new qualification or conversion seam under `telegram_app/`
- `telegram_app/external_conversations/`
- `telegram_app/live_execution/`
- `telegram_app/engagement_brain/`
- operator-facing summaries in orchestrator or later live-ops surfaces
