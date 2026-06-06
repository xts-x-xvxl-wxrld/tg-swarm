# Evidence Foundation

## Goal

Preserve enough inbound and outbound evidence that later review layers can reason over real thread continuity instead of compressed fragments.

## Why This Slice Exists

The current runtime already captures inbound events well, but outbound continuity is still too thin for the target architecture.

This slice should fix the evidence surface before changing higher-level model behavior.

## Primary Seams

- [telegram_app/engagement/models.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/engagement/models.py)
- [telegram_app/engagement/storage.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/engagement/storage.py)
- [telegram_app/external_conversations/projector.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/external_conversations/projector.py)
- [telegram_app/external_conversations/models.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/external_conversations/models.py)
- [telegram_app/engagement_brain/context_builder.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/engagement_brain/context_builder.py)
- [telegram_app/live_execution/service.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/live_execution/service.py)

## Scope

- preserve richer outbound message evidence
- preserve enough metadata to reconstruct bounded thread continuity
- keep recent-message reconstruction useful for both cheap triage and deeper review

## Intended Changes

### Outbound Evidence

Extend the outbound evidence record so the runtime can preserve:

- outbound text
- lightweight asset refs when present
- send timestamp
- campaign and conversation linkage

### Recent Message Reconstruction

Update the bounded context builder so recent outbound messages are reconstructed with real text and timing, not only a message id placeholder.

### Compact Thread Summaries

Keep the existing conversation summary field, but stop treating it as the main evidence layer.

The summary should become a compact convenience view built on top of richer durable evidence.

## Non-Goals

- full transcript memory
- broad workspace scans for every review
- changing review policy or promotion logic yet

## Exit Criteria

- one promoted-thread review can see a credible bounded thread window with both inbound and outbound continuity
- evidence persistence remains compact and restart-safe
- existing reply matching and live execution flows still work
