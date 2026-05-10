# Telegram Capability Layer

## Purpose

Define the reusable Telegram execution surface that specialist agents and the orchestrator rely on.

This document exists to prevent Telegram implementation details from leaking into every agent prompt or tool bundle.

## Design Goal

The Telegram capability layer should be the stable interface between agent reasoning and Telegram operations.

It should:

- expose Telegram actions in role-agnostic form
- normalize account and community operations
- support both read and write workflows
- preserve auditability and safety hooks
- remain reusable across workflows beyond marketing

## Architectural Role

This layer sits between:

- orchestrator and specialist agents above
- Telegram client/runtime implementation below

Agents should think in terms of capabilities, not raw Telegram client details.

## Core Principle

Telegram capabilities should be broad enough to support flexible agent behavior, but structured enough to remain observable and governable.

## Capability Families

### 1. Session and Account Capabilities

Examples:

- list available Telegram accounts
- inspect account metadata and status
- inspect account restrictions or risk indicators
- select or reserve an account context for work

Expected consumers:

- orchestrator
- account manager

### 2. Community Discovery Capabilities

Examples:

- search for groups or channels by keyword or topic
- resolve handles, invite links, and visible metadata
- inspect community type and accessibility
- collect lightweight candidate data for ranking

Expected consumers:

- discovery agent
- orchestrator

### 3. Community Profiling Capabilities

Examples:

- read recent messages
- inspect community norms signals
- infer likely moderation posture
- capture evidence notes for profiling

Expected consumers:

- discovery agent
- strategy agent

### 4. Membership and Access Capabilities

Examples:

- join a community
- leave a community
- inspect membership state
- record join outcomes or restrictions

Expected consumers:

- account manager
- orchestrator under approval flows

### 5. Messaging Capabilities

Examples:

- read message history
- send a message
- reply in-thread or in-chat
- read and continue direct-message context

Expected consumers:

- strategy agent
- account manager
- future engagement workflows

### 6. State and Audit Capabilities

Examples:

- log actions
- read prior execution history
- attach evidence to community profiles
- expose structured action records

Expected consumers:

- all agents
- future reporting workflows

## Interface Shape

The capability layer should expose operations in a stable, high-level form.

Examples of desired interface qualities:

- clear input contracts
- explicit action names
- structured results
- standard error shapes
- audit metadata where relevant

The exact code interface is still open, but the abstraction should be narrow and intentional.

## Capability Design Principles

### Separate Read and Write Intent

- Read operations should be easy to reuse in analysis workflows.
- Write operations should be more observable and approval-friendly.

### Prefer Structured Outputs

- Capabilities should return structured records whenever possible.
- Agent prompts should not need to parse raw Telegram client output heavily.

### Keep Roles Out Of The Capability API

- Capabilities should not be named for specific agents.
- They should represent Telegram domain actions that any workflow can reuse.

### Preserve Swapability

- The layer should survive a change in Telegram execution backend.
- Browser automation, Telegram client libraries, or a hybrid approach should remain implementation choices beneath the interface.

## Backing Execution Options

The current design leaves these implementation strategies open:

- Telegram client library
- browser automation
- hybrid model

The capability layer should absorb this choice so workflow logic does not depend on it.

## Approval and Guardrail Hooks

The capability layer should not own policy decisions outright, but it should expose hooks for:

- approval-required operations
- action classification
- risk annotations
- audit logging

This enables later policy enforcement without rewriting every agent.

## Relationship To Agent Design

The capability layer should let role agents remain relatively broad:

- Discovery Agent can search and inspect communities
- Strategy Agent can inspect context and propose messaging
- Account Manager can inspect account state and plan assignments

The agents should use the same capability substrate instead of each carrying bespoke Telegram tools.

## Minimal MVP Surface

The MVP likely needs at least:

- account inventory read
- community discovery
- community metadata/profile read
- membership state read
- join operation
- message read
- structured action logging

Write messaging may exist later or stay gated depending on rollout risk.

## Non-Goals

This layer should not:

- encode campaign strategy
- own orchestrator reasoning
- replace persistence models
- become a product-specific rules engine

## Success Criteria

This layer is successful when:

1. Agents can perform Telegram-relevant work without knowing backend mechanics.
2. Read workflows and write workflows are clearly distinguishable.
3. Telegram tooling can evolve without breaking role definitions.
4. State and audit information can be captured consistently.

## Open Questions

- Which capabilities must be synchronous versus queued?
- Should write capabilities execute directly or produce execution requests for orchestrator approval?
- What metadata should every capability return by default?
- Which operations belong in MVP versus later engagement phases?
