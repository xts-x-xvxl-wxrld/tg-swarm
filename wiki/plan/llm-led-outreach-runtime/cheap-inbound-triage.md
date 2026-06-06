# Cheap Inbound Triage

## Goal

Add a low-cost first-pass model layer that reads bulk inbound flow, emits lightweight structured signals, and promotes only the right threads into deeper commercial reasoning.

## Why This Slice Exists

The architecture now explicitly depends on a two-stage model pipeline:

- cheap bounded inbound triage first
- selective higher-capability commercial reasoning second

This slice is the runtime seam that enforces that split.

## Primary Seams

- [telegram_app/llm/model_selection.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/llm/model_selection.py)
- [telegram_app/engagement_brain/review_dispatcher.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/engagement_brain/review_dispatcher.py)
- [telegram_app/external_conversations/manager.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/external_conversations/manager.py)
- [telegram_app/external_conversations/models.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/external_conversations/models.py)

## New Seam

Add a dedicated package:

- `telegram_app/engagement_triage/`

Recommended initial files:

- `models.py`
- `service.py`

This seam should own:

- cheap-model prompt contract
- structured triage result parsing
- promotion decision logic
- low-cost signal extraction

## Scope

- run the cheap model for eligible inbound review moments
- emit structured triage results
- decide whether the thread should be promoted into deeper commercial review

## Triage Output Shape

The result should be compact and structured.

Minimum fields:

- interest level
- urgency level
- objection presence
- low-signal chatter flag
- review priority
- promotion decision
- concise triage summary

## Routing Rule

The cheap triage seam should not enqueue live actions directly.

It should only:

- update conversation-owned triage state
- optionally emit signal pressure
- decide whether deeper review should run now

## Non-Goals

- replacing deep commercial reasoning yet
- changing live execution policy
- building a broad campaign analytics system in this slice

## Exit Criteria

- inbound review moments use `resolve_model("summary")` through the new triage seam
- non-promoted threads can complete review without invoking the deeper brain
- promoted threads continue into the existing deeper review path safely
