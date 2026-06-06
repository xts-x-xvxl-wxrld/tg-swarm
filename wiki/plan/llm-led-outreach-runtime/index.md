# LLM-Led Outreach Runtime Plan

## Goal

Turn the [LLM-Led Outreach Runtime](../../spec/llm-led-outreach-runtime.md) spec into a concrete implementation series that can land in the existing live runtime without a flag-day rewrite.

## Why This Is A Separate Series

The repo already has meaningful live-runtime seams in code:

- inbound event ingestion
- external conversation projection
- bounded engagement-brain review
- autonomous-send authorization
- live execution
- live ops

What it does not yet have is one implementation series that makes those seams behave as a true two-stage, LLM-led outreach machine with:

- cheap inbound triage
- richer durable conversation evidence
- conversation belief state
- promoted-thread commercial reasoning
- opportunity and yield visibility

This series is intentionally behavioral and reasoning-focused.

It is not the place to carry the broader control-plane redesign around freeform agent expression, typed intent compilation, open work-family ontology, or replacement of marker-first runtime contracts.

## Relationship To Existing Plans

- [Live Engagement MVP](../live-engagement-mvp/index.md) remains the earlier live-runtime foundation series.
- [Engagement Machine Readiness](../engagement-machine-readiness/index.md) remains the status bridge for already-landed live-runtime seams.
- [Freeform-To-Structured Compilation](../../spec/freeform-to-structured-compilation.md) now owns the broader control-plane philosophy for how agent freedom should compile into structured runtime intent.
- [LLM-Led Runtime Integration Plan](../llm-led-runtime-integration/index.md) is the implementation umbrella that converges this behavior series with the compiled-intent control-plane work.
- This folder is the forward implementation track for making the live outreach machine truly LLM-led in its commercial reasoning and behavior.

## Document Map

1. [Current State Audit](./current-state-audit.md)
   A compact baseline of what is already shipped, what is partially there, and what still blocks the target architecture.
2. [Implementation Sequence](./implementation-sequence.md)
   The recommended delivery order and acceptance gates for the series.
3. [Evidence Foundation](./evidence-foundation.md)
   Slice 1: preserve richer inbound and outbound evidence for later reasoning.
4. [Cheap Inbound Triage](./cheap-inbound-triage.md)
   Slice 2: add a low-cost first-pass model layer for bulk inbound reads and review prioritization.
5. [Conversation Belief State](./conversation-belief-state.md)
   Slice 3: persist durable triage state plus conversation belief state under the external conversation seam.
6. [Promoted-Thread Commercial Reasoning](./promoted-thread-commercial-reasoning.md)
   Slice 4: replace deeper heuristic next-move decisioning with structured LLM review for promoted threads.
7. [Opportunity Signals And Commercial Summaries](./opportunity-signals-and-commercial-summaries.md)
   Slice 5: model positive momentum and expose commercial traction through campaign signals, continuous ops, and live ops.

## Delivery Principles

- Keep the Telegram runtime thin.
- Keep ingestion, conversation state, reasoning, authorization, and execution as separate seams.
- Introduce the cheap model as a new bounded review tier, not as an overload of the deeper brain.
- Persist structured runtime state instead of hiding important meaning in freeform summaries only.
- Replace heuristics only where the spec requires real commercial judgment.
- Keep deterministic policy narrow and hard at the authorization and execution layers.
- Land each slice with focused tests and restart-safe persistence behavior.

## Success Criteria

This series is complete when:

- most inbound flow is first read by a cheaper bounded model
- promoted threads are reviewed by a more capable commercial reasoning model
- conversations carry durable triage and belief-state records
- outbound reasoning sees real inbound and outbound continuity, not only partial context
- positive momentum is modeled as explicitly as risk and friction
- live ops and continuous ops surface commercial traction, not only operational motion
- the deeper engagement path is genuinely LLM-led in its decisioning while execution remains deterministically controlled
