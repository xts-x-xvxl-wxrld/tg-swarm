# App Runtime Architecture

## Purpose

Define the runtime architecture for reshaping OpenSwarm into a Telegram-native autonomous agent platform.

This document focuses on execution boundaries, runtime responsibilities, and control flow. It should be read alongside [Campaign Operations Model](C:/Users/ravil/OneDrive/Desktop/tg-swarm/wiki/spec/campaign-operations-model.md), which defines the behavioral operating shape the runtime must support.

## Design Goal

The app should treat Telegram as the primary operating surface and OpenSwarm as the coordination substrate.

The runtime should:

- accept operator input from Telegram
- preserve session continuity across interactions
- preserve campaign continuity across sessions
- route work through an orchestrator
- let specialist agents reason within clear boundaries
- expose Telegram actions through a reusable capability layer
- support delegated work, recurring schedules, and long-lived campaign memory
- keep write actions, approvals, and state changes legible

## Architectural Position

The current OpenSwarm repository already provides:

- agent factories
- a shared orchestrator pattern
- a FastAPI server entrypoint
- shared instructions and tool loading conventions

The Telegram app should evolve this runtime rather than replace it wholesale.

## Target Runtime Layers

### 1. Telegram Transport Layer

Responsibilities:

- receive Telegram webhook or polling updates
- translate Telegram events into internal app events
- deliver replies, summaries, approval prompts, and status updates back to Telegram

Inputs:

- `/new`
- operator freeform messages
- replies to approval prompts
- follow-up session messages

Outputs:

- user-visible Telegram responses
- normalized session events

### 2. Thin App Service Layer

Responsibilities:

- handle transport-level runtime rules such as `/new`
- attach updates to the right session
- load pending approval state when present
- pass structured runtime context through to the orchestrator

This layer should not decide what a user message means beyond narrow transport concerns.

### 3. Session Layer

Responsibilities:

- create operator sessions
- bind messages to the correct active session
- attach sessions to the correct campaign workspace
- persist session context, campaign references, decisions, and pending approvals
- make prior context retrievable by the orchestrator

This layer is the conversational continuity backbone of the app.

It should not be the thing that owns asynchronous campaign work outside operator interaction.

### 4. Campaign State And Memory Layer

Responsibilities:

- persist the durable campaign workspace
- expose canonical shared memory to the orchestrator and specialists
- preserve campaign-level facts, decisions, priorities, and operating posture
- store agent working memory separately from canonical campaign memory
- support scheduled work and long-lived review cycles

This layer is the long-term operational memory of the app.

### 5. Orchestrator Layer

Responsibilities:

- interpret operator intent
- decide what work should happen now versus later
- create, assign, prioritize, or refresh work items
- schedule recurring review, discovery, and maintenance work
- delegate campaign goals to specialist agents
- merge outputs into a coherent response
- maintain control over high-risk or state-changing actions

The orchestrator is the control brain of the product.

### 6. Specialist Agent Layer

Responsibilities:

- perform role-specific reasoning
- make tactical decisions inside their domain
- maintain agent-local working memory
- update shared campaign memory when findings become durable
- produce structured outputs and durable memory updates
- request execution through shared capabilities
- escalate ambiguity or sensitive actions

The first role emphases are:

- Discovery Agent
- Strategy Agent
- Account Manager Agent

These roles should express decision-making emphasis, not hard implementation silos.

### 7. Telegram Capability Layer

Responsibilities:

- expose Telegram actions through stable internal interfaces
- normalize account access, community access, messaging operations, and audit visibility
- shield specialist agents from transport and client implementation details

This layer is the engineering center of the platform.

### 8. Scheduling And Work Coordination Layer

Responsibilities:

- persist recurring schedules
- create or refresh work items from those schedules
- run schedule-triggered work through the orchestrator and the relevant specialist path
- execute recurring work from a dedicated scheduler worker rather than implicitly from every webhook or polling process
- protect due-schedule dispatch with a single-worker lease or equivalent leader election
- resolve campaign context directly for background work, while tolerating a temporary bridge through the latest campaign session when artifacts are still session-scoped
- track schedule outcomes, repeated low-yield runs, and auto-paused schedules
- support campaign review cadences and recurring discovery or maintenance tasks
- avoid bypassing orchestrator control for risky execution

This layer turns the app from a one-pass workflow into an operating system for campaigns.

### 9. State and Audit Layer

Responsibilities:

- persist structured records
- store work items, approvals, schedules, and runtime events
- store reusable compatibility views where needed
- record approvals, assignments, joins, and other meaningful actions
- preserve enough history for later automation and review

## Target Control Flow

The intended high-level flow is:

1. Telegram receives an operator action.
2. The transport layer normalizes the event.
3. A thin app service handles transport-level entry rules and loads runtime state.
4. The session layer attaches it to an existing or new session and resolves the related campaign.
5. The orchestrator reads campaign memory, current work state, and any pending approvals.
6. The orchestrator decides whether to answer directly, create or update work items, or delegate to one or more specialists.
7. Specialists reason within scope, update their working memory, and write durable findings back into shared campaign memory when appropriate.
8. The orchestrator reviews cross-domain consequences, schedules follow-up work where useful, and routes sensitive writes or ambiguous decisions through approval handling.
9. The orchestrator responds through the Telegram transport layer when the trigger was operator-driven, or records background outcomes for later operator review when the trigger was schedule-driven.

The runtime may also initiate work without a fresh operator message when a campaign schedule creates a recurring work item. In those cases, the orchestrator should still remain the control point, and the runtime should resolve the campaign directly rather than pretending there is an active operator session.

For the current implementation, recurring dispatch should run in a dedicated scheduler-only process such as `python server.py --run-scheduler`. Webhook and polling app instances should not each run their own scheduler loop by default, because that creates duplicate-dispatch risk in multi-instance deployments.

The scheduler worker should hold a short renewable lease in shared runtime state before dispatching due schedules. If another live worker holds the lease, the current worker should skip the dispatch tick rather than racing.

Schedules should normally create or refresh work items and then execute bounded planning or review work through specialist agents. They should not directly perform risky external actions such as joins, outreach, posting, or member messaging.

Schedules may also carry simple health expectations such as:

- evaluation metric name
- minimum acceptable outcome value
- consecutive-miss limit before auto-pause

This allows recurring campaign work to stop cleanly when it keeps producing weak results instead of running forever without supervision.

## Control Boundary Principles

### Orchestrator Owns User-Facing Control

- The operator should interact conceptually with one app brain, not a noisy mesh of agents.
- The orchestrator should remain responsible for summaries, approvals, and session continuity.
- The orchestrator should assign outcomes and priorities rather than scripting every specialist substep.
- The orchestrator should be free to ask clarifying questions whenever more context is needed.

### App Service Owns Thin Runtime Adaptation

- Runtime code should handle session entry, bookkeeping, and context loading.
- Runtime code should not try to classify conversational intent, resolve approval semantics, or branch workflows on behalf of the orchestrator.

### Specialists Own Reasoning Emphasis

- Specialists should propose and analyze within their role domain.
- Specialists should own tactical choices within their assigned scope.
- Specialists should maintain their own working memory while respecting shared campaign truth.
- Specialists should not each invent their own Telegram execution rules.

### Capability Layer Owns Execution Semantics

- Telegram implementation details should not leak into every agent.
- Execution interfaces should stay stable even if the underlying Telegram mechanism changes.

### State Layer Owns Reusability

- Outputs must be persisted in structured form.
- Important campaign truth should live in campaign memory rather than only in session chat history.
- The system should avoid burying important decisions in chat text only.

## Communication Topology Direction

The default all-to-all OpenSwarm communication model is likely too open for this app's first production shape.

Preferred direction:

- operator input enters through the orchestrator
- specialist-to-specialist collaboration is allowed when useful
- campaign work may also originate from orchestrator-managed schedules and recurring work items
- important write actions still route through shared control boundaries
- approval-sensitive paths should return to the orchestrator

This does not forbid agent collaboration. It narrows where control is finalized.

## Runtime Implementation Bias

The implementation should favor:

- thin Telegram UI
- strong session continuity
- strong campaign continuity
- orchestrator-led campaign operations
- work-item and schedule-driven coordination
- stable capability interfaces
- structured persistence plus flexible campaign memory

The implementation should avoid:

- Telegram logic duplicated inside many agents
- uncontrolled direct write paths
- orchestrator micromanagement of every tactical action
- role definitions that substitute for architecture
- chat-only outputs for reusable campaign knowledge

## Integration With Existing Repo Structure

The existing repo likely evolves toward these concerns:

- `server.py` or a neighboring entrypoint for Telegram-facing HTTP integration
- `telegram_app/app_service.py` for thin runtime adaptation
- `telegram_app/campaigns/` or neighboring modules for campaign workspace and memory handling
- `telegram_app/scheduling/` or neighboring modules for recurring work
- `swarm.py` for agency composition and communication topology
- `orchestrator/` for control-brain behavior
- new Telegram-facing modules for transport, capabilities, campaign memory, and persistence
- updated shared instructions aligned to the platform constitution

Exact file placement is still open.

## Likely New Subsystems

- Telegram bot transport adapter
- thin app service
- session storage service
- campaign workspace and memory service
- work-item and scheduling service
- capability facade for Telegram operations
- approval state tracker
- structured persistence models and repositories

## Success Criteria

This runtime design is correct when:

1. Telegram remains the primary operator surface without requiring a rich UI.
2. Sessions persist cleanly across multi-step operator interactions while remaining attached to durable campaign workspaces.
3. The orchestrator remains the stable control point for both operator-driven and schedule-driven work.
4. Specialist agents can evolve without rewriting Telegram internals or surrendering tactical autonomy.
5. Underlying Telegram tooling can change without redefining campaign operations or workflow roles.
6. The runtime can support recurring campaign maintenance and review without reverting to a rigid stage pipeline.

## Open Questions

- Should Telegram transport use webhook delivery, polling, or a hybrid development strategy?
- Should specialist agents call capabilities directly, or should write operations route through an execution facade?
- Where should approval state live relative to session state?
- How much of the current all-to-all handoff model should be preserved?
- How quickly should campaign artifacts move from session-backed storage to campaign-backed storage so scheduled work no longer needs the latest-session bridge?
