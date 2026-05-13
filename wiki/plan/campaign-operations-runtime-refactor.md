# Campaign Operations Runtime Refactor Plan

## Goal

Refactor the current stage-first Telegram runtime into a campaign operations runtime that matches [Campaign Operations Model](C:/Users/ravil/OneDrive/Desktop/tg-swarm/wiki/spec/campaign-operations-model.md).

This plan focuses on orchestration, control flow, work delegation, scheduling, and approval boundaries. It does not define the campaign memory storage model in depth; that is handled by [Campaign Memory Implementation Plan](C:/Users/ravil/OneDrive/Desktop/tg-swarm/wiki/plan/campaign-memory-implementation.md).

## Why This Plan Exists

The current runtime still carries a mostly consecutive workflow shape:

- intake
- discovery
- strategy
- account planning
- conversational review

That is useful for first-run planning, but it is not a strong long-lived operating model for agentic Telegram marketing.

The new spec requires the runtime to behave more like a campaign organization:

- the operator acts like a manager or team lead
- the orchestrator acts like a campaign manager
- specialists act like tactically autonomous workers
- campaigns persist across sessions
- recurring work is scheduled over time
- work is delegated as outcomes, not micromanaged as step lists

## Scope

This plan covers:

- runtime control-flow changes
- orchestrator responsibility changes
- specialist delegation boundaries
- work item introduction
- scheduling introduction
- session-to-campaign runtime behavior
- approval-boundary updates

This plan does not fully define:

- campaign workspace file layout
- Markdown memory conventions
- detailed campaign metadata persistence

Those are handled in the memory implementation plan.

## Current Runtime Shape

The current runtime is centered on:

- `server.py`
- `telegram_app/app_service.py`
- `telegram_app/orchestrator/orchestrator.py`
- `telegram_app/intake.py`
- `telegram_app/sessions/`
- `telegram_app/approvals/`

The current system persists:

- session state
- message history
- workflow snapshot
- workflow artifacts such as:
  - `campaign_brief`
  - `community_shortlist`
  - `strategy_playbook`
  - `account_assignment_plan`

This gives continuity, but it still makes the runtime think in terms of stage progression more than campaign operations.

## Refactor Objective

The runtime should stop treating the next stage as its main orchestration primitive.

It should instead treat:

- campaign attachment
- work items
- schedules
- campaign memory references
- approval-aware execution

as the primary operating units.

## One Operational State Model

The refactor should converge the runtime on one primary operational state model.

That model should be:

- campaign-centered
- asynchronous and non-linear
- driven by work items, schedules, memory, and approvals

Sessions should remain the operator interaction layer, not the core operational state container.

`workflow_snapshot` stages may remain temporarily as compatibility state on sessions, but they should not survive as the primary way campaign work is represented.

High-level labels like `setup`, `operating`, or `review` may still be useful as descriptive summaries, but they should not become a second authoritative state machine that competes with work items and schedules.

## Target Runtime Behavior

After this refactor:

1. Operator sessions attach to campaigns, and scheduled or background work resolves campaign context directly without requiring an active session.
2. The orchestrator may answer directly, create work items, refresh work items, or delegate work to specialists.
3. Specialists receive bounded goals and choose tactical substeps inside their domain.
4. Recurring schedules can trigger campaign work without requiring a fresh operator message or a session-owned workflow stage.
5. Risky execution remains routed through approval-aware boundaries.
6. Discovery, strategy, and account planning become recurring work families rather than one-shot pipeline stages.

## Design Constraints

The refactor should preserve these constraints:

- do not remove session continuity
- do not remove the orchestrator as the user-facing control point
- do not make sessions the container for asynchronous campaign work
- do not let schedules bypass approval-sensitive control
- do not force specialists to become dumb parameterized tools
- do not force the orchestrator to script every tactical detail
- do not require a large normalized database-first implementation

## Refactor Themes

### Theme 1: Session To Campaign Attachment

The runtime should attach operator sessions to campaigns without making campaigns depend on one active session.

This means:

- session creation may also create a campaign
- new operator messages may attach to an existing active campaign
- session state should carry campaign references
- the orchestrator should reason from campaign context, not only recent chat
- scheduled and background work should resolve campaign context directly

### Theme 2: Orchestrator As Campaign Manager

The orchestrator should shift from stage router to campaign manager.

The orchestrator should:

- interpret operator direction
- decide priorities
- create and assign work items
- trigger or refresh recurring work
- review specialist outputs
- resolve cross-domain conflicts
- escalate consequential decisions

The orchestrator should assign outcomes, not exact tactical scripts.

### Theme 3: Specialists As Tactical Workers

Specialists should own tactical decisions inside their domain.

This means:

- discovery chooses how to expand, refresh, or validate community coverage
- strategy chooses how to revise positioning or message framing
- account or execution planning chooses how to represent readiness, blockers, and pacing

Specialists should escalate:

- cross-domain conflicts
- risky execution proposals
- unclear strategic changes

### Theme 4: Work Items As The Main Delegation Primitive

The runtime should introduce a durable work item model.

At minimum, a work item should express:

- `work_item_id`
- `campaign_id`
- `owner_role`
- `goal`
- `constraints`
- `priority`
- `status`
- `due_at` or review timing
- `related_memory_refs`
- `result_summary`
- `escalation_reason`

The runtime does not need the final perfect schema immediately, but it does need a first durable form.

### Theme 5: Scheduling As A First-Class Runtime Concern

The runtime should support recurring campaign tasks such as:

- discovery refresh
- community revalidation
- weekly strategy review
- account-readiness review
- stale-work cleanup

Schedules should normally create or refresh work items.

Schedules should not directly perform risky external actions.

The first operational cut should use a dedicated scheduler worker rather than embedding a scheduler loop into every webhook or polling app instance.

That worker should hold a renewable lease in shared runtime state before dispatching due schedules so duplicate execution stays bounded even if multiple processes are running.

Schedule records should also be able to track simple health expectations and outcomes:

- evaluation metric
- minimum acceptable value
- consecutive misses
- auto-paused status after repeated misses

### Theme 6: Approvals Focused On Consequential Execution

The runtime should continue moving approvals away from normal planning.

Hard approval should be strongest around:

- community joins
- outreach
- posting
- member messaging
- account-risking external actions

Routine planning, review, memory maintenance, and scheduled reassessment should remain fluid.

## Target Runtime Control Flow

The refactored high-level flow should be:

1. Telegram receives an operator event or a scheduled runtime trigger fires.
2. If the trigger came from an operator turn, the app service resolves the current session and campaign context.
3. If the trigger came from a schedule or background process, the runtime resolves campaign context directly without requiring an operator session.
4. The orchestrator reads current campaign memory, work state, and pending approvals.
5. The orchestrator decides one of:
   - answer directly
   - create or refresh work items
   - delegate one work item to a specialist
   - summarize or review campaign status
   - escalate for approval
6. The specialist works inside scope and returns:
   - memory updates
   - work-item result updates
   - escalation
   - execution proposals when relevant
7. The orchestrator merges the outcome, schedules follow-up where useful, and responds to the operator when appropriate.

## File-Level Work Proposal

### New Runtime Areas

- `telegram_app/campaigns/`
- `telegram_app/work_items/`
- `telegram_app/scheduling/`

These should eventually handle:

- campaign resolution and attachment
- work-item persistence and lifecycle
- recurring schedule persistence and dispatch

### Existing Areas Likely To Change

- `telegram_app/app_service.py`
- `telegram_app/orchestrator/orchestrator.py`
- `telegram_app/orchestrator/context_builder.py`
- `telegram_app/intake.py`
- `telegram_app/models/session.py`
- `telegram_app/models/workflow.py`
- `telegram_app/sessions/session_manager.py`
- `telegram_app/approvals/`

## Phased Implementation

### Phase 1: Campaign-Aware Runtime Spine

Goals:

- add campaign references to session runtime state
- teach the app service and orchestrator to resolve campaign context
- keep the existing stage flow operational while campaign attachment is introduced

Expected code areas:

- session model
- session manager
- app service
- orchestrator context builder

### Phase 2: Work Item Introduction

Goals:

- add a first durable work-item model
- let the orchestrator create and update work items
- preserve compatibility with legacy stage-oriented specialist calls

Expected code areas:

- new work-item models and persistence
- orchestrator
- specialist invocation interface

### Phase 3: Specialist Delegation Refactor

Goals:

- shift specialist prompts and runtime contracts toward outcome-based delegation
- stop passing only “next stage” framing
- let specialists update tactical state and return bounded results

Expected code areas:

- orchestrator
- specialist agents
- prompts

### Phase 4: Scheduling Introduction

Goals:

- add a minimal schedule model
- allow schedules to create or refresh work items
- execute due schedules through a dedicated lease-protected scheduler worker
- let schedule-triggered work run the relevant specialist path rather than stopping at placeholder work-item creation
- record schedule outcomes and pause unhealthy recurring work after repeated misses
- keep execution actions approval-aware
- ensure schedule-triggered work runs against campaign context directly instead of relying on an active session

Expected code areas:

- new scheduling package
- scheduler worker / polling or job dispatch layer
- orchestrator entrypoints for scheduled work
- session lookup helpers used by background work while artifacts remain session-scoped

Current implementation note:

- the first cut is now in code
- `server.py --run-scheduler` runs a dedicated scheduler-only process
- due schedules are lease-protected to reduce duplicate dispatch across webhook, polling, or multiple runtime instances
- scheduled runs currently reuse the latest campaign session when they need access to session-scoped artifacts
- recurring discovery can now be measured against thresholds such as validated community count and auto-pause after consecutive misses

Remaining follow-up inside Phase 4:

- move more durable campaign knowledge out of session-scoped artifacts so scheduled work can operate without the latest-session bridge
- add orchestrator or specialist-authored schedule creation flows instead of relying only on manual/runtime-created schedules
- broaden outcome evaluation beyond the first discovery-focused metric shape when more recurring work families land

### Phase 5: Approval-State Migration

Goals:

- remove legacy hard approval usage for planning artifacts and conversational review checkpoints
- migrate any persisted `waiting_for_approval`, `community_shortlist`, `strategy_playbook`, and `account_assignment_plan` planning approvals into normal conversational review or explicit campaign-linked execution approvals
- ensure only consequential execution proposals create durable approval records going forward

Expected code areas:

- `telegram_app/approvals/`
- `telegram_app/sessions/`
- `telegram_app/orchestrator/`
- intake and compatibility migration helpers

### Phase 6: Stage Model Reduction

Goals:

- reduce dependence on rigid workflow stage progression
- reframe discovery, strategy, and account planning as recurring work families
- keep only the minimum stage or mode concepts needed for operator experience

Expected code areas:

- workflow snapshot handling
- orchestrator routing
- intake

## Compatibility Strategy

The refactor should not require a flag day rewrite.

Compatibility expectations:

- existing session flows should still run during the transition
- existing artifact generation can remain temporarily
- legacy `workflow_snapshot` stages can remain as compatibility views while work items are introduced
- legacy planning approval categories should be translated and removed during migration rather than preserved indefinitely
- prompts may temporarily support both old and new framing until runtime state catches up

## Validation

The runtime refactor should be considered ready when:

1. Sessions attach to campaigns reliably across restarts.
2. The orchestrator can create and track work items instead of only advancing stages.
3. Specialists can receive bounded goals without requiring micromanaged instructions.
4. Scheduled work can create or refresh campaign tasks without bypassing approval boundaries.
5. Planning-only review checkpoints no longer create durable approval state.
6. Risky execution still returns through explicit review paths.
7. Legacy stage-driven behavior continues to work during migration until its replacement is proven.

## Focused Test Tracks

- session-to-campaign attachment
- campaign-aware orchestrator routing
- work-item creation and updates
- specialist escalation behavior
- scheduled-work dispatch
- scheduled work without session dependency
- scheduler-worker lease behavior and duplicate-dispatch protection
- schedule outcome recording and auto-pause after repeated misses
- approval safety for risky execution proposals
- approval-migration cleanup for legacy planning approval records
- compatibility with existing discovery, strategy, and account-planning flows

## Non-Goals

This plan should not:

- solve full execution automation in one pass
- finalize every future specialist role
- require a large job-processing system before the first schedule support lands
- remove all workflow-stage language immediately if compatibility still needs it

## Recommended Delivery Order

1. Add campaign references to runtime state.
2. Add a first work-item model and persistence layer.
3. Make the orchestrator campaign-aware and work-item-aware.
4. Refactor specialist delegation contracts toward bounded tactical autonomy.
5. Add schedule persistence, dedicated scheduler dispatch, and lease protection.
6. Let scheduled work execute bounded specialist runs and record health outcomes.
7. Reduce stage-first routing after the new path is stable.

## Plain-Language Summary

This plan turns the runtime from a stage machine into a campaign manager.

The orchestrator should stop thinking mainly in terms of “what is the next stage?” and start thinking in terms of “what campaign work needs to happen now, later, and repeatedly?”

That means adding campaigns, work items, and schedules as first-class runtime concepts while keeping risky execution visible and approval-aware.
