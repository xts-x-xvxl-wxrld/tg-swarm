# Session Lifecycle

## Purpose

Define how operator sessions begin, evolve, pause, resume, and complete in the Telegram-native app.

This document focuses on continuity, state ownership, and approval handling across multi-turn work.

## Design Goal

The system should treat a session as the durable unit of operator work.

A session should let the app:

- understand what the operator is trying to accomplish
- remember what has already happened
- track what is pending
- preserve reusable outputs
- continue work safely across multiple Telegram messages

## Session Definition

A session is an operator-driven thread of work, initially started through `/new`, that captures intent, context, work state, approvals, and outputs until the work is complete or intentionally paused.

## Session Stages

### 1. Session Creation

Entry conditions:

- operator sends `/new`
- app creates a fresh work context

At creation time, the system should initialize:

- session identifier
- operator identifier
- creation timestamp
- empty working context
- initial status

### 2. Intent Capture

After creation, the operator sends one or more freeform messages describing the goal.

The system should capture:

- stated objective
- important constraints
- target audience or campaign context when relevant
- unresolved ambiguities

The orchestrator should normalize this into a usable task frame.

### 3. Active Work

During active work, the orchestrator and specialists:

- analyze the request
- produce intermediate findings
- generate structured records
- identify approval points
- update state as work progresses

This is the default operating state.

### 4. Pending Approval

Some actions or decisions should pause active work and await operator input.

Examples:

- approving a shortlist of communities
- approving a strategy playbook
- approving account assignment or join actions

In this state, the session should preserve:

- the pending approval request
- the exact decision needed
- the relevant context for resumption

### 5. Resumed Work

After an operator responds, the session should resume without rebuilding context from scratch.

The resumed workflow should:

- surface any pending approval context back to the orchestrator
- let the orchestrator interpret whether the new message is an approval response, clarification, or changed request
- update status
- continue the appropriate workstream

### 6. Completed Or Archived

A session may eventually:

- complete successfully
- end with operator cancellation
- pause indefinitely
- be archived for later reference

Completed sessions should still remain queryable for historical context and data reuse.

## Session State Categories

Each session should eventually be able to hold at least:

- operator intent
- current workflow stage
- relevant campaign context
- discovered communities
- strategy outputs
- account planning outputs
- approvals requested and resolved
- audit events
- final summaries and artifacts

## Session Ownership Principles

### Orchestrator Owns Session Coordination

- The orchestrator should be the primary interpreter of session state.
- Specialists contribute outputs, but the orchestrator maintains continuity.

### Structured State Beats Chat Memory

- Important workflow data should be stored in structured form.
- The system should not rely only on conversational recall.

### Pending Decisions Must Be Explicit

- Approval waits should be first-class state, not implicit pauses.
- A resumed session should know exactly what it was waiting on.
- The runtime should preserve this state without taking over interpretation of the operator reply.

## Telegram Interaction Model

The Telegram operator experience should stay intentionally simple.

Expected interaction pattern:

1. Operator starts with `/new`.
2. Operator sends goal in natural language.
3. App responds with questions, findings, summaries, or approvals.
4. Operator continues the same work through follow-up messages.

The session layer should make this feel coherent despite multi-agent internals.
Clarifying questions should flow naturally through the orchestrator rather than through a separate runtime-only question system.

## Session Data Requirements

The exact persistence model is still open, but session storage likely needs:

- canonical session record
- message history or normalized event history
- current stage/status
- pending approval record if present
- links to structured workflow entities

## Failure And Recovery Considerations

The session model should eventually account for:

- Telegram delivery retries or duplicate updates
- tool failures during active work
- partial completion of a multi-step workflow
- operator silence during approval waits

Recovery behavior is not yet fully designed, but the session layer should make it possible.

## Relationship To Workflow Entities

Sessions are not the same thing as campaigns or communities.

A session is the operator work container.

It may create, update, or reference:

- campaigns
- communities
- community profiles
- accounts
- assignments
- playbooks

This distinction should stay clear in the implementation.

## MVP Bias

For MVP, the lifecycle should optimize for:

- straightforward session start
- clear active versus pending-approval state
- resumable work
- enough persistence to avoid losing reasoning context

It should avoid prematurely complex workflow state machines.

## Success Criteria

This lifecycle is successful when:

1. An operator can start and continue work through Telegram without repeating context constantly.
2. The system can pause for approvals and resume cleanly.
3. Important outputs persist outside raw chat text.
4. The orchestrator can maintain continuity over multi-turn workflows.

## Open Questions

- What should happen if the operator sends a new request while an approval is pending?
- Should one operator have one active session at a time or multiple concurrent sessions?
- How much raw Telegram message history should be persisted versus summarized?
- What session timeout or archival policy should exist for inactive work?
