# Orchestrator Routing And Compatibility

## Goal

Finish the campaign-loop router so operator turns are selected from campaign pressure, not from historical stage progression, while keeping the current Telegram planning UX understandable during migration.

## Why This Needs Its Own Slice

The repository already has most of the lower-level observation pieces:

- `observation` work items exist
- signal storage and review persistence exist
- scheduled observation review exists
- observation review can already refresh planning work deterministically

What is still incomplete is the operator-turn routing layer that decides what to do when setup, planning review, planning refresh, and live observation pressure all coexist.

This slice is where those seams become one coherent control plane.

## Core Decision

Keep `workflow_stage` as a Telegram UX compatibility summary only. Do not reintroduce stage-first control flow.

The real routing inputs should be:

- current setup readiness
- open work items
- active schedules
- unresolved observation pressure
- pending review posture for the currently selected work

## Current Runtime Baseline

The code is already partway through this transition:

- `telegram_app/orchestrator/orchestrator.py` already resolves most specialist turns from the primary open work item before falling back to `workflow_stage`
- `telegram_app/work_items/manager.py` already persists campaign-owned work items for planning and observation
- `telegram_app/scheduling/manager.py` and orchestrator scheduled-work paths already support schedule-triggered planning and observation execution
- `telegram_app/campaign_signals/manager.py` already persists `signals.json`, `reviews.json`, and `cursor.json`
- `PurposeBuiltOrchestrator.run_pending_observation_work(...)` already performs bounded observation review and deterministic follow-on refresh mapping

The main remaining gaps are in route selection and compatibility projection:

- `_get_primary_work_item(...)` still filters `observation` out of operator-turn routing
- `handle_turn(...)` still has no first-class operator-turn branch for `observation`
- compatibility backfill still assumes only discovery, strategy, and account planning are routable work families
- `workflow_stage` summaries still overfit the linear planning ladder even when campaign pressure is now broader than that
- normal orchestrator context does not yet surface observation pressure as a first-class routing explanation

## Scope

- allow `observation` to become the primary routed work family on operator turns when review pressure is highest
- preserve the current discovery -> strategy -> account-planning experience when no observation pressure exists
- keep setup gating ahead of planning and observation routing
- keep deterministic observation execution outside the live write path
- keep `campaign_brief` and `workflow_stage` as compatibility artifacts while real continuity lives in setup state, assets, memory, work items, schedules, and signals

## Non-Goals

- rebuilding the observation-review subsystem from scratch
- moving live review into the live execution write path
- replacing discovery, strategy, or account-planning specialists
- creating a broad new workflow-stage enum for every campaign posture
- adding operator dashboard concepts outside the current Telegram UX

## Target Routing Model

The router should answer one question on every operator turn:

Which campaign-owned concern deserves the next bounded turn right now?

Recommended precedence:

1. If campaign setup is incomplete, stay in setup.
2. If there is operator-facing review pending for the currently selected planning work item, handle that review turn.
3. If unresolved `observation` pressure is the highest-priority open work, route to observation review.
4. Otherwise continue the highest-priority open planning work item.
5. Fall back to a normal orchestrator turn when no specialist work family owns the turn.

This preserves the current planning flow but allows live campaign pressure to interrupt it when the runtime has a concrete reason.

## Setup Gate Rule

Setup should remain a hard gate ahead of normal work-family selection.

Routing should not ask planning or observation specialists to compensate for missing setup facts such as:

- missing campaign objective
- missing target audience basics
- missing readiness confirmation
- missing seed-group confirmation when discovery depends on it

Implementation direction:

- keep setup detection outside work-item priority scoring
- short-circuit routing into the existing setup path before selecting a primary work item
- treat setup readiness as a campaign-control predicate, not as just another open work item

## Observation Priority Rule

`observation` should become operator-turn routable, but not noisy.

Recommended first rule:

- `observation` may outrank planning work only when it is open and its priority is at least as strong as the current planning concern
- `review_pending` planning work should still beat low-signal observation noise
- high-priority or critical observation pressure should be allowed to outrank in-progress planning refresh work

Recommended first tie-break posture:

- prefer `REVIEW_PENDING` over `IN_PROGRESS`
- prefer `IN_PROGRESS` over `PENDING`
- within the same status band, prefer higher `priority`
- when status and priority tie, prefer the most recently refreshed item

This should extend the current primary-work-item scorer rather than introducing a second hidden router.

## Operator-Turn Observation Contract

Operator-turn observation routing should reuse the same bounded observation execution contract that scheduled review already uses.

Implementation direction:

- do not create a second observation-review implementation path inside `handle_turn(...)`
- factor any missing shared helper so scheduled observation runs and operator-triggered observation runs call the same execution logic
- keep the observation specialist bounded to reviewing compact signal digests and emitting one structured result plus a short operator-facing summary
- keep deterministic result persistence, signal state transitions, and planning follow-on mapping in runtime code

This means operator turns gain observation priority without duplicating observation logic.

## Review-Pending Planning Rule

Review-pending planning work should remain a strong compatibility-preserving posture.

Recommended first rule:

- if the selected planning work item is already `REVIEW_PENDING`, the operator should land in the existing conversational review flow for that work family
- observation should interrupt that only when the observation work is materially higher priority

This keeps the current Telegram review experience stable while still allowing serious live pressure to surface.

## Compatibility Direction

Preserve:

- current Telegram-friendly summaries
- current specialist artifact views where they still help
- current `workflow_stage` snapshots for operator comprehension
- current planning review prompts and approval-like conversational checkpoints

Move real continuity toward:

- `campaign_setup_state`
- campaign asset refs and `assets/manifest.json`
- campaign memory files
- work-item metadata such as `trigger_source`, `refresh_reason`, and `context_refs`
- `CampaignSignal` records and persisted review results

## `workflow_stage` Contract

The runtime should continue writing `workflow_stage`, but only as a readable projection.

Recommended first compatibility contract:

- keep the existing `WorkflowStage` enum if possible
- prefer projecting observation pressure into `workflow_snapshot.summary` and `workflow_snapshot.data` instead of inventing a full new irreversible observation stage
- keep `primary_work_item_id` and `primary_work_item_type` aligned to the actual routed item
- add compact compatibility data such as `routing_reason`, `pending_review_kind`, or `observation_pressure` when useful for Telegram-facing summaries and debugging

This keeps old session views understandable without making stage state authoritative again.

## Context-Building Direction

Normal runtime context should explain why the router selected the current work.

Recommended additions to `telegram_app/orchestrator/context_builder.py`:

- a compact primary-route summary
- a compact observation-pressure summary when unresolved review pressure exists
- explicit indication when the routed turn is a planning review versus a planning refresh versus an observation review

Keep that context compact. The router should expose routing reasons, not dump raw signal history into every turn.

## Compatibility Backfill Rules

Compatibility backfill should remain a migration bridge for old sessions, not the steady-state router.

Recommended rules:

- keep stage-to-work-item backfill only for legacy planning sessions that truly lack campaign-native work items
- do not backfill `observation` from stage, because observation pressure already has campaign-native work and signal records
- once a session has real campaign work items, prefer them completely over stage-derived guesses

## Implementation Tracks

### 1. Route Selection And Priority Scoring

Primary file:

- `telegram_app/orchestrator/orchestrator.py`

Implementation direction:

- replace the current planning-only primary-work-item selector with one scorer that can include `observation`
- centralize precedence rules for setup, review-pending planning work, observation pressure, and ordinary planning work
- keep the route result explicit enough that tests can assert why a route won

Concrete work:

- introduce a helper that returns the selected routed concern plus the routing reason
- stop filtering `OBSERVATION_WORK_TYPE` out of `_get_primary_work_item(...)`
- make observation priority an explicit policy instead of an accidental side effect of list order

### 2. Operator-Turn Observation Route

Primary file:

- `telegram_app/orchestrator/orchestrator.py`

Implementation direction:

- add a first-class `observation` branch to `handle_turn(...)`
- route it through the same bounded review execution path already used for scheduled observation work
- return a Telegram response that feels similar in clarity to the existing planning review turns

Concrete work:

- add one operator-turn adapter around shared observation execution
- ensure observation failures degrade cleanly back into a readable operator response instead of silently disappearing
- make completed observation results visible to the next normal planning turn

### 3. Compatibility Projection

Primary files:

- `telegram_app/orchestrator/orchestrator.py`
- `telegram_app/app_service.py`

Implementation direction:

- keep workflow-stage transition logging useful even when the routed work is no longer a pure stage step
- update stage summary text so it describes the current campaign posture instead of pretending the flow is strictly linear
- preserve existing monitoring hooks while making them truthful about campaign-driven routing

Concrete work:

- keep `_set_workflow_stage(...)` as a projection helper
- add routing metadata to workflow snapshot data where it improves operator comprehension or debugging
- ensure app-service transition logging still makes sense when observation becomes the routed concern

### 4. Runtime Context And Prompt Compatibility

Primary files:

- `telegram_app/orchestrator/context_builder.py`
- `prompts/orchestrator.md`

Implementation direction:

- expose the selected route and compact observation pressure to the orchestrator context when relevant
- update the orchestrator prompt only where needed so fallback non-specialist turns can explain the current routed posture coherently
- avoid teaching the prompt to own deterministic route decisions

### 5. Regression And Migration Coverage

Primary files:

- `tests/test_observation_review.py`
- orchestrator routing tests
- compatibility summary tests

Implementation direction:

- invert the current "operator turn ignores observation work" expectation into an explicit post-change routing assertion
- preserve no-regression tests for the normal discovery -> strategy -> account-planning flow when observation pressure is absent
- add tests proving compatibility summaries remain readable when observation is active

## Suggested Delivery Breakdown

### Slice A: Route Scoring Extraction

- extract route-selection logic into a small helper with explicit precedence rules
- keep behavior the same at first except for making observation eligibility testable

### Slice B: Observation Becomes Operator-Turn Routable

- remove the planning-only filter from primary-work selection
- add the first operator-turn observation branch
- reuse scheduled observation execution logic rather than duplicating it

### Slice C: Compatibility Summary Tightening

- update `workflow_stage` summary projection so observation pressure is visible without becoming stage authority
- add routing metadata fields that explain the selected work family

### Slice D: Regression Hardening

- lock route-precedence tests
- lock compatibility-summary tests
- verify normal planning turns still behave the same when there is no live pressure

## Concrete File-Level Work List

- `telegram_app/orchestrator/orchestrator.py`
  Unify route scoring, add operator-turn observation routing, and keep workflow-stage projection secondary.
- `telegram_app/orchestrator/context_builder.py`
  Surface compact route and observation-pressure context.
- `telegram_app/app_service.py`
  Keep stage-transition and routing telemetry truthful once observation can own a turn.
- `prompts/orchestrator.md`
  Adjust only the compatibility language needed for coherent fallback summaries.
- `tests/test_observation_review.py`
  Convert the current observation-routing regression from "ignored" to the new expected behavior.
- additional orchestrator routing tests
  Cover setup, planning review, observation pressure, normal planning work, and fallback orchestration.

## Migration Constraints

- do not delete `workflow_stage`
- do not require a historical session rewrite before the first routing cut lands
- do not make observation review free-running on every operator message; it still needs bounded persisted work
- do not let prompt logic become the source of route priority truth
- do not duplicate observation follow-on mapping in both scheduled and operator-turn paths

## Acceptance Criteria

- existing planning turns still behave normally when no observation work is active
- `observation` can become the primary routed work on operator turns when review pressure exists
- setup gating still outranks planning and observation routing
- high-value observation pressure can interrupt ordinary planning refresh work without breaking planning review flows
- `workflow_stage` remains readable without becoming the real router
- setup state, assets, work items, schedules, and signals become the visible continuity sources behind routing decisions
- legacy stage-only sessions still remain serviceable through compatibility backfill during migration

## Validation

- orchestrator tests for route priority between setup, observation, review-pending planning work, and normal planning work
- tests proving operator turns can execute observation review through the shared bounded path
- tests proving `workflow_stage` summaries remain compatible even when observation is the active routed work
- regression tests for discovery, strategy, and account-planning flows with no live observation inputs
- focused tests proving scheduled observation runs and operator-turn observation runs share the same deterministic follow-on behavior

## Definition Of Done

This slice is complete when:

- campaign routing truthfully comes from setup readiness plus campaign work pressure
- observation review is a normal routed campaign concern rather than a worker-only side path
- the Telegram UX still reads cleanly through compatibility summaries
- the router no longer depends on stage progression to decide what happens next
