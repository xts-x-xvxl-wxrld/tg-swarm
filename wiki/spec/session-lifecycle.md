# Session Lifecycle

## Purpose

Define how operator sessions begin, evolve, pause, resume, and complete in the Telegram-native app.

This document focuses on continuity, state ownership, and approval handling across multi-turn work. It should be read alongside [Campaign Operations Model](C:/Users/ravil/OneDrive/Desktop/tg-swarm/wiki/spec/campaign-operations-model.md), which defines the longer-lived campaign object that sessions attach to.

## Design Goal

The system should treat a session as the conversational unit of operator work, not the full durable campaign object.

A session should let the app:

- understand what the operator is trying to accomplish
- remember what has already happened
- track what is pending
- attach the conversation to reusable campaign memory
- continue work safely across multiple Telegram messages

## Session Definition

A session is an operator-driven thread of work, initially started through `/new`, that captures intent, context, work state, approvals, and immediate conversational history while attaching the operator to a longer-lived campaign workspace.

## Relationship To Campaigns

Sessions are not the same thing as campaigns.

A campaign is the durable operating workspace.

A session is the conversational thread through which the operator interacts with that workspace.

One session should typically attach to one active campaign at a time. A campaign may be revisited across multiple sessions over time.

Scheduled and background campaign work may continue without any active session.

Sessions are therefore an interaction layer over campaign operations, not the container that makes campaign work exist.

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
- campaign linkage or campaign creation intent
- initial status

### 2. Intent Capture

After creation, the operator sends one or more freeform messages describing the goal.

The system should capture:

- stated objective
- important constraints
- target audience or campaign context when relevant
- unresolved ambiguities

The orchestrator should normalize this into a usable task frame and either attach the session to an existing campaign or create a new campaign workspace when appropriate.

### 3. Active Work

During active work, the orchestrator and specialists:

- analyze the request
- read and update campaign memory
- produce intermediate findings
- generate work items, memory updates, and structured records
- identify approval points
- update state as work progresses

This is the default operating state.

### 4. Pending Approval

Some actions or decisions should pause active work and await operator input.

Examples:

- approving joins into communities
- approving outreach or posting actions
- approving other sensitive or consequential external writes

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
- continue the appropriate campaign workstream

### 6. Completed Or Archived

A session may eventually:

- complete successfully
- end with operator cancellation
- pause indefinitely
- be archived for later reference

Completed sessions should still remain queryable for historical context and data reuse.

Campaigns may continue operating beyond any one session through scheduled work, later sessions, or orchestrator-managed review cycles.

## Session State Categories

Each session should eventually be able to hold at least:

- operator intent
- current conversational state
- campaign identifier and campaign workspace linkage
- relevant campaign context pointer
- pending or recent work items visible to the operator
- approvals requested and resolved
- audit events
- final summaries and references to durable campaign memory

## Session Ownership Principles

### Orchestrator Owns Session Coordination

- The orchestrator should be the primary interpreter of session state.
- Specialists contribute outputs, but the orchestrator maintains continuity.

### Structured State Beats Chat Memory

- Important workflow data should be stored in structured form.
- The system should not rely only on conversational recall.
- Durable campaign truth should live in campaign memory rather than only inside session chat history.

### Pending Decisions Must Be Explicit

- Approval waits should be first-class state, not implicit pauses.
- A resumed session should know exactly what it was waiting on.
- The runtime should preserve this state without taking over interpretation of the operator reply.

## Telegram Interaction Model

The Telegram operator experience should stay intentionally simple.

Expected interaction pattern:

1. Operator starts with `/new`.
2. Operator sends goal in natural language.
3. App attaches the session to a campaign and responds with questions, findings, summaries, work updates, or approvals.
4. Operator continues the same work through follow-up messages.

The session layer should make this feel coherent despite multi-agent internals.
Clarifying questions should flow naturally through the orchestrator rather than through a separate runtime-only question system.

## Session Data Requirements

The exact persistence model is still open, but session storage likely needs:

- canonical session record
- message history or normalized event history
- current status
- campaign linkage
- pending approval record if present
- links to campaign memory and relevant work items

## Failure And Recovery Considerations

The session model should eventually account for:

- Telegram delivery retries or duplicate updates
- tool failures during active work
- partial completion of a delegated work item or scheduled task
- operator silence during approval waits
- campaigns that continue to accumulate memory across many sessions

Recovery behavior is not yet fully designed, but the session layer should make it possible.

## Relationship To Workflow Entities

Sessions are not the same thing as campaigns or communities.

A session is the operator-facing work thread, not the full durable work container.

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
- clean campaign attachment
- clear active versus pending-approval state
- resumable work
- enough persistence to avoid losing reasoning context

It should avoid prematurely complex workflow state machines.

## Success Criteria

This lifecycle is successful when:

1. An operator can start and continue work through Telegram without repeating context constantly.
2. The system can pause for approvals and resume cleanly.
3. Important outputs persist outside raw chat text in a durable campaign workspace.
4. The orchestrator can maintain continuity over multi-turn workflows and across multiple sessions attached to the same campaign.

## Open Questions

- What should happen if the operator sends a new request while an approval is pending?
- Should one operator have one active session at a time or multiple concurrent sessions?
- How much raw Telegram message history should be persisted versus summarized?
- What session timeout or archival policy should exist for inactive work?
