# Managed Account Operations

## Purpose

Define the operational loop for using managed MTProto accounts in a way that stays aligned with the platform's agentic-first design.

This document is a companion to:

- [Campaign Operations Model](C:/Users/ravil/OneDrive/Desktop/tg-swarm/wiki/spec/campaign-operations-model.md)
- [Telegram Capability Layer](C:/Users/ravil/OneDrive/Desktop/tg-swarm/wiki/spec/telegram-capability-layer.md)
- [Account Capability](C:/Users/ravil/OneDrive/Desktop/tg-swarm/wiki/spec/account-capability.md)
- [Approval And Guardrails](C:/Users/ravil/OneDrive/Desktop/tg-swarm/wiki/spec/approval-and-guardrails.md)

The account capability spec defines the action surface. This spec defines the operational process that should govern how those actions are prepared, executed, observed, and adapted over time.

## Design Goal

Managed-account work should behave like an agentic operating loop, not a fire-and-forget automation queue.

It should:

- preserve operator direction and approval boundaries
- let the orchestrator act like a campaign manager
- let specialists make tactical choices within scope
- keep risky external actions legible
- capture outcomes back into campaign memory
- improve future decisions through observed feedback

## Agentic-First Principles

The managed-account operational model should follow the repo's existing autonomy model rather than replacing it with rigid scripts.

### Operator Owns Direction

The operator should continue to own:

- campaign goals
- strategic constraints
- tolerance for risk
- approval of consequential external actions when required

The operator is not expected to micromanage every tactical action.

### Orchestrator Owns Coordination

The orchestrator should:

- decide what kind of account work is needed now
- decide whether the work should happen immediately, later, or after review
- choose whether to answer directly, create a work item, or delegate to a specialist
- keep campaign continuity across sessions, schedules, and outcomes

The orchestrator decides `what` and `why`, not every tiny `how`.

### Specialists Own Tactical Reasoning

Specialists should:

- reason within their domain
- choose tactical substeps inside scope
- prepare execution recommendations with real Telegram context
- interpret observed outcomes and recommend adjustments
- escalate when the action crosses risk, policy, or scope boundaries

Specialists should not become dumb wrappers around individual MTProto calls.

### Capability Layer Owns Execution Mechanics

The capability layer should:

- expose stable account-domain actions
- normalize execution results
- preserve audit visibility
- classify retry, cooldown, and rate-limit outcomes
- avoid leaking Telethon-specific details upward into agent reasoning

## Core Operational Loop

Managed-account work should flow through four phases:

1. `prepare`
2. `execute`
3. `observe`
4. `adapt`

This loop should be the normal shape for account-facing operations whether triggered by an operator turn or by a schedule-backed work item.

## 1. Prepare

Prepare is where the runtime decides whether an account action should happen at all, and if so, under what conditions.

### Prepare Responsibilities

- understand the campaign objective behind the action
- gather the minimum live context needed to act responsibly
- check account readiness and account health
- check peer or community state
- choose the right account
- decide whether approval is required
- shape the action request so execution is explicit and auditable

### Preflight Checks

Prepare should include preflight checks such as:

- account exists and is authenticated
- account health is acceptable
- cooldown or flood-wait windows are respected
- membership state supports the intended action
- the target peer is resolvable and reachable
- the target chat type matches the intended action
- the campaign memory does not already show a conflicting recent action
- the action fits the current work-item goal rather than being an ungrounded impulse

Preflight should prevent avoidable execution mistakes before Telegram is touched.

### Account Selection

Account selection should be explicit rather than accidental.

Selection should consider:

- account tier and warm-up state
- health and recent rate-limit history
- recent action load
- community or conversation history
- role suitability for the current campaign posture
- any operator or campaign constraints

The goal is not just "an available account." The goal is "the right account for this action now."

### Approval Decision

Prepare should also decide whether the action:

- can execute directly
- should be proposed for operator approval
- should be delayed or converted into a work item
- should be rejected as inappropriate or unsupported

This keeps risky execution visible before it becomes external behavior.

## 2. Execute

Execute is where the runtime performs the chosen Telegram action through one consistent audited wrapper.

### Execute Responsibilities

- call the capability surface with normalized inputs
- attach approval context when required
- record the attempt as an auditable event
- classify success, retriable failure, rate-limit, and hard failure outcomes
- update immediate account state needed for cooldowns or health tracking

### One Audited Wrapper

Visible account actions should go through one shared execution pattern rather than each feature inventing its own behavior.

That wrapper should cover:

- action type classification
- structured audit event creation
- retry and flood-wait handling
- normalized error shape
- cooldown and health updates
- consistent result payloads for downstream memory and UX

Examples of actions that should use this path:

- send a message
- send a reply
- set typing or other presence signals
- mark a dialog or message as read
- send or clear a reaction
- archive or leave a dialog

### Execution Boundary Principle

Execution should stay thin.

The runtime should not bury strategic reasoning inside the execution layer. By the time an action reaches execute, the system should already know:

- why it is acting
- which account is acting
- which target is involved
- whether approval exists
- what outcome categories matter

## 3. Observe

Observe is where the runtime turns raw Telegram outcomes into operational signals the system can learn from.

### Observe Responsibilities

- capture execution outcomes
- ingest replies or follow-up messages when relevant
- detect moderation or access friction
- detect cooldown and rate-limit signals
- distinguish silent success from meaningful engagement
- preserve evidence for later review

### Signals Worth Observing

The runtime should be able to observe:

- success or failure of the attempted action
- flood wait and other pacing constraints
- permission or access errors
- moderation signals
- replies, reactions, or silence after a send
- membership changes or removals
- conversation-state changes after read or presence actions

Observation is not only for debugging. It is how the campaign learns what happened in the real Telegram environment.

### Observation Scope

Not every action needs a heavyweight observation loop.

For example:

- a typing action may only need audit plus cooldown tracking
- a message send may need follow-up outcome tracking and reply ingestion
- a join may need moderation and visibility follow-up

The depth of observation should match the operational significance of the action.

## 4. Adapt

Adapt is where observed signals change future behavior.

### Adapt Responsibilities

- update campaign memory with durable outcomes
- update account state, cooldowns, and health
- update work-item status or next actions
- recommend retries, pauses, escalation, or strategy changes
- keep the operator informed when outcomes materially change campaign posture

### Memory And State Updates

Adapt should write to the right state layer:

- audit logs for raw execution trace
- account registry for health and cooldown changes
- campaign memory for durable operational learning
- work items for status, blockers, and next-step recommendations

This separation matters. Raw logs are not strategy, and strategy is not just a cooldown counter.

### Adaptation Outcomes

Adapt may result in:

- continue with the next planned action
- schedule a follow-up review
- pause an account or community path
- escalate to the operator
- revise strategy or assignment assumptions
- close or refresh a work item

## Operational Invariants

The managed-account loop should preserve these invariants:

1. External actions remain legible and approval-aware.
2. Specialists retain tactical autonomy inside scope.
3. The orchestrator remains the campaign-level coordinator.
4. Campaign memory accumulates durable lessons from live Telegram outcomes.
5. Raw execution does not silently bypass planning, memory, or review.
6. The capability layer stays broad, but execution still follows a consistent operational process.

## Work Item Alignment

This loop should fit naturally into the campaign work-item model.

Examples:

- discovery-related account checks may mostly run through `prepare` and `observe`
- outbound engagement readiness may require deep `prepare` before any `execute`
- scheduled review work may emphasize `observe` and `adapt` without performing new visible writes

The loop should not force every work item to perform every phase equally. It should provide the shared operating grammar.

## Schedule Alignment

Schedules should generally be strongest at:

- refreshing preflight state
- collecting observations
- updating campaign memory
- recommending follow-up actions

Schedules should not become a backdoor for unreviewed risky execution.

This keeps the current runtime direction intact: recurring work is valuable, but consequential external action should remain legible and approval-aware.

## Relationship To Capability Families

This operational loop should apply across the account capability families:

- `presence`
- `messaging`
- `engagement`
- `dialog`
- `identity`
- `social`

Different families will have different risk and observation depth, but they should share the same operational shape.

## Rollout Guidance

### First Practical Cut

The earliest implementation should prioritize:

- strong `prepare` checks
- one shared `execute` wrapper
- basic `observe` result capture
- minimal but durable `adapt` state updates

This is more important than shipping a large number of raw account actions quickly.

### Why This Order Matters

If the runtime adds many account actions before it has a stable operational loop, the result will be:

- inconsistent safety behavior
- fragmented audit trails
- poor account-state learning
- weak campaign memory continuity

The process shape is part of the product, not incidental plumbing.

## Non-Goals

This spec does not:

- define the exact Python classes or file layout for every helper
- mandate a fully automatic outreach engine
- remove the orchestrator or specialist autonomy model
- turn the runtime into a generic task queue disconnected from campaign reasoning

## Success Criteria

This spec is successful when:

1. Managed-account work follows one coherent operational loop.
2. The loop aligns with operator -> orchestrator -> specialist responsibility boundaries.
3. Live Telegram outcomes feed back into campaign memory and future decisions.
4. Risky external actions stay visible rather than disappearing into library calls.
5. The runtime becomes more operationally capable without becoming less agentic.

## Open Questions

- Which actions should be allowed to execute directly after `prepare`, and which should always stop for approval?
- What is the smallest useful observation model for presence and reaction actions?
- How should campaign memory summarize operational outcomes without turning raw logs into prompt bloat?
- Which parts of `adapt` should happen immediately versus through scheduled review work?
