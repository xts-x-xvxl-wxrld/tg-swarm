# Implementation Sequence

## Goal

Translate the LLM-led outreach target into a delivery order that lands safely on top of the current live runtime.

This sequence is intentionally scoped to outreach-behavior improvements:

- evidence quality
- cheap review
- belief-state continuity
- deeper commercial reasoning
- commercial momentum visibility

It does not try to carry the separate control-plane redesign around freeform agent expression, typed intent compilation, or open runtime ontology. Those concerns now belong to:

- [Freeform-To-Structured Compilation](../../spec/freeform-to-structured-compilation.md)

## Recommended Order

### Slice 1: Evidence Foundation

Land [Evidence Foundation](./evidence-foundation.md) first.

Why first:

- better reasoning depends on better evidence
- cheap triage and promoted-thread review both need richer thread continuity
- this slice improves correctness before it changes model behavior

Exit criteria:

- inbound and outbound evidence preserve enough detail for later bounded review
- recent conversation context can reconstruct both inbound and outbound continuity
- persistence remains compact and restart-safe

### Slice 2: Cheap Inbound Triage

Land [Cheap Inbound Triage](./cheap-inbound-triage.md) second.

Why second:

- the repo already has review dispatch and model-role routing foundations
- this slice delivers the token-efficiency architecture quickly
- it creates a clean promotion boundary before deeper-brain changes land

Exit criteria:

- most inbound review moments go through the cheap model tier first
- triage emits structured low-cost signals and a promotion decision
- non-promoted threads can exit review without invoking deeper commercial reasoning

### Slice 3: Conversation Belief State

Land [Conversation Belief State](./conversation-belief-state.md) third.

Why third:

- cheap triage needs somewhere durable to write its meaning
- deeper commercial reasoning should update explicit state, not only freeform summaries
- this slice makes later reasoning output inspectable and reusable

Exit criteria:

- conversations persist triage state and belief state explicitly
- state survives restart and can be refreshed over multiple turns
- review and qualification paths can consume the new fields without breaking compatibility

### Slice 4: Promoted-Thread Commercial Reasoning

Land [Promoted-Thread Commercial Reasoning](./promoted-thread-commercial-reasoning.md) fourth.

Why fourth:

- the promotion boundary and state model should exist before deeper decisioning is replaced
- this is the slice that makes the system truly LLM-led in its commercial next-move choice
- it is easier to validate once evidence and persistence are already stable

Exit criteria:

- promoted-thread review is model-led in interpretation, belief-state update, and next-move choice
- deterministic code no longer acts as the main commercial decision engine
- authorization and execution boundaries remain unchanged and deterministic

### Slice 5: Opportunity Signals And Commercial Summaries

Land [Opportunity Signals And Commercial Summaries](./opportunity-signals-and-commercial-summaries.md) last.

Why last:

- it depends on richer evidence and better state
- it should summarize already-landed behavior, not invent new hidden logic
- it turns the improved machine into something the operator can actually steer

Exit criteria:

- positive momentum and yield signals are persisted alongside risk signals
- continuous ops reports commercial traction as well as operational readiness
- live ops exposes commercially meaningful status, not only blocked or paused counts

## Cross-Slice Validation

After each slice:

- run the smallest focused pytest coverage for the touched seam
- verify live planning flows do not regress
- verify new durable state survives restart where applicable

Before calling the series ready for broader rollout:

- run `python -m pytest tests/` if the tree is stable enough
- run at least one live smoke path that covers inbound ingestion, cheap triage, promoted-thread review, and operator status inspection
