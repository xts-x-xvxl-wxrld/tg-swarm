# Telegram Core Platform

## Purpose

Build a Telegram-native autonomous agent platform where a human operator interacts through a minimal bot UI, an orchestrator interprets intent and manages sessions, and specialist agents can use Telegram broadly under shared behavioral guidance.

This platform is broader than any single workflow. Marketing is the first operating mode, not the whole product.

This document should be read alongside [Campaign Operations Model](C:/Users/ravil/OneDrive/Desktop/tg-swarm/wiki/spec/campaign-operations-model.md), which defines the current source-of-truth operating shape for campaigns, delegated work, memory, and scheduling.

## Product Statement

This app exists to let an operator manage autonomous agent campaign operations through Telegram itself.

The system should:

- receive operator intent through a Telegram bot
- maintain session and campaign context
- coordinate specialist agents
- support delegated work and recurring operational cadence
- give agents broad access to Telegram functionality
- allow the first workflow package to focus on community-driven growth use cases

## Core Principles

- Telegram capability is the foundation.
- Campaign operations sit on top of the platform.
- The operator interface stays intentionally simple at first.
- Agent autonomy is shaped mostly by prompts, role definitions, and shared rules.
- Guardrails should be documented now and enforced later.
- Campaigns, not one-off chat sessions alone, should be the durable operational objects.

## Operator Interaction Model

### UI Surface

The initial Telegram operator interface is deliberately thin:

- `/new` starts a new operator session
- freeform messages are forwarded to the orchestrator

The UI does not need rich menus, dashboards, or complex command trees in the first version.

### Expected Operator Actions

The operator should be able to:

- start a new session
- describe a goal in plain language
- ask follow-up questions
- review results
- review recurring campaign updates
- respond to approval requests
- receive summaries and status updates

## Platform Layers

### 1. Telegram Bot UI

Responsibilities:

- receive `/new`
- receive operator messages
- display orchestrator responses
- relay questions, summaries, approvals, and results

### 2. Orchestrator

Responsibilities:

- interpret operator intent
- create and manage session context
- attach work to durable campaign context
- choose which agents should think or act
- assign campaign goals rather than scripting every tactical substep
- schedule recurring review, discovery, and maintenance work
- gather outputs into coherent responses
- maintain continuity across sessions and campaign cycles

### 3. Campaign Memory And Work Coordination

Responsibilities:

- persist durable campaign memory
- distinguish shared campaign memory from agent-local working memory
- support work-item based delegation
- support recurring schedules and campaign review cadence

This layer makes the platform operational over time rather than only conversational turn by turn.

### 4. Telegram Capability Layer

Responsibilities:

- expose Telegram actions and state to the agents
- normalize account/session access
- provide a reusable interface for reading, joining, messaging, and account operations

This is the core reusable platform layer.

### 5. Specialist Agents

Responsibilities:

- operate according to their role prompts
- use Telegram capabilities when needed
- collaborate through the orchestrator and shared campaign context
- own tactical execution inside their domain
- maintain domain working memory and promote durable findings into campaign memory when appropriate

These agents should not be overly boxed into tiny task-only capabilities. They are role-based operators with broad access and different priorities.

## Agent Autonomy Model

The intended model is:

- broad Telegram capability access
- role-based prompts
- shared platform constitution
- minimal hard restrictions in the first planning phase

This means the system should favor behavioral guidance over deep capability partitioning.

The goal is not to make each agent able to do only one narrow step. The goal is to let each agent act flexibly while still optimizing for its role.

The responsibility split should be:

- operator decides direction and constraints
- orchestrator decides priorities and delegation
- specialists decide tactical substeps inside scope

## Telegram Capability Categories

The platform should eventually support these capability families:

### Session and Account Operations

- account inventory access
- session selection
- session/account state inspection
- account status and restriction checks

### Community Operations

- discover channels and groups
- inspect community metadata
- join or leave communities
- read recent activity and norms

### Messaging Operations

- read messages
- send messages
- reply in threads or chats
- review DM context
- continue conversations where appropriate

### State and Audit Operations

- log actions
- read prior session history
- read prior campaign state
- inspect community/account state
- expose structured records for later campaign work, schedules, and reviews

## Session Model

A session is an operator-driven thread of work that begins with `/new`.

It should be treated as the conversational interface into a campaign, not the full durable campaign object itself.

Each session should eventually hold:

- operator intent
- campaign linkage
- orchestrator reasoning context
- relevant communities
- relevant accounts
- decisions made so far
- outputs produced so far

Campaigns should hold the longer-lived operating memory that survives across multiple sessions.

This does not yet define the final persistence implementation, only the operating concept.

## Shared Behavioral Constitution

The system should eventually have a shared constitution that all agents inherit.

For now, the constitution should cover:

- how to use Telegram responsibly
- how to escalate ambiguity
- how to preserve session continuity
- how to prefer useful, context-aware action over spammy action

The constitution is conceptually required now, even if its final prompt text is not written yet.

## Planned Guardrails

Guardrails should be present in the design, but not yet enforced in implementation.

### Types of Planned Guardrails

- behavior guardrails
- account safety guardrails
- approval guardrails
- Telegram platform guardrails

### Current Status

- identified
- should be documented
- enforcement deferred

## First Operating Mode

The first supported workflow package is community marketing / community operations.

Its initial emphasis is:

- discovery
- campaign strategy
- account management

This operating mode depends on the Telegram core platform but should not define the whole platform.

Its runtime shape should follow the newer campaign-operations model:

- the operator acts like a manager
- the orchestrator acts like a campaign manager
- specialists act like tactically autonomous workers
- campaigns persist across sessions
- recurring work is scheduled over time

## Success Criteria

The platform model is correct when:

1. A human can operate the system from Telegram with very little UI complexity.
2. The orchestrator can receive and manage freeform intent.
3. Specialist agents can use Telegram broadly without being artificially boxed into tiny task silos.
4. The platform can support long-lived campaign memory, delegated work, and recurring operating cadence.
5. The platform is reusable for workflows beyond marketing.
6. The first workflow package can be implemented without redesigning the platform.

## Open Questions

- What execution method should back the Telegram capability layer?
- How should session context persist between bot interactions?
- Should all agents access all Telegram tools directly, or should some operations route through a Telegram ops facade?
- Which guardrails should be documented first even if enforcement is deferred?
