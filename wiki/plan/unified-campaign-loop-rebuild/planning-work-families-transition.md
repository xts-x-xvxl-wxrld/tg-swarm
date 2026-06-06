# Planning Work Families Transition

## Goal

Turn discovery, strategy, and account planning from the apparent architecture of the runtime into campaign-owned work families that operate inside one longer-lived outreach loop.

## Why This Needs Its Own Slice

This is the control-plane transition at the heart of the rebuild.

Without it, the runtime still behaves like:

- setup
- discovery
- strategy
- account planning
- done

The single-loop architecture needs it to behave like:

- campaign created or resumed
- orchestrator selects the highest-priority campaign work
- specialists execute bounded work items
- live execution produces signals
- observation and schedules refresh campaign priorities
- orchestrator selects the next campaign work again

## Core Shift

The main change is not removing the existing specialists. It is changing what owns them.

Today they still read like workflow stages.

In the rebuilt loop they should behave as:

- `discovery` work family
- `strategy` work family
- `account_planning` work family

Each one should be:

- created from campaign needs
- persisted as campaign work items
- resumable across turns and restarts
- schedulable when recurring review is useful
- re-prioritizable when live campaign pressure changes

## Scope

- define discovery, strategy, and account planning as campaign work families first and workflow stages second
- make work items the durable execution unit for planning activity
- make schedules the recurring trigger for re-running planning work when needed
- keep specialist outputs as artifacts or summaries, but stop treating artifact completion as campaign completion
- preserve current operator-facing stage summaries as compatibility views only

## Current Runtime Baseline

The runtime already has part of the needed shape:

- `telegram_app/work_items/manager.py` owns durable campaign work items
- `telegram_app/scheduling/manager.py` owns recurring campaign schedules
- `telegram_app/orchestrator/orchestrator.py` already prefers the primary open work item before falling back to pure `workflow_stage`
- scheduled work already creates or refreshes work items before running specialists

What is still stage-shaped:

- the default goals and review prompts still assume a linear `discovery -> strategy -> account_planning` handoff
- approval and review handlers still auto-advance to the next planning family as though the stage flow is the authority
- compatibility helpers still backfill work items directly from `workflow_stage`
- `workflow_stage` and artifact presence still carry too much meaning about what should happen next

This plan is the implementation bridge between that partially migrated runtime and the true campaign-loop model.

## Control-Plane Model

The campaign loop should be driven by these durable control objects:

- campaign state
- open work items
- active schedules
- current setup readiness
- current observation pressure
- campaign memory and signals

The loop should not be driven by a one-way stage machine.

## Target Runtime Rules

- a campaign may have zero, one, or several open planning work items at the same time
- each planning family should be reopenable without resetting the whole workflow
- completion of one work item should update campaign state, not implicitly end the planning loop
- approval of one planning artifact should create or refresh follow-on work only when the campaign actually needs it
- recurring schedules should refresh planning work through work items, not by jumping the session to a synthetic stage
- `workflow_stage` should be computed as a readable compatibility summary of the current campaign posture

## Work Family Contract

Each planning family should share one runtime contract:

- one or more durable `WorkItemRecord`s represent the bounded planning task
- the work item goal explains the current campaign need, not just the historical next stage
- `result_summary` explains what changed or what is waiting for review
- related artifact refs and memory refs carry continuity between turns
- review acceptance resolves the current work item outcome but does not by itself define the next routed work
- deterministic runtime code decides whether downstream work should be created, refreshed, reprioritized, or left alone

Recommended additions to the work-item contract for implementation:

- `trigger_source` or equivalent metadata for `operator`, `schedule`, `observation`, or `compatibility_backfill`
- `refresh_reason` or equivalent short text for why a previously completed family reopened
- `context_refs` or equivalent structured refs for the artifacts, setup facts, assets, or signals that justified the work

These fields do not need to be perfect on the first pass, but the runtime needs enough metadata to distinguish first-run planning from refresh work.

## Work Family Responsibilities

### Discovery

- validate seed groups
- find additional communities
- refresh community evidence when stale
- produce or update shortlist artifacts when needed
- complete when the current discovery pass has a reviewable shortlist or a bounded reason it cannot progress
- reopen when setup changes, discovery evidence ages out, strategy requests new sourcing, or observation pressure suggests the community mix is wrong

### Strategy

- translate current campaign context and current discovery evidence into an engagement plan
- refresh or narrow strategy when campaign conditions materially change
- respond to observation pressure or scheduled reviews
- complete when the current playbook is reviewable and tied to a specific discovery state
- reopen when approved discovery inputs materially change, live signals invalidate assumptions, or scheduled review says the plan is stale

### Account Planning

- map strategy to the current managed-account roster
- distinguish executable work from blocked work
- refresh assignments when account posture or community posture changes
- complete when the current assignment plan is reviewable and clearly separates ready, blocked, and deferred work
- reopen when strategy changes, account inventory or health changes, or campaign observation indicates assignment drift

## Dependency And Refresh Rules

Follow-on work should be explicit and need-based:

- accepted discovery should normally create or refresh strategy work if strategy is missing or stale
- accepted strategy should normally create or refresh account-planning work if assignments are missing or stale
- refreshed discovery should be able to lower confidence in existing strategy and account-planning outputs without deleting them immediately
- refreshed strategy should be able to reopen account-planning work without pretending the campaign returned to an earlier stage
- operator feedback may reopen one work family while leaving others completed until deterministic invalidation rules say otherwise

Recommended first invalidation rules:

- strategy becomes stale when a newer approved shortlist materially changes target communities
- account planning becomes stale when a newer approved strategy changes targeting or posture
- account planning may also become stale when managed-account inventory, rate limits, or posture constraints change
- discovery may become stale on a time cadence or when the operator changes seed communities or campaign objective

## Persistence Direction

- work items become the main durable planning queue
- schedules become the recurring planning trigger
- artifacts remain outputs and compatibility surfaces
- `workflow_stage` remains a summary for operator comprehension

This means a completed strategy artifact does not mean the campaign is finished. It means a bounded strategy work item completed and the campaign can continue.

## Implementation Tracks

### 1. Work-Item Semantics

Primary files:

- `telegram_app/models/work_item.py`
- `telegram_app/work_items/manager.py`

Implementation direction:

- preserve the existing bounded work-item shape
- add only the minimal metadata needed to explain first-run versus refresh planning
- add manager helpers for finding the latest work item by `work_type`, active status, and freshness relationship
- keep one active item per `(campaign_id, work_type, schedule_id)` slot unless there is a strong reason to support parallel items of the same family

### 2. Orchestrator Routing And Review Handling

Primary file:

- `telegram_app/orchestrator/orchestrator.py`

Implementation direction:

- replace stage-minded helper naming and assumptions with work-family language where practical
- stop treating review acceptance as a hardcoded instruction to immediately run the next family
- centralize follow-on creation in one deterministic helper that evaluates campaign needs after a work item is completed or reopened
- keep compatibility routing only as a migration bridge for old sessions that still lack campaign-native work items
- keep `_set_workflow_stage(...)` but downgrade it to summary projection instead of routing authority

Concrete runtime changes:

- introduce one helper that computes the next planning actions after a work item outcome
- make discovery, strategy, and account-planning review handlers call that helper instead of directly chaining to the next specialist
- make scheduled planning runs use the same follow-on helper so operator turns and worker turns stay aligned
- ensure `primary_work_item_id` in the workflow snapshot reflects the actual routed item, not a stage guess

### 3. Specialist Contract And Prompt Inputs

Primary files:

- `agents/discovery/agent.py`
- `agents/strategy/agent.py`
- `agents/account_manager/agent.py`
- `prompts/discovery.md`
- `prompts/strategy.md`
- `prompts/account_manager.md`
- `telegram_app/orchestrator/context_builder.py`

Implementation direction:

- pass the current work-item goal, refresh reason, and relevant context refs into specialist prompts
- keep specialists focused on producing the best bounded planning result for the current work item
- avoid making specialists responsible for cross-family invalidation or schedule creation
- enrich runtime context so prompts can tell whether they are producing a first draft, a refresh, or a review-driven revision

### 4. Schedule-Driven Planning Refresh

Primary files:

- `telegram_app/models/schedule.py`
- `telegram_app/scheduling/manager.py`
- `telegram_app/scheduling/dispatcher.py`

Implementation direction:

- use schedules to create or refresh planning review work, not to simulate stage transitions
- allow planning-family schedules such as periodic discovery refresh, strategy review cadence, or account-roster reassessment
- keep schedule outcome summaries compact so they can justify why a planning family was reopened
- make schedule-created work items look the same as operator-created ones except for origin metadata

### 5. Compatibility Projection

Primary files:

- `telegram_app/orchestrator/orchestrator.py`
- `telegram_app/app_service.py`
- `telegram_app/orchestrator/context_builder.py`

Implementation direction:

- keep Telegram-facing summaries readable while campaign-native routing takes over
- map active work families into a small set of summary postures for `workflow_stage`
- prefer summary text like `discovery under review`, `strategy refresh in progress`, or `account planning blocked by account posture` over pretending the session is simply at one irreversible stage
- preserve existing artifact consumers during migration

## Suggested Delivery Breakdown

### Slice A: Baseline Inventory And Helper Extraction

- identify every place where the runtime still assumes linear planning progression
- extract shared helpers for `complete`, `reopen`, `refresh`, and `create_follow_on_work`
- keep behavior the same at first while reducing duplicated stage logic

### Slice B: Discovery No Longer Owns The Whole Workflow

- change discovery approval handling so accepting a shortlist resolves discovery first
- create or refresh strategy work through deterministic follow-on logic
- leave room for discovery to reopen later without stage-reset semantics

### Slice C: Strategy Becomes Refreshable Campaign Planning

- change strategy acceptance so it resolves strategy work rather than meaningfully "moving the workflow forward"
- reopen strategy from discovery change, observation pressure, or scheduled review without pretending the campaign has restarted
- create or refresh account-planning work only when the new strategy outcome warrants it

### Slice D: Account Planning Stops Implying Campaign Completion

- treat accepted account planning as one completed planning outcome, not the end of the campaign
- keep or create recurring reviews for account posture changes where useful
- project a compatibility summary that says the current plan is ready rather than that the campaign is over

### Slice E: Schedule-Owned Refresh Rules

- add planning review schedules where they help campaign continuity
- ensure due schedules reopen or refresh existing planning work instead of spawning confusing duplicates
- verify worker-driven refresh behavior matches operator-turn behavior

### Slice F: Compatibility Cleanup

- narrow stage-backfill logic to genuinely old sessions only
- simplify prompt instructions that still describe the runtime as a one-way planning ladder
- keep operator UX stable while removing stage-first decision authority

## Concrete File-Level Work List

- `telegram_app/orchestrator/orchestrator.py`
  Convert review handlers and follow-on routing from stage chaining to work-family outcome handling.
- `telegram_app/models/work_item.py`
  Add the minimum metadata needed to explain refresh origin and context.
- `telegram_app/work_items/manager.py`
  Add helpers for latest-by-family, stale-or-refreshable lookup, and safe reopen semantics.
- `telegram_app/orchestrator/context_builder.py`
  Expose active work-family status and refresh context more explicitly to prompts.
- `prompts/orchestrator.md`
  Teach the orchestrator to treat planning families as campaign-owned bounded work, not the campaign architecture itself.
- `prompts/discovery.md`, `prompts/strategy.md`, `prompts/account_manager.md`
  Clarify first-run versus refresh behavior and remove language that implies final completion of the campaign.
- `tests/`
  Add routing, refresh, review, and schedule-regression coverage around the new control-plane rules.

## Migration Rules

- keep current discovery, strategy, and account-planning specialists
- keep current artifact views where they still help prompts and Telegram summaries
- stop using stage progression as the main source of authority for what happens next
- prefer work-item status, review status, and campaign pressure when deciding what to run

Recommended migration constraints:

- do not delete `workflow_stage` until all Telegram-facing summaries have a clear replacement
- do not require a schema rewrite of historical work-item files for the first cut; prefer additive fields with tolerant reads
- do not make schedule creation mandatory for every campaign before the work-family model is useful
- do not couple observation work to this slice beyond the refresh hooks it will eventually need

## Acceptance Criteria

- campaigns can carry more than one open or recurring planning concern over time
- discovery, strategy, and account planning can be reopened or refreshed without awkward stage resets
- planning artifacts remain useful without implying the campaign loop has ended
- work items and schedules, not stage progression, become the normal trigger for subsequent planning work
- accepting account planning no longer implies the campaign itself is complete
- scheduled refreshes and operator-triggered refreshes converge on the same work-family lifecycle
- old sessions without campaign-native planning work still remain serviceable during migration

## Validation

- orchestrator tests for selecting planning work from open work items instead of only stage state
- tests for reopening or refreshing discovery, strategy, and account-planning work after prior completion
- regression tests proving the current operator-facing summaries still make sense in Telegram
- tests for approval acceptance creating or refreshing follow-on work without hardcoded stage jumps
- tests for account-planning acceptance leaving the campaign operational instead of terminal
- scheduled-work tests proving refresh runs reuse the same lifecycle helpers as operator turns

## Definition Of Done

This slice is ready to hand off to the later observation-routing work when:

- all three planning families can be created, completed, reopened, and refreshed as campaign-owned work
- follow-on planning decisions come from deterministic campaign-need helpers rather than stage chaining
- `workflow_stage` remains readable but no longer decides what work runs next
- the runtime can truthfully describe the campaign as continuing after the first account plan is approved
