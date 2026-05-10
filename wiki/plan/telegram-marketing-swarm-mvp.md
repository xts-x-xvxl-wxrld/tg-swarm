# Telegram Platform + Marketing MVP Plan

## Goal

Turn the current general-purpose OpenSwarm harness into a Telegram-native agent platform with a minimal bot UI, an orchestrator, a shared Telegram capability layer, and a first marketing/community-operations mode with three primary role emphases:

- Discovery Agent
- Strategy Agent
- Account Manager Agent

## Phase 1: Define The Telegram Core

### Objectives

- define the minimal Telegram operator UI
- define the orchestrator as the session-level control brain
- define the Telegram capability layer as the reusable platform foundation

### Deliverables

- operator bot contract
- orchestrator session model
- Telegram core platform spec

## Phase 2: Define Shared System Behavior

### Objectives

- define role-based autonomy
- define the shared constitution/prompts concept
- identify guardrails that should exist later without enforcing them yet

### Deliverables

- role definitions
- shared behavior draft
- planned guardrail inventory

## Phase 3: Define The Shared Data Layer

### Objectives

- introduce persistent records for campaigns, communities, profiles, accounts, assignments, and playbooks
- make agent outputs structured and reusable

### Deliverables

- schema draft
- storage choice
- serialization format for agent handoff outputs

## Phase 4: Build Discovery First

### Objectives

- let the system ingest a campaign brief
- find candidate Telegram communities
- score and summarize them consistently

### Deliverables

- discovery instructions
- discovery tools
- community ranking output format

## Phase 5: Build Strategy Second

### Objectives

- convert discovery output into campaign segments and message playbooks
- produce community-specific guidance instead of generic messaging

### Deliverables

- strategy instructions
- playbook schema
- review-ready campaign strategy output

## Phase 6: Build Account Management Third

### Objectives

- track account inventory and health
- assign accounts to communities safely
- produce join and warm-up plans

### Deliverables

- account registry format
- assignment logic
- pacing and cooldown rules

## Phase 7: Add Approval Surfaces And Guardrail Placeholders

### Objectives

- leave room for future approvals without over-constraining the first implementation
- identify where guardrails will eventually be enforced

### Deliverables

- approval surface design
- planned enforcement points
- operator escalation model

## Recommended Technical Order

1. Define the Telegram core platform.
2. Define the shared autonomy model and planned guardrails.
3. Create the structured data model.
4. Implement Discovery Agent.
5. Implement Strategy Agent.
6. Implement Account Manager Agent.
7. Add reporting and approval surfaces.

## What We Should Not Build Yet

- autonomous multi-account engagement loops
- full analytics dashboards
- cross-platform connectors
- complex lead scoring
- self-optimizing message experimentation
- hard guardrail enforcement logic
- rich Telegram bot UI

## Acceptance Criteria

- An operator can start a session from Telegram with `/new`.
- The orchestrator can receive and handle freeform operator intent.
- The platform model supports broad Telegram capability access for specialist agents.
- The swarm can return a ranked community shortlist.
- The swarm can return a community-aware strategy brief.
- The swarm can return an account assignment/join plan.
- All outputs are stored in structured form for reuse.
