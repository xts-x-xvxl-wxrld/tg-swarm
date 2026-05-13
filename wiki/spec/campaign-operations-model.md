# Campaign Operations Model

## Purpose

Define the long-lived operating model for agentic Telegram marketing campaigns.

This document describes how campaign work should be organized, delegated, remembered, reviewed, and adjusted over time. It replaces the idea of a purely consecutive workflow with a campaign operations system.

## Design Goal

The system should behave less like a one-pass workflow runner and more like a compact marketing organization.

It should:

- let the operator act like a manager or team lead
- let the orchestrator act like a campaign manager
- let specialist agents act like tactical workers with bounded autonomy
- preserve campaign knowledge beyond one session
- support recurring work, review cadences, and strategy adjustment
- keep risky execution legible and approval-aware

## Why This Model Is Needed

The current discovery -> strategy -> account-planning sequence is useful as an initial planning path, but it is too narrow to describe real campaign behavior.

Real campaign operations are not strictly consecutive:

- goals evolve
- positioning changes
- new communities appear over time
- old assumptions get invalidated
- research and execution readiness progress at different speeds
- strategy must be refreshed as signals accumulate

The runtime should therefore be built around ongoing operations, not just stage progression.

## Architectural Position

This model sits on top of the Telegram-native runtime foundation.

It should align with:

- the Telegram transport and session runtime
- orchestrator-led control boundaries
- reusable Telegram capability interfaces
- structured state for continuity
- flexible campaign memory for evolving knowledge

This spec defines the product operating shape. Implementation plans should make the current code match this shape over time.

## Core Operating Model

The system should be treated as a small campaign organization.

### Operator

The operator is the manager or team lead.

The operator should:

- set campaign direction
- provide constraints and priorities
- review important decisions
- approve risky execution when required
- redirect strategy when goals change

The operator should not need to manually manage every tactical substep.

### Orchestrator

The orchestrator is the campaign manager.

The orchestrator should:

- interpret operator intent
- maintain campaign continuity
- decide what work should happen now versus later
- assign goals to specialist agents
- schedule recurring review, discovery, and maintenance work
- resolve cross-agent tradeoffs
- escalate consequential decisions back to the operator

The orchestrator should decide `what` and `why`, not micromanage `how`.

### Specialist Agents

Specialist agents are tactical workers with bounded autonomy.

Each specialist should:

- own a clear domain of responsibility
- make tactical decisions inside that domain
- maintain its own working memory
- update shared campaign memory when findings become durable
- escalate ambiguity, cross-domain conflict, or risky actions

Specialists should decide `how` to achieve assigned goals within their scope.

## Responsibility Split

The system should preserve this core split:

- operator: direction, constraints, approval, oversight
- orchestrator: campaign-level coordination and strategic prioritization
- specialists: tactical execution of their domain work

This split is a design invariant, not a prompt preference.

## Campaign As The Durable Unit

The durable object should be the campaign, not just the current chat session.

A campaign should be a long-lived operating workspace that can survive:

- multiple Telegram sessions
- evolving goals
- periodic reviews
- future execution loops

Sessions remain important, but they are the conversational interface into campaign work rather than the full container of truth.

## Session Relationship

Sessions should become campaign-attached work threads.

A session should:

- attach to an active or newly created campaign
- provide conversational continuity
- capture turn history and immediate context
- link the orchestrator to shared campaign memory

A session is not the campaign itself.

Scheduled and background campaign work should not require an active session.

Sessions are the operator-facing interaction surface into campaign work, not the container that makes campaign work exist.

## Operational State Model

There should be one primary operational state model for campaign work.

That model should be campaign-centered and asynchronous.

Its durable state should live in:

- campaign metadata
- shared campaign memory
- agent-local working memory
- work items
- schedules
- approvals tied to consequential execution

Sessions should attach operator conversation to that model, but should not become a second competing state machine for operations.

`workflow_stage` may still exist temporarily as a session-local compatibility aid during migration, but it should not become the long-lived source of truth for campaign state.

`setup`, `operating`, and `review` can still be useful descriptive postures for summaries or operator UX, but they should not become a second authoritative operational state model that competes with work items, schedules, and memory.

## Campaign Memory Model

Campaign memory should be split into two layers:

### Shared Campaign Memory

Shared campaign memory is the canonical cross-agent view of the campaign.

It should hold:

- goals
- positioning
- approved personas
- community dossiers
- major decisions
- current priorities
- experiments
- execution posture
- next actions

This memory should be durable, readable by humans, and reusable across sessions.

### Agent Working Memory

Each specialist agent should have its own working memory.

This memory should hold tactical state such as:

- discovery search trails, unresolved leads, and validation notes
- strategy hypotheses, audience frames, and messaging alternatives
- execution readiness notes, blockers, pacing concerns, and rollout ideas

Agent working memory should support tactical autonomy without forcing every intermediate thought into shared canonical memory.

## Canonical Memory Principle

Not all memory should be treated equally.

The system should distinguish:

- canonical campaign memory
- agent-local working memory
- raw runtime logs

Canonical memory is what the campaign currently believes and intends.

Agent-local memory is how individual specialists think and work.

Raw runtime logs are for audit and debugging, not strategic truth.

## Work Item Model

The primary orchestration primitive should be the work item rather than the next sequential stage.

A work item is a bounded unit of responsibility assigned to a specialist or to the orchestrator itself.

Work items should express:

- the goal to achieve
- relevant constraints
- owning role
- priority
- due time or review cadence
- related campaign memory
- status
- result or escalation outcome

The orchestrator should assign outcomes, not exhaustive step-by-step instructions.

## Scheduling Model

The system should support recurring campaign operations through scheduling.

Scheduling should be a first-class part of the campaign model, not an ad hoc add-on.

Examples include:

- periodic discovery refresh
- community revalidation
- weekly strategy review
- experiment follow-up
- execution readiness review
- stale-memory cleanup

Schedules should normally create or refresh work items rather than directly triggering risky execution.

## Campaign Posture Views

The campaign may expose a few high-level postures for operator understanding.

These are descriptive views, not the primary operational state machine.

### 1. Setup Mode

This is the guided campaign initialization path.

Setup mode should establish:

- campaign goal
- product context
- audience
- positioning direction
- constraints
- initial operating cadence
- initial communities or research direction

This mode may feel more sequential because it creates the starting campaign frame.

### 2. Operating Mode

This is the main long-lived mode.

In operating mode, the orchestrator should:

- manage ongoing work
- refresh priorities
- create and resolve work items
- schedule recurring reviews
- adapt strategy as new information arrives

### 3. Review Mode

This is the synthesis and adjustment mode.

Review mode should:

- summarize what changed
- surface what was learned
- re-rank priorities
- recommend strategy changes
- identify blocked work and next actions

### 4. Paused Or Archived Status

Paused and archived should remain explicit campaign statuses because they affect whether campaign work should continue at all.

## Consecutive Workflow Position

The old linear flow should not disappear entirely, but it should be reframed.

Discovery, strategy, and account planning remain useful specialist emphases.

They should no longer define the entire operating architecture.

Instead, they should become common work item families inside a broader campaign operations system.

## Autonomy Boundaries

Specialists should have meaningful agency, but not unlimited authority.

### Specialists Should Be Free To

- choose tactical substeps inside their domain
- update their own working memory
- update shared campaign memory when findings become durable
- propose changes in campaign direction
- escalate when they detect uncertainty or cross-domain impact

### Specialists Should Not Unilaterally Own

- global campaign direction
- cross-campaign policy
- operator approval semantics
- high-risk execution requiring explicit oversight

This keeps the system decentralized enough to be useful without losing control.

## Escalation Model

Escalation should happen when:

- a specialist encounters ambiguity it cannot responsibly resolve
- a tactical decision creates cross-domain consequences
- campaign direction appears inconsistent with new evidence
- the requested action is risky, sensitive, or irreversible

Escalation should return to the orchestrator first unless direct operator approval is clearly required.

## Approval Model

Normal planning, research, and memory maintenance should not require heavy approval gates.

Approvals should be focused on consequential actions such as:

- joining communities
- sending outreach
- posting promotional content
- messaging members
- other actions that materially affect account safety or external perception

This keeps the planning system fluid while preserving human oversight for risky execution.

## Campaign Memory And Scheduling Relationship

Scheduling should not operate independently of memory.

Scheduled work should:

- read current campaign memory
- create or refresh work items using that memory
- write back outcomes, observations, and adjustments

This makes the campaign state cumulative instead of repetitive.

## Runtime Invariants

The operational model should preserve these invariants:

1. Every active session is attached to a campaign.
2. Every work item, schedule, approval, and execution record is attached to a campaign.
3. Every active campaign has canonical shared memory.
4. Specialists may act autonomously inside scope, but must escalate beyond it.
5. The orchestrator owns campaign-level prioritization and scheduling.
6. Work items are the normal vehicle for delegated operational work.
7. Schedules create ongoing work; they do not bypass control boundaries.
8. Risky execution remains legible and approval-aware.
9. Campaign truth should not live only in raw chat history.

## Relationship To Existing Marketing Roles

The current role emphases remain valid:

- Discovery Agent
- Strategy Agent
- Account Manager Agent

But they should be understood as tactical domains in an operating system, not as one-shot steps in a pipeline.

Additional specialists may be added later if the campaign organization expands, but the manager-versus-worker responsibility split should remain stable.

## Success Criteria

This model is correct when:

1. A campaign can continue across multiple sessions without losing strategic continuity.
2. The orchestrator can coordinate ongoing work without prescribing every tactical step.
3. Specialists can adapt their own tactics while staying aligned to shared campaign goals.
4. The system can support recurring discovery, review, and adjustment work over time.
5. Campaign memory grows into a useful operating asset instead of a pile of disconnected artifacts.
6. Risky external actions remain visible and reviewable.

## Open Questions

- How explicit should agent-local memory boundaries be in the first implementation?
- Which scheduled tasks should be enabled first in MVP versus later phases?
- How should the orchestrator decide when a campaign shifts from setup mode into operating mode?
- What is the smallest useful work-item schema that still preserves autonomy and scheduling?
