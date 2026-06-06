# Implementation Sequence

## Goal

Translate the combined LLM-led behavior plus compiled-intent control-plane direction into a delivery order that can land safely on top of the current runtime.

## End-State Check

This sequence is aiming at a runtime where:

- one operator-facing control brain interprets freeform operator steering and campaign state
- bounded reasoning surfaces handle planning, cheap inbound triage, promoted-thread reasoning, and campaign-level observation
- all meaningful state-change suggestions flow through one typed proposal seam
- deterministic authorization and execution remain late and explicit

This means the migration is not complete merely because the current discovery, strategy, and account-planning specialists produce better outputs.

It is complete only when those planning specialists have become bounded work-family surfaces inside a broader proposal-first runtime rather than remaining the permanent top-level architecture.

## Recommended Order

### Slice 1: Intent Envelope And Persistence

Land [Intent Envelope And Persistence](./intent-envelope-and-persistence.md) first.

Why first:

- both specs now depend on one reusable proposal boundary
- the storage layer is already flexible enough to support it
- this is the smallest safe first slice that does not yet disturb execution

Exit criteria:

- one compiled-intent record shape exists
- intent kinds can be validated by kind
- proposed versus accepted versus applied state is inspectable

### Slice 2: Operator Control Shadow Compilation

Land the first half of [Operator Control And Work Proposal Migration](./operator-control-and-work-proposal-migration.md) second.

Why second:

- operator freeform control is the cleanest first real compiler target
- it exercises the envelope on live runtime input without widening autonomy
- it replaces the most brittle phrase-only and marker-only control surfaces first

Exit criteria:

- selected operator turns compile into stored intents in shadow mode
- legacy control paths still apply behavior while comparison remains possible
- schedule mutation and live-ops control have clear proposed-intent visibility

### Slice 3: Intent-First Control Application And Work Proposal Evaluation

Land the second half of [Operator Control And Work Proposal Migration](./operator-control-and-work-proposal-migration.md) third.

Why third:

- once shadow compilation is trustworthy, narrow control kinds can safely move to intent-first application
- this is the right time to break the hardest remaining fixed ladder assumptions
- it lets the runtime evaluate planning follow-on needs deterministically from typed proposals

Exit criteria:

- accepted control intents apply through deterministic applicators
- schedule mutation no longer depends mainly on the bespoke schedule marker path
- work follow-on logic is proposal-driven rather than purely hardcoded

### Slice 4: Specialist Proposal Adapters

Land the first half of [Specialist Output And Execution Transition](./specialist-output-and-execution-transition.md) fourth.

Why fourth:

- the runtime should already know how to store, validate, inspect, and apply typed proposals before specialist outputs depend on them
- this slice lets the current outreach reasoning seams keep working while their outputs become control-plane compatible

Exit criteria:

- discovery, planning, or review outputs can be wrapped into typed proposals after parsing
- belief-state, memory, and work-refresh implications are inspectable as applied or rejected proposal outcomes
- durable artifacts and typed proposals can coexist without the artifact schema being the only machine-readable meaning

### Slice 5: Agent Architecture Transition

Land [Agent Architecture Transition](./agent-architecture-transition.md) fifth.

Why fifth:

- once specialist outputs are proposal-compatible, the next risk is continuing to explain the runtime through the wrong top-level ontology
- architecture should be clarified before richer tooling is expanded, so the infra is built for the right long-term role model
- this is the right point to demote the fixed planning ladder conceptually without forcing a flag-day rewrite

Exit criteria:

- repo-facing docs and migration notes describe the runtime as `control brain + reasoning surfaces + compiled intents + late deterministic execution`
- discovery, strategy, and account planning are framed as planning work families rather than the permanent architecture
- live triage, promoted-thread reasoning, and observation are treated as first-class reasoning surfaces in the migration model

### Slice 6: Agent Infra And Tooling Expansion

Land [Agent Infra And Tooling Expansion](./agent-infra-and-tooling-expansion.md) sixth.

Why sixth:

- once the architecture is framed correctly, the next main bottleneck is under-informed reasoning rather than missing write seams
- richer bounded read access should arrive before the prompts are fully rewritten around broader proposal contracts
- this is the right point to standardize a shared read-side runtime seam instead of growing more bespoke agent glue

Exit criteria:

- planning and observation surfaces can see active work, schedules, and compact runtime-pressure state
- a shared bounded read-side runtime seam exists for richer agent inspection
- proposal lifecycle outcomes are visible back to future reasoning surfaces in prompt-safe form
- direct state mutation is still constrained to deterministic runtime-owned write paths

### Slice 7: Typed Proposal Contracts For Live Reasoning Surfaces

Land the second half of [Specialist Output And Execution Transition](./specialist-output-and-execution-transition.md) seventh.

Why seventh:

- prompt contract migration is easier after the runtime already trusts the proposal model and the agent role model is clearer
- execution-adjacent proposal kinds should only arrive after non-execution proposal kinds are stable
- richer read-side infra should exist before prompts are asked to emit broader typed proposal sets

Exit criteria:

- specialist surfaces no longer depend on one bespoke marker per control action
- promoted-thread review can emit typed next-move and learning proposals
- authorization and execution remain deterministic and late
- the runtime is clearly moving from a fixed specialist ladder toward bounded reasoning surfaces selected by work and context

### Slice 8: Cleanup And Cutover

Land [Cleanup And Cutover](./cleanup-and-cutover.md) eighth, after the proposal layer is stable.

Why last:

- shadow compilation and dual-write behavior are useful only during migration
- prompt and runtime cleanup should happen after the new path has already proven it can carry real behavior
- this is where the repo stops being "mid-migration" and becomes architecturally coherent again

Exit criteria:

- obsolete marker-first control paths are removed or clearly reduced to narrow fallback behavior
- fixed ladder helpers no longer act as primary routing authority
- prompts and validators describe the proposal-first architecture rather than the transitional contract set
- repo-facing docs describe discovery, strategy, and account planning as planning work families, not as the final permanent top-level runtime ontology

## Cross-Slice Validation

After each slice:

- run the smallest focused pytest coverage for the touched seam
- verify old sessions still behave acceptably when compatibility paths are still active
- verify compiled intents are inspectable and restart-safe where applicable

Before calling the series ready for broader rollout:

- run `python -m pytest tests/` if the tree is stable enough
- verify at least one operator-control path, one planning follow-on path, and one promoted-thread review path through the new proposal layer
- verify the remaining compatibility helpers are intentional and documented rather than accidental leftovers
- verify the final prompts and docs describe the runtime as `control brain + reasoning surfaces + compiled intents + late deterministic execution`, not as a rigid specialist ladder
