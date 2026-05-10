# App Runtime Architecture

## Purpose

Define the runtime architecture for reshaping OpenSwarm into a Telegram-native autonomous agent platform.

This document focuses on execution boundaries, runtime responsibilities, and control flow. It does not redefine product behavior already covered by other specs.

## Design Goal

The app should treat Telegram as the primary operating surface and OpenSwarm as the coordination substrate.

The runtime should:

- accept operator input from Telegram
- preserve session continuity across interactions
- route work through an orchestrator
- let specialist agents reason within clear boundaries
- expose Telegram actions through a reusable capability layer
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
- persist session context, artifacts, decisions, and pending approvals
- make prior context retrievable by the orchestrator

This layer is the continuity backbone of the app.

### 4. Orchestrator Layer

Responsibilities:

- interpret operator intent
- decide whether work is research, planning, execution, or approval-gated
- delegate to specialist agents
- merge outputs into a coherent response
- maintain control over high-risk or state-changing actions

The orchestrator is the control brain of the product.

### 5. Specialist Agent Layer

Responsibilities:

- perform role-specific reasoning
- produce structured outputs
- request execution through shared capabilities
- escalate ambiguity or sensitive actions

The first role emphases are:

- Discovery Agent
- Strategy Agent
- Account Manager Agent

These roles should express decision-making emphasis, not hard implementation silos.

### 6. Telegram Capability Layer

Responsibilities:

- expose Telegram actions through stable internal interfaces
- normalize account access, community access, messaging operations, and audit visibility
- shield specialist agents from transport and client implementation details

This layer is the engineering center of the platform.

### 7. State and Audit Layer

Responsibilities:

- persist structured records
- store workflow outputs for reuse
- record approvals, assignments, joins, and other meaningful actions
- preserve enough history for later automation and review

## Target Control Flow

The intended high-level flow is:

1. Telegram receives an operator action.
2. The transport layer normalizes the event.
3. A thin app service handles transport-level entry rules and loads runtime state.
4. The session layer attaches it to an existing or new session.
5. The orchestrator interprets the request.
6. The orchestrator delegates reasoning to one or more specialists.
7. Specialists read or propose actions through the Telegram capability layer.
8. Sensitive writes or ambiguous decisions return to the orchestrator for approval handling.
9. The orchestrator responds through the Telegram transport layer.

## Control Boundary Principles

### Orchestrator Owns User-Facing Control

- The operator should interact conceptually with one app brain, not a noisy mesh of agents.
- The orchestrator should remain responsible for summaries, approvals, and session continuity.
- The orchestrator should be free to ask clarifying questions whenever more context is needed.

### App Service Owns Thin Runtime Adaptation

- Runtime code should handle session entry, bookkeeping, and context loading.
- Runtime code should not try to classify conversational intent, resolve approval semantics, or branch workflows on behalf of the orchestrator.

### Specialists Own Reasoning Emphasis

- Specialists should propose and analyze within their role domain.
- Specialists should not each invent their own Telegram execution rules.

### Capability Layer Owns Execution Semantics

- Telegram implementation details should not leak into every agent.
- Execution interfaces should stay stable even if the underlying Telegram mechanism changes.

### State Layer Owns Reusability

- Outputs must be persisted in structured form.
- The system should avoid burying important decisions in chat text only.

## Communication Topology Direction

The default all-to-all OpenSwarm communication model is likely too open for this app's first production shape.

Preferred direction:

- operator input enters through the orchestrator
- specialist-to-specialist collaboration is allowed when useful
- important write actions still route through shared control boundaries
- approval-sensitive paths should return to the orchestrator

This does not forbid agent collaboration. It narrows where control is finalized.

## Runtime Implementation Bias

The implementation should favor:

- thin Telegram UI
- strong session continuity
- orchestrator-led workflows
- stable capability interfaces
- structured persistence

The implementation should avoid:

- Telegram logic duplicated inside many agents
- uncontrolled direct write paths
- role definitions that substitute for architecture
- chat-only outputs for reusable workflow artifacts

## Integration With Existing Repo Structure

The existing repo likely evolves toward these concerns:

- `server.py` or a neighboring entrypoint for Telegram-facing HTTP integration
- `telegram_app/app_service.py` for thin runtime adaptation
- `swarm.py` for agency composition and communication topology
- `orchestrator/` for control-brain behavior
- new Telegram-facing modules for transport, capabilities, and persistence
- updated shared instructions aligned to the platform constitution

Exact file placement is still open.

## Likely New Subsystems

- Telegram bot transport adapter
- thin app service
- session storage service
- capability facade for Telegram operations
- approval state tracker
- structured persistence models and repositories

## Success Criteria

This runtime design is correct when:

1. Telegram remains the primary operator surface without requiring a rich UI.
2. Sessions persist cleanly across multi-step operator interactions.
3. The orchestrator remains the stable control point.
4. Specialist agents can evolve without rewriting Telegram internals.
5. Underlying Telegram tooling can change without redefining workflow roles.

## Open Questions

- Should Telegram transport use webhook delivery, polling, or a hybrid development strategy?
- Should specialist agents call capabilities directly, or should write operations route through an execution facade?
- Where should approval state live relative to session state?
- How much of the current all-to-all handoff model should be preserved?
