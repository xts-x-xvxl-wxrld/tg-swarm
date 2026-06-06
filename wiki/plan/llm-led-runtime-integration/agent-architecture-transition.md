# Agent Architecture Transition

## Goal

Transition the runtime from a small fixed planning-specialist ladder toward the intended final architecture:

- one operator-facing control brain
- several bounded reasoning surfaces
- one shared compiled-intent proposal boundary
- one late deterministic execution boundary

This slice is about architectural role shape, not about widening direct write power.

## Why This Needs Its Own Slice

The current repo still carries two competing mental models at once:

- the old planning-era model of `discovery -> strategy -> account_planning`
- the newer LLM-led runtime model of proposal-driven work selection, live triage, promoted-thread reasoning, and campaign-level observation

The specs now clearly prefer the second model.

Without a dedicated architecture slice, the repo risks improving prompts and tooling while still explaining itself through the older ladder.

That would leave:

- prompts describing the wrong top-level ontology
- routing logic that still overfits a fixed specialist roster
- new work families feeling like exceptions instead of first-class runtime concepts

## Target Architecture

### 1. Operator Control Brain

This is the main interpreter of:

- operator freeform steering
- campaign posture changes
- priority shifts
- bounded work selection
- ambiguity resolution

It should decide which reasoning surface to use next, not assume that planning always advances through one fixed ladder.

### 2. Campaign Planning Surfaces

Planning should remain a real capability, but it should stop being the only architecture.

Examples of planning work families:

- discovery
- strategy
- account planning
- objection analysis
- outreach-angle experiments
- account-recovery planning
- conversion acceleration review

These are bounded work families, not the permanent top-level ontology of the runtime.

### 3. Cheap Inbound Triage Surface

This surface handles:

- broad low-cost inbound reading
- lightweight interest and urgency interpretation
- promotion decisions for deeper review

It is part of the final runtime architecture, not an add-on helper.

### 4. Promoted-Thread Reasoning Surface

This surface handles:

- deeper commercial interpretation
- belief-state updates
- next-move selection
- compact campaign learnings

It should remain clearly separated from execution authorization and dispatch.

### 5. Observation / Opportunity Surface

This surface handles:

- campaign-level pressure detection
- plan refresh pressure
- opportunity summaries
- prioritization across signals, work, and conversations

It should be treated as a first-class reasoning surface rather than a side workflow.

### 6. Shared Proposal Boundary

All reasoning surfaces should express machine-usable meaning through the same conceptual boundary:

- operator-facing prose when needed
- durable artifact when useful
- zero or more typed proposals

The runtime should not require one bespoke top-level contract per role.

### 7. Deterministic Execution Boundary

Policy, consent, readiness, queueing, retries, and external writes should remain runtime-owned and late in the flow.

This is where discipline lives.

## Primary Migration Surfaces

### Orchestrator Routing And Explanation

Current pressure:

- the orchestrator still explains and routes too much of the runtime through the old planning roster

Migration direction:

- make work-family and runtime-pressure selection the primary routing model
- keep `workflow_stage` and the current planning specialists as compatibility aids only
- update prompts and docs so they describe reasoning surfaces and work families, not just a fixed ladder

Candidate surfaces:

- `prompts/orchestrator.md`
- `prompts/shared_runtime.md`
- `telegram_app/orchestrator/orchestrator.py`

### Planning Specialist Reframing

Current pressure:

- discovery, strategy, and account planning still look like the architecture itself

Migration direction:

- preserve those surfaces where they are useful
- describe them as planning work-family surfaces
- stop implying that one must always lead directly into the next

Candidate surfaces:

- `agents/discovery/agent.py`
- `agents/strategy/agent.py`
- `agents/account_manager/agent.py`
- planning prompts under `prompts/`

### Live Reasoning Surface Promotion

Current pressure:

- live triage and promoted-thread reasoning already behave more like the target architecture than the planning ladder does

Migration direction:

- make them first-class in repo-facing architecture language
- align orchestrator, docs, and future routing with that reality

Candidate surfaces:

- `telegram_app/engagement_triage/`
- `telegram_app/engagement_brain/`
- `agents/observation/agent.py`

## Recommended Transition Strategy

### Step 1: Rewrite The Runtime Vocabulary

First update the repo's architectural language:

- "specialists" becomes a compatibility term, not the primary architecture term
- "planning work families" becomes the right frame for discovery, strategy, and account planning
- "reasoning surfaces" becomes the cross-runtime frame that includes planning, triage, promoted-thread review, and observation

This should happen in specs, plans, prompts, and code-index notes before large code deletions.

### Step 2: Make Routing Prefer Work And Pressure, Not Ladder Expectations

Once the vocabulary is aligned:

- keep selecting active work first
- reduce compatibility routing authority further
- avoid adding new code that assumes a fixed next planning family by default

### Step 3: Let New Work Families Fit Naturally

After the architecture is reframed:

- introduce new planning or review work families without treating them as exceptions
- keep the work-item and proposal system as the extensibility seam

### Step 4: Retire Roster-First Explanations

Once docs, prompts, and routing are aligned:

- remove or demote repo-facing language that still presents the old ladder as the architecture
- keep narrow compatibility references only where old sessions or contracts still require them

## Relationship To The Infra Slice

This architecture slice and the infra slice are related but different.

This slice answers:

- what the runtime roles should be
- how the repo should explain those roles
- how routing should think about them

The infra slice answers:

- what those reasoning surfaces can see
- what bounded tools they can use
- how proposal outcomes become inspectable runtime state

Architecture should land before or alongside infra expansion so new tooling is built for the right model.

## Non-Goals

This slice does not require:

- deleting discovery, strategy, or account planning immediately
- replacing every prompt contract in one change
- changing deterministic execution policy
- widening direct write access for agents

## Acceptance Criteria

This slice is complete when:

- repo-facing docs describe the runtime primarily as `control brain + reasoning surfaces + compiled intents + late deterministic execution`
- discovery, strategy, and account planning are described as bounded planning work families rather than the permanent top-level architecture
- orchestrator-facing guidance prefers work-family and runtime-pressure selection over fixed ladder assumptions
- live triage, promoted-thread reasoning, and observation are treated as first-class reasoning surfaces in architecture docs and migration plans
- new work families can be added conceptually without forcing a redesign of the agent model
