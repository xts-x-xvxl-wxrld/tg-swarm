# Freeform-To-Structured Compilation

## Purpose

Define the runtime design principle that lets agents think and express intent more freely without turning execution into an unconstrained sandbox.

This spec exists to resolve a recurring failure mode in the current runtime shape:

- if the system is too rigid, the LLM becomes a weak form filler
- if the system is too freeform, the runtime becomes unsafe, opaque, and hard to restart cleanly

The target is a middle path where reasoning is freeform, runtime intent is structured, and execution stays deterministic.

## Relationship To Existing Specs

This spec is a boundary and control-plane spec.

It should be read alongside:

- [Agentic Campaign Runtime](C:/Users/ravil/OneDrive/Desktop/tg-swarm/wiki/spec/agentic-campaign-runtime.md)
- [LLM-Led Outreach Runtime](C:/Users/ravil/OneDrive/Desktop/tg-swarm/wiki/spec/llm-led-outreach-runtime.md)
- [Campaign Operations Model](C:/Users/ravil/OneDrive/Desktop/tg-swarm/wiki/spec/campaign-operations-model.md)
- [App Runtime Architecture](C:/Users/ravil/OneDrive/Desktop/tg-swarm/wiki/spec/app-runtime-architecture.md)

Those specs say the product should be agentic, LLM-led, and campaign-centered.

This spec clarifies how that freedom should be expressed in the runtime without collapsing back into:

- rigid predefined action trees
- marker-driven workflow slots as the main expression mechanism
- unconstrained agent execution

## Problem Statement

The current runtime still carries a planning-era assumption:

- define a narrow set of actions or artifacts first
- ask the model to fill those slots
- validate the output
- move to the next predefined step

That pattern keeps the system legible, but it also creates a ceiling.

The agent becomes artificially weak because:

- it can only express intent through predefined work families
- it must compress reasoning too early into rigid output schemas
- it cannot easily introduce new campaign work types or operating rhythms
- the runtime treats unexpected but useful reasoning as malformed output instead of valuable control input

At the same time, removing structure entirely would create a different failure mode:

- state mutations would become hard to inspect
- execution would become hard to audit and replay
- safety and consent boundaries would blur
- restart-safe behavior would degrade

## Design Goal

The runtime should let agents reason and propose actions in a broad, natural, campaign-aware way.

It should not force all meaningful thought into a small set of fixed planning artifacts.

But it also should not let agents perform freeform external behavior without compilation into structured runtime intent.

The desired shape is:

1. freeform reasoning
2. structured intent compilation
3. deterministic authorization and execution

## Core Principle

Agents should be free in cognition.

The runtime should be strict in mutation.

That means:

- agents may reason in broad natural language and open-ended campaign concepts
- agents may propose new work, new priorities, new outreach angles, or new operating rhythms
- agents should not directly mutate durable state or perform external writes as a raw side effect of freeform output

Instead, the runtime should compile freeform expression into typed, inspectable, replayable runtime objects.

## What Should Be Freeform

Freeform expression is desirable in:

### 1. Campaign Interpretation

Agents should be able to say things like:

- this community needs warming before direct promotion
- this campaign is learning that technical proof matters more than urgency framing
- this operator message sounds like a launch delay, not a strategy revision
- this objection pattern deserves its own follow-up workstream

### 2. Commercial Reasoning

Agents should be able to infer:

- which opportunities are worth pursuing
- which threads are decaying
- which accounts or communities are fragile but high-yield
- which public moments deserve DM continuation
- which campaign learnings deserve durable memory

### 3. Work Discovery

Agents should be able to propose work that was not pre-modeled in the original workflow, such as:

- objection analysis
- trust-signal extraction
- outreach-angle experiments
- proactive group-opportunity review
- account-recovery work
- conversion acceleration review

### 4. Operator Control Interpretation

Agents should be able to interpret ordinary language as:

- launch guidance
- delay guidance
- tone or safeguard updates
- campaign posture changes
- pauses, exceptions, or conditional constraints

## What Should Become Structured

Freeform reasoning should not be the final runtime interface.

Before the runtime mutates state or acts externally, the system should compile that reasoning into one or more structured intent records.

Examples include:

- work-item proposals
- memory updates
- campaign-control updates
- posture changes
- schedule proposals
- execution requests
- review requests
- signal records
- qualification updates
- handoff decisions

The key rule is:

- the agent does not directly "do whatever it wants"
- the runtime receives a typed proposal of what the agent thinks should happen

## Compilation Layer

The compilation layer is the missing middle of the operating system.

Its job is to turn agent expression into durable intent that deterministic runtime code can safely process.

### Compilation Responsibilities

The compiler layer should:

- preserve the agent's intended meaning
- normalize that meaning into typed runtime objects
- retain grounding and evidence links
- retain confidence or ambiguity signals when useful
- separate proposal from authorization
- produce inspectable state transitions

### Minimum Compilation Contract

Each compiled intent should preserve at least:

- `kind`: what type of runtime intent this is
- `summary`: compact human-readable meaning
- `payload`: structured machine-usable data
- `grounding_refs`: what campaign evidence, assets, conversations, or operator turns support it
- `source_role`: which agent or runtime layer proposed it
- `confidence` or `ambiguity`: when uncertainty matters
- `safety_class`: whether this is read-only, state-mutating, execution-adjacent, or externally consequential

The exact Python classes and persistence layout are implementation details. The design requirement is that freeform thought becomes structured runtime intent before execution.

## Desired Runtime Boundary

The system should move away from:

- fixed artifact slot first
- freeform language only inside that slot
- hardcoded next-step ladder

toward:

- freeform interpretation first
- typed intent proposals second
- deterministic policy and execution last

In practical terms:

- an agent should not need a predeclared `strategy` or `account_planning` box before it can say something useful
- the runtime should be able to accept richer kinds of proposed work and control actions than the current planning ladder
- deterministic seams should decide whether and how those compiled intents become durable state or live actions

## Final Architectural Implication

The final runtime should not be organized primarily as one orchestrator plus a small permanent ladder of planning specialists.

Instead, it should be organized as:

- one operator-facing control interpreter
- several bounded reasoning surfaces
- one shared compiled-intent boundary
- one late deterministic authorization and execution boundary

Some current specialist roles may remain useful, but they should be understood as work families or reasoning surfaces, not as the permanent control-plane ontology of the product.

That means:

- `discovery`, `strategy`, and `account_planning` may continue to exist
- they should not be the only first-class types of meaningful reasoning the runtime can express
- they should not imply a hardcoded next-step chain by default
- they should not be the only route by which the runtime can propose refreshes, experiments, memory updates, posture changes, or outreach actions

The control plane should remain open enough to absorb future reasoning surfaces such as:

- objection analysis
- proactive group-opportunity review
- account-recovery planning
- conversion acceleration review
- campaign-level opportunity prioritization

## Freeform Does Not Mean Unbounded Execution

This spec does not advocate an unconstrained playground where agents can act externally without structure.

That is explicitly not the target.

The system should not allow:

- raw freeform external messaging without structured execution requests
- raw prompt text to directly mutate campaign state without compilation
- freeform agent decisions to bypass pause, consent, approval, readiness, or policy seams
- hidden reasoning to become the only record of why the runtime changed state

Freeform is for cognition and proposal generation.

Structured compilation is for runtime control.

Deterministic code remains responsible for final authorization and execution.

## Open Ontology Principle

The runtime should not lock the control plane into a tiny permanent set of work families.

It should remain possible for the system to introduce new first-class operating concepts over time.

That means:

- work types should be extensible
- operator-control categories should be extensible
- review and observation outputs should not be permanently limited to a tiny enum set
- schedule and follow-up logic should not assume only one ladder of campaign progress

Open ontology does not mean untyped ontology.

It means the set of typed concepts should be allowed to grow from runtime needs instead of being frozen too early.

## Human Legibility Principle

Structured compilation is not only for machines.

It should improve operator trust and developer debuggability.

The operator should be able to inspect:

- what the system thinks is happening
- what it proposes to do next
- what changed in durable campaign state
- why a live action was authorized or blocked

Developers should be able to inspect:

- what freeform reasoning got compiled into
- what deterministic checks accepted or rejected
- which proposals never became execution

## Runtime Implications

If the runtime follows this spec, several implementation consequences follow:

### 1. Prompts Should Optimize For Richer Intent Expression

Prompts should not only ask for final ladder-shaped artifacts.

They should also support:

- broader control interpretation
- richer work proposals
- explicit ambiguity surfacing
- compact rationale attached to structured proposals

### 2. Runtime Contracts Should Prefer Typed Intents Over Marker-Only Artifact Parsing

Marker-based JSON blocks can remain as a transition tool, but they should not be the long-term primary control interface.

The runtime should move toward:

- typed proposal contracts
- typed control intents
- typed memory mutations
- typed execution requests

Durable artifacts may still exist when they are genuinely useful for operator review or downstream context, but they should no longer be the only machine-readable meaning the runtime can act on.

### 3. Work And Schedule Systems Should Become More Extensible

The work-item and schedule layers should be able to absorb new runtime work families without requiring a fundamental redesign each time.

### 4. Policy Should Stay Late In The Flow

Policy should evaluate compiled intents near authorization and execution time.

It should not over-own the interpretation layer or become the place where the system's commercial reasoning is encoded.

## Non-Goals

This spec does not require:

- unconstrained agent shell access
- autonomous external writes without policy
- removal of deterministic execution seams
- removal of human-readable runtime summaries
- immediate replacement of every existing JSON artifact contract

This spec also does not say that every intermediate thought must be persisted.

Freeform reasoning may remain transient.

What must become durable is the compiled intent that the runtime relies on for state mutation, authorization, scheduling, or execution.

## Success Criteria

This direction is correct when:

1. Agents can express useful campaign reasoning without first squeezing it into a tiny fixed workflow ladder.
2. The runtime can accept new kinds of work and control proposals without treating them as malformed by default.
3. Freeform agent reasoning never directly bypasses deterministic safety, consent, readiness, or execution seams.
4. Operators and developers can inspect what was proposed, what was accepted, and what was blocked.
5. The runtime becomes more LLM-led in interpretation and prioritization without becoming less disciplined operationally.

## Open Questions

- What is the smallest typed intent envelope that can replace the current marker-first artifact pattern gradually?
- Which current runtime outputs should be converted into compiled-intent contracts first?
- How much of the existing work-item model can be generalized before compatibility pressure becomes too high?
- Which proposals should remain advisory only versus directly eligible for authorization and execution?
