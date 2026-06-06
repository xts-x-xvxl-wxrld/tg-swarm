# Implementation Sequence

## Goal

Turn the readiness audit into a concrete execution order.

This note assumes the repo already has most of the lower-level live runtime seams in place and focuses on the narrow remaining work required to make them behave as one machine.

## Recommended Order

### Step 1: Plan Activation Contract

Land [Plan Activation Contract](./plan-activation-contract.md) first.

Why first:

- the runtime still lacks one locked bridge from approved account planning into live execution state
- later live triggers are much easier to reason about once there is a stable activation object to target
- this is the clearest boundary between planning completion and real campaign execution

Exit criteria:

- one explicit runtime contract exists for turning approved plan output into campaign-owned executable state
- operator activation and plan revision behavior are deterministic
- focused activation coverage proves prepared execution records survive restart and can be inspected

### Step 2: Conversation Review Triggering

Land [Conversation Review Triggering](./conversation-review-triggering.md) second.

Why second:

- inbound review moments and follow-up timing already persist in production-shaped state
- the engagement brain already knows how to review one conversation and queue a next move
- the main missing piece is a real worker path that notices those moments and invokes the brain

Exit criteria:

- inbound events can trigger bounded production review
- due follow-up windows can trigger bounded production review
- duplicate processing is controlled by durable claim or cursor rules

### Step 3: Autonomous Send Approval Alignment

Land [Autonomous Send Approval Alignment](./autonomous-send-approval-alignment.md) third.

Why third:

- once review triggering exists, the machine needs a clear answer for which proposed writes can actually be sent
- approval posture should be explicit before autonomous review is turned loose on real conversations
- this keeps policy clarity ahead of broader operator UX work

Exit criteria:

- the runtime distinguishes proposal generation from send authorization cleanly
- approved autonomous paths are explicit and narrow
- blocked writes surface a usable review state instead of silently failing

### Step 4: Telegram Live Ops Surface

Land [Telegram Live Ops Surface](./telegram-live-ops-surface.md) fourth.

Why fourth:

- by this point the machine can activate, reason, and queue work, so operator controls become high leverage
- pause, resume, and inspection flows are easier to expose once the underlying runtime contracts are stable
- this provides the human steering surface needed for safe live use

Exit criteria:

- operators can inspect readiness and live state in Telegram
- operators can pause and resume campaigns, accounts, and conversations through normal runtime flows
- escalation and blocked-write cases are visible without reading raw workspace files

## Phase 2 Extensions

These are valuable, but they should follow the readiness-critical sequence above.

### Step 5: Operator Takeover And Closure

Land [Operator Takeover And Closure](./operator-takeover-and-closure.md) after the live ops surface is usable.

Why here:

- takeover needs the earlier pause, inspection, and state-reporting primitives
- it is a richer operator-workflow feature, not a prerequisite for basic machine readiness

### Step 6: Conversion And Handoff Runtime

Land [Conversion And Handoff Runtime](./conversion-and-handoff-runtime.md) last.

Why last:

- this is the first major extension beyond "can the machine run safely"
- qualification and conversion semantics are easier to design once the engagement loop is already functioning end to end

## Cross-Step Validation

After each step:

- run the smallest focused pytest coverage for the touched seam
- verify current Telegram planning flows do not regress
- verify new durable state survives restart where applicable

Before calling the machine readiness series complete:

- run `python -m pytest tests/` if the local tree is stable enough
- run at least one Telegram smoke flow that covers plan approval, activation, inbound review, and operator intervention
