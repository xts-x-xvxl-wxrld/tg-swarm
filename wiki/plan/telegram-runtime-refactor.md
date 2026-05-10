# Telegram Runtime Refactor Plan

## Goal

Turn the current general-purpose OpenSwarm repo into a Telegram-native app foundation without prematurely committing to the full marketing workflow implementation.

Phase 1 should produce the runtime skeleton that later workflow specialization can sit on top of cleanly.

## Phase 1 Intent

Phase 1 is about architecture, not feature completeness.

By the end of this phase, the repo should have:

- a Telegram-facing runtime entrypoint direction
- a session-aware control path
- an orchestrator-centered topology
- a dedicated home for Telegram capabilities
- a narrowed agent roster aligned to the product

Phase 1 should not yet attempt broad autonomous engagement behavior.

## Why This Phase Exists

The current repo is structurally strong but product-shape mismatched.

Today it is:

- a general multi-agent deliverables system
- composed of many specialist media and productivity agents
- wired with broad all-to-all communication

The target product is:

- a Telegram-native operator app
- centered on session continuity and agent orchestration
- dependent on a reusable Telegram capability layer

This phase closes that gap by establishing the runtime boundaries first.

## Current Repo Anchors

The plan should evolve these current anchors:

- [swarm.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/swarm.py)
- [server.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/server.py)
- [orchestrator/orchestrator.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/orchestrator/orchestrator.py)
- [shared_instructions.md](C:/Users/ravil/OneDrive/Desktop/tg-swarm/shared_instructions.md)
- [shared_tools](C:/Users/ravil/OneDrive/Desktop/tg-swarm/shared_tools)

## Target Outcomes

Phase 1 is successful when we have:

1. A concrete place for Telegram transport code.
2. A concrete place for session state and approval state.
3. A concrete place for Telegram domain capabilities.
4. An orchestrator wired for the narrower product.
5. A reduced default agent topology that reflects the Telegram platform direction.

## Proposed Runtime Shape

The repo should evolve toward these top-level concerns:

### Existing Areas We Keep

- `orchestrator/`
- `shared_tools/`
- `patches/`
- `swarm.py`
- `server.py`

### New Areas We Introduce

- `telegram_app/`
- `telegram_app/app_service.py`
- `telegram_app/transport/`
- `telegram_app/sessions/`
- `telegram_app/approvals/`
- `telegram_app/capabilities/`
- `telegram_app/models/`

The exact names can still shift slightly, but the separation of concerns should remain.

## Proposed Module Responsibilities

### `telegram_app/transport/`

Responsibilities:

- Telegram update intake
- webhook or polling adapters
- response delivery back to Telegram
- normalization of Telegram events into internal requests

### `telegram_app/app_service.py`

Responsibilities:

- thin runtime adapter between Telegram transport and orchestrator
- handle transport-level session entry such as `/new`
- attach turns to the active session
- surface pending approval state back to the orchestrator
- avoid interpreting conversational meaning in app-layer code

### `telegram_app/sessions/`

Responsibilities:

- session creation and lookup
- active session resolution per operator
- session persistence contracts
- workflow state resume support

### `telegram_app/approvals/`

Responsibilities:

- pending approval tracking
- approval request formatting
- approval state lookup and persistence for orchestrator-led resumption

### `telegram_app/capabilities/`

Responsibilities:

- Telegram account operations facade
- community discovery/profile operations facade
- membership and messaging operations facade
- audit-aware execution surface

### `telegram_app/models/`

Responsibilities:

- structured runtime records
- session record shapes
- approval record shapes
- workflow entity shapes where needed in Phase 1

## Agent Topology Direction

Phase 1 should narrow the agency from the stock OpenSwarm shape.

### Keep Active

- Orchestrator
- Deep Research Agent, if we want a temporary research-heavy bridge for discovery work

### Add Or Prepare

- Discovery Agent
- Strategy Agent
- Account Manager Agent

These may begin as scaffolded agents before they have final tools.

### De-emphasize Or Remove From Default Product Path

- General Agent
- Slides Agent
- Docs Agent
- Image Agent
- Video Agent
- Data Analyst

These can remain in the repo initially, but they should not define the Telegram app's default user path.

## Recommended Communication Topology

Phase 1 should move away from unrestricted all-to-all communication.

Preferred direction:

- operator-facing requests enter through orchestrator
- orchestrator delegates to specialists
- specialists can hand back to orchestrator
- write-sensitive flows resolve through orchestrator-controlled boundaries

This is more important than perfect final topology in this phase.

## Concrete Refactor Steps

### Step 1. Add Runtime Scaffolding

Create the new `telegram_app/` package and its boundary modules without trying to solve final Telegram execution details yet.

Deliverables:

- package folders
- placeholder module files
- docstrings or minimal interfaces describing responsibility

### Step 2. Introduce Session And Approval Contracts

Create basic runtime data shapes and simple in-memory or file-backed placeholders for:

- session records
- approval records
- lookup/resume operations

The point is to establish the control path, not final storage.

### Step 3. Introduce Telegram Capability Facade Interfaces

Create a stable internal interface for Telegram domain actions before binding to a backend.

Initial facade domains:

- accounts
- communities
- membership
- messaging
- audit/logging

These can be interfaces or stub implementations at first.

### Step 4. Wire A Thin Telegram App Service

Introduce a thin `telegram_app/app_service.py` layer that connects normalized Telegram updates to session state and the orchestrator without turning runtime code into a decision engine.

Immediate target:

- keep `/new` as the main runtime-level special command
- persist incoming session turns
- pass session and pending-approval context through to the orchestrator
- let the orchestrator decide whether a turn is a clarification, a continuation, a new request, or an approval response

### Step 5. Narrow The Agency Composition

Update [swarm.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/swarm.py) planning so the eventual active roster matches the Telegram app direction.

Immediate target:

- preserve orchestrator
- decide whether to keep deep research temporarily
- prepare dedicated Telegram workflow agents

### Step 6. Prepare A Telegram Entry Path

Refactor [server.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/server.py) planning so Telegram transport can become a first-class entrypoint instead of treating the API layer as a generic wrapper only.

This may remain partially scaffolded in Phase 1.

### Step 7. Align Shared Instructions

Plan updates to [shared_instructions.md](C:/Users/ravil/OneDrive/Desktop/tg-swarm/shared_instructions.md) so the runtime assumptions match:

- Telegram-native operator flow
- session continuity
- approval sensitivity
- role-based Telegram work

## Proposed Folder Skeleton

```text
telegram_app/
  __init__.py
  app_service.py
  transport/
    __init__.py
    telegram_updates.py
    telegram_responses.py
  sessions/
    __init__.py
    session_store.py
    session_manager.py
  approvals/
    __init__.py
    approval_store.py
    approval_manager.py
  capabilities/
    __init__.py
    base.py
    accounts.py
    communities.py
    membership.py
    messaging.py
    audit.py
  models/
    __init__.py
    session.py
    approval.py
    workflow.py
```

This is intentionally modest and can grow later.

## Phase 1 Implementation Bias

Prefer:

- narrow interfaces
- placeholder implementations where needed
- orchestrator-centered control flow
- low-risk structural changes

Avoid:

- binding to one Telegram backend too early
- rewriting every existing agent immediately
- adding many workflow-specific rules into shared runtime code
- overbuilding persistence before the control path is proven

## Suggested Sequence For Actual Code Work

1. Add `telegram_app/` package scaffolding.
2. Add session and approval model/store interfaces.
3. Add Telegram capability facade interfaces.
4. Add a thin `telegram_app/app_service.py` adapter.
5. Add or scaffold Telegram-focused agent folders.
6. Refactor `swarm.py` toward the narrowed topology.
7. Refactor `server.py` toward Telegram-aware entrypoints.
8. Update shared and orchestrator instructions to match the new runtime model.

## Out Of Scope For Phase 1

- full Telegram backend implementation
- live join or message execution at scale
- final workflow prompts for all agents
- final persistence database choice
- final enforcement guardrail logic
- full marketing campaign automation

## Risks To Watch

### Risk 1: Architecture Drift

If we keep using the stock agent roster too long, the product may continue to behave like general OpenSwarm with Telegram features bolted on.

### Risk 2: Capability Leakage

If Telegram operations are implemented directly inside agent-specific tools too early, the capability layer will lose its value.

### Risk 3: Premature Backend Commitment

If we commit to browser automation or a client library before the capability contracts are stable, later change will be painful.

## Acceptance Criteria

- The repo has a documented target package layout for Telegram runtime concerns.
- Phase 1 code work can begin without ambiguity about where new responsibilities belong.
- The app runtime keeps transport/session concerns thin and leaves turn interpretation to the orchestrator.
- The agency direction is clearly narrowed toward orchestrator plus Telegram workflow roles.
- Future Telegram execution details can plug in beneath stable capability interfaces.

## Next Planned Follow-Up

After this plan, the next most useful design artifact is:

- `wiki/spec/telegram-execution-backend.md`

That document should evaluate client library, browser automation, and hybrid execution choices against the capability-layer contract.
