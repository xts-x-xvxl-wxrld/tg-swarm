# Continuous Autonomous Operations

## Goal

Define how a campaign keeps running after initial setup instead of stopping at a finished plan.

## Core Problem

The repo already has strong foundations for planning and growing live execution seams, but the product still needs one explicit operating target for a continued self-improving campaign process.

## Desired Direction

After campaign interpretation and confirmation, the runtime should be able to:

- continue discovery and refresh
- adapt messages and assets
- qualify leads
- route leads toward conversion
- pause or escalate when blocked

## Important Boundaries

Continuous operation should not mean unconstrained action.

The runtime still needs:

- campaign-level pause and resume
- account health limits
- explicit blockage visibility
- conservative escalation paths

## First Questions To Lock

- what campaign posture signals should drive continued operation
- how the runtime decides between continuing, revising, or escalating
- what minimum self-improvement loops are worth landing first
- how conversion outcomes refresh strategy and execution posture

## Expected Deliverables

- one explicit continuous campaign loop model
- bounded improvement and refresh triggers
- operator-visible blocked-state reporting
- cleaner links between campaign signals, planning refresh, and conversion outcomes
