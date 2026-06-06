# LLM-Led Runtime Integration Plan

## Goal

Turn the [LLM-Led Outreach Runtime](../../spec/llm-led-outreach-runtime.md) behavior spec and the [Freeform-To-Structured Compilation](../../spec/freeform-to-structured-compilation.md) control-plane spec into one implementation series that can land on top of the current Telegram-native runtime without a flag-day rewrite.

## Why This Is A Separate Series

Those two specs now do different jobs on purpose:

- `llm-led-outreach-runtime` defines the desired commercial behavior of the live outreach machine
- `freeform-to-structured-compilation` defines how freeform reasoning must compile into typed runtime intent before mutation, authorization, scheduling, or execution

The repo now needs one implementation plan that converges them.

Without that bridge, the docs are clearer but the delivery path is still split awkwardly:

- the outreach plan is intentionally behavior-only
- the compilation spec is intentionally architecture-only
- the current runtime still mixes marker contracts, phrase parsers, fixed ladders, and newer structured seams

This plan is the integration layer that turns those two source-of-truth specs into one repo-shaped migration sequence.

## What This Plan Covers

This series covers:

- the smallest compiled-intent envelope that the runtime can adopt gradually
- where operator freeform input should compile into typed control and work proposals
- how the planning ladder becomes a proposal-driven work selection loop instead of a hardcoded next-step chain
- how the live outreach reasoning seams should emit typed proposals rather than relying on marker-first contracts forever
- how deterministic policy, authorization, and execution stay late in the flow

## Target End State

The target runtime shape for this series is:

- one operator-facing control brain that interprets freeform operator intent and campaign state
- a set of bounded reasoning surfaces for planning, triage, promoted-thread review, and campaign-level observation
- one reusable compiled-intent seam that carries typed proposals from all of those reasoning surfaces
- one late deterministic execution boundary that still owns policy, consent, readiness, queueing, and external writes

In that end state:

- `discovery`, `strategy`, and `account_planning` remain valid bounded work families when useful
- they no longer define the permanent top-level architecture of the runtime
- the runtime can introduce new work families and proposal kinds without treating them as malformed by default
- durable artifacts remain useful for operator review, but they are no longer the only machine-readable output contract

This series does not replace the behavior spec or the compilation spec.

It is the implementation bridge between them.

## Relationship To Existing Plans

- [Agentic Campaign Runtime Plan](../agentic-campaign-runtime/index.md) remains the broader product-direction series for campaign interpretation, conversion targets, qualification, and continuous operation.
- [LLM-Led Outreach Runtime Plan](../llm-led-outreach-runtime/index.md) remains the behavior and reasoning series for evidence quality, triage, belief state, commercial reasoning, and traction visibility.
- [Unified Campaign Loop Rebuild](../unified-campaign-loop-rebuild/index.md) remains the campaign-loop and work-family transition series that first moved the repo away from stage-only thinking.
- This plan sits across those tracks and focuses on how freeform reasoning should become typed runtime intent in the active runtime.

## Document Map

1. [Current State Audit](./current-state-audit.md)
   What the runtime already supports, where it is already flexible, and where the remaining rigidity still lives.
2. [Intent Envelope And Persistence](./intent-envelope-and-persistence.md)
   The minimum compiled-intent contract, storage seam, lifecycle, and first intent kinds.
3. [Operator Control And Work Proposal Migration](./operator-control-and-work-proposal-migration.md)
   How operator freeform input should stop depending on phrase gates, marker parsing, and implicit next-step ladders.
4. [Specialist Output And Execution Transition](./specialist-output-and-execution-transition.md)
   How deeper reasoning surfaces should emit typed proposals while deterministic execution remains unchanged.
5. [Agent Architecture Transition](./agent-architecture-transition.md)
   How the runtime should move from a fixed planning-specialist ladder toward the intended `control brain + reasoning surfaces + compiled intents + late deterministic execution` model.
6. [Agent Infra And Tooling Expansion](./agent-infra-and-tooling-expansion.md)
   How reasoning surfaces should gain richer bounded read access, proposal-lifecycle visibility, and a shared read-side runtime seam without widening direct write power.
7. [Cleanup And Cutover](./cleanup-and-cutover.md)
   How legacy marker contracts, phrase-gated compatibility paths, and stale ladder assumptions should be retired once the proposal layer is proven.
8. [Implementation Sequence](./implementation-sequence.md)
   The recommended order, migration checkpoints, and acceptance gates for landing the series safely.

## Delivery Principles

- Keep freeform reasoning broad and useful.
- Keep runtime mutation typed, inspectable, and restart-safe.
- Prefer introducing one compiler seam over widening ad hoc regex and marker logic.
- Migrate high-leverage control surfaces first, especially operator controls and work proposals.
- Keep deterministic policy late, close to authorization and execution.
- Dual-write or shadow-compile during transition whenever a legacy contract is still active.
- Plan explicit cleanup and contract retirement work instead of letting migration scaffolding become permanent architecture.
- Land each slice with focused tests and clear operator-visible inspection paths.

## Success Criteria

This series is complete when:

- operator freeform control no longer depends mainly on phrase-gated parsing
- the runtime has one reusable compiled-intent envelope for state mutation and control proposals
- new work and control concepts can be introduced without treating them as malformed by default
- the planning loop is driven by typed work proposals and deterministic evaluation, not only a hardcoded ladder
- live outreach reasoning emits typed proposals that can be inspected, accepted, rejected, or applied
- obsolete marker-first, phrase-first, and ladder-only compatibility paths are either removed or reduced to deliberate narrow fallbacks
- deterministic policy, consent, readiness, and execution seams remain explicit and late in the flow
