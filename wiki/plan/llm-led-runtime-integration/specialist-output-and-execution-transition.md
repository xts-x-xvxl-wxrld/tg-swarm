# Specialist Output And Execution Transition

## Goal

Migrate specialist and live-review outputs from marker-first contracts toward compiled proposals, while keeping deterministic authorization and execution unchanged until the very end of the sequence.

## Final Shape This Slice Should Enable

This slice should help the repo move from:

- one orchestrator
- a small fixed planning specialist ladder
- one marker-shaped machine-readable contract per surface

to:

- one operator-facing control brain
- bounded reasoning surfaces selected by work, runtime pressure, and campaign context
- one shared typed proposal seam that all of those surfaces can use

In that final shape:

- planning specialists such as `discovery`, `strategy`, and `account_planning` may remain useful
- they are treated as bounded work-family surfaces, not as the permanent architecture of the runtime
- durable artifacts can still exist, but they no longer monopolize machine-readable meaning

## Why This Slice Comes After Operator Control

Specialist output and live reasoning surfaces are more central to runtime behavior than operator control parsing.

By the time this slice starts, the repo should already have:

- a compiled-intent envelope
- persistence for proposed intents
- validators by intent kind
- narrow applicators for accepted control and work proposals

That lets the runtime absorb richer reasoning output without turning execution into freeform side effects.

## Primary Migration Surfaces

### Orchestrator Schedule Output

Current surface:

- `prompts/orchestrator.md`
- `telegram_app/orchestrator/orchestrator.py`
- `telegram_app/workflow_validation.py`

Migration direction:

- stop treating schedule mutation as a special one-off marker path
- compile schedule proposals through the same intent framework as other control mutations

### Discovery And Planning Artifacts

Current surface:

- `prompts/discovery.md`
- strategy and account-planning output contracts
- artifact persistence in the orchestrator and session layer

Migration direction:

- keep final artifacts as durable outputs where they are still useful
- add typed companion proposals for follow-on work, invalidation, revision handling, and operator review posture
- avoid forcing every specialist conclusion to hide inside a single artifact schema
- make it possible for future planning work families to use the same proposal pattern without first adding a brand-new top-level specialist architecture

### Promoted-Thread Commercial Review

Current surface:

- `prompts/live_engagement_review.md`
- `telegram_app/engagement_brain/`

Migration direction:

- keep structured review output
- represent next-move proposals, learning notes, and execution-adjacent suggestions as typed intents or typed proposal objects
- preserve belief-state persistence as a deterministic application step, not a raw freeform side effect

## Policy And Execution Boundary

This slice should not weaken the current execution boundary.

Compiled proposals may recommend:

- reply
- ask
- wait
- escalate
- schedule follow-up work
- add campaign learning

But the runtime should still separately decide:

- whether the proposal is authorized
- whether readiness is sufficient
- whether consent posture allows it
- whether it should be queued for execution or kept advisory only

## Recommended Transition Strategy

### Step 1: Proposal Adapters Around Existing Outputs

Keep current prompt contracts active, but wrap their meaning into compiled proposals after parsing.

This gives the repo one inspection model before the prompts themselves are rewritten.

### Step 2: Prompt Contracts That Emit Typed Proposal Lists

Once the runtime can consume proposals reliably:

- move prompts away from one bespoke marker per surface
- prefer one typed proposal contract that can return zero or more proposals
- keep final operator-facing prose or durable artifacts separate from control proposals
- keep planning-oriented surfaces and live-review surfaces on the same conceptual proposal model even when their operator-facing artifacts differ

### Step 3: Execution-Adjacent Intents

Only after proposal handling is stable should the runtime introduce narrower compiled intent kinds for execution-adjacent decisions.

Those should still terminate at deterministic authorization and queueing seams.

## Acceptance Criteria

This slice is complete when:

- marker parsing is no longer the long-term primary control interface for specialist outputs
- promoted-thread reasoning outputs can be inspected as typed proposals
- belief-state, memory, and work refresh mutations are applied through deterministic application paths
- execution remains policy-gated and late in the flow
- the repo no longer depends on a tiny fixed specialist roster as the main way to explain how reasoning enters the runtime
