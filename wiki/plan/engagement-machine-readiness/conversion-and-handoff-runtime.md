# Conversion And Handoff Runtime

## Goal

Add the runtime seam that carries qualified conversations beyond engagement into a concrete business next step, operator-reviewed handoff, or both.

## Why This Is Separate

The machine can be considered readiness-complete before this exists.

This step is the first real extension from "the loop runs safely" to "the loop advances commercial outcomes deliberately."

## Current Baseline

Already present in code and design:

- the live engagement machine can already listen, reason, queue, and observe
- the north-star already expects qualified conversations to move toward a business-defined next step
- current pause and escalation posture can stop or surface conversations, but not yet progress them through a dedicated conversion runtime

Missing today:

- one first-class conversion or handoff seam
- one durable state model for conversion progression
- one explicit handoff contract from automation into operator-led commercial follow-through

## Implementation Track

### Conversion State

- define a minimal qualification and conversion progression model
- keep the first cut compact and campaign-owned
- avoid turning this into a full CRM inside the runtime

### Handoff Contract

- define what information a strong lead handoff must preserve
- define when automation stops and operator ownership begins
- define whether handoff creates a work item, a conversation state transition, or both

### Operator Flow

- surface conversion-ready or handoff-ready conversations clearly
- capture operator outcomes without requiring raw file inspection
- preserve enough history for later campaign review

## Non-Goals

- building a full sales pipeline product
- generic multi-channel lead routing
- broad post-conversion lifecycle automation

## Acceptance Criteria

- qualified conversations can transition into one compact conversion or handoff runtime path
- the handoff preserves the needed business and conversation context
- operator outcomes are durable and visible for later campaign review
