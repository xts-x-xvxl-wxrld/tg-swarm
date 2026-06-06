# Plan Activation Contract

## Goal

Define the first-class runtime bridge between approved account planning output and campaign-owned live execution state.

This is the point where the planning control plane stops being "ready in theory" and starts producing durable live work the execution runtime can own.

## Current Baseline

Already present in code:

- account planning can produce execution-shaped assignments and draft `message_text`
- campaign work items and schedules already persist under `telegram_app/work_items/` and `telegram_app/scheduling/`
- live execution already has durable queueing and policy checks under `telegram_app/live_execution/`

Missing today:

- one explicit activation contract
- one durable object model for prepared live execution state
- one deterministic rule for what happens when the operator revises a plan after activation

Relevant code touchpoints today:

- `telegram_app/orchestrator/orchestrator.py` approves account plans conversationally, but stops at "ready for execution"
- `agents/account_manager/agent.py` persists the latest account plan as a mutable session artifact
- `telegram_app/campaign_memory/manager.py` mirrors the latest plan artifact into the campaign workspace
- `telegram_app/live_execution/manager.py` and `telegram_app/live_execution/service.py` already own the actual queued-write path
- `tests/test_telegram_runtime_state.py` already proves plan approval does not send or queue anything by itself

## Core Questions To Lock

This step should answer:

1. what exact operator action activates execution
2. what durable records activation creates
3. how activation connects to one-time actions versus recurring execution
4. how later plan edits invalidate, replace, or preserve already-prepared records

## Recommended Direction

For the first cut:

- treat activation as an explicit operator action against an already approved account plan
- create campaign-owned prepared execution records before enqueueing visible MTProto writes
- keep recurring scheduling separate from one-time activation, but allow activation to reference schedule intent when it already exists
- make plan revision invalidate only records that have not yet been claimed or executed

This keeps the first slice narrow and reversible.

## Locked Operator Behavior

Activation should stay separate from conversational plan approval.

- `approve` keeps its current meaning: accept the current account-planning artifact as the latest approved plan
- `activate` should become the first explicit execution verb after approval
- approving a plan must still not enqueue or send anything
- activating a plan may materialize prepared execution records and enqueue only the actions that are runnable immediately

Recommended first-turn copy after approval:

- "The account assignment plan is approved. Say `activate` when you want me to prepare live execution from this revision."

Recommended copy after a later revision invalidates prepared state:

- "The approved plan changed after activation, so the unstarted prepared execution state was invalidated. Say `activate` to prepare the latest revision."

## Concrete Runtime Shape

Use one new narrow seam rather than widening the live execution queue itself.

Recommended package:

- `telegram_app/prepared_execution/`

Recommended first files:

- `models.py`
  Own durable prepared-batch and prepared-item records.
- `manager.py`
  Own campaign-backed JSON persistence plus lookup helpers.
- `service.py`
  Own activation, materialization, invalidation, and queue handoff rules.

Why this seam:

- `live_execution/` should remain the write queue and dispatch worker only
- account-plan activation is a control-plane translation step, not a queue concern
- keeping prepared state separate makes stale invalidation and operator inspection much easier

## Implementation Track

### Runtime Contract

Define one campaign-owned prepared execution batch plus one prepared item record per executable unit.

Recommended batch fields:

- `batch_id`
- `campaign_id`
- `source_plan_artifact_id`
- `source_plan_updated_at`
- `source_plan_fingerprint`
- `source_strategy_artifact_id`
- `activated_by_operator_id`
- `activated_at`
- `status`
- `summary`
- `schedule_intent_refs`
- `queued_action_ids`

Recommended batch statuses:

- `prepared`
- `partially_queued`
- `queued`
- `superseded`
- `completed`
- `cancelled`

Recommended prepared-item fields:

- `prepared_item_id`
- `batch_id`
- `campaign_id`
- `action_type`
- `account_id`
- `community_ref`
- `chat_id`
- `community_id`
- `source_assignment_index`
- `source_post_index`
- `day_offset`
- `time_window`
- `draft_text`
- `approval_context`
- `status`
- `live_action_id`
- `invalidated_reason`
- `result_summary`

Recommended prepared-item statuses:

- `prepared`
- `queued`
- `claimed`
- `executed`
- `superseded`
- `cancelled`
- `blocked`

### Source Revision Contract

The current workflow artifact model is mutable and not revisioned. Do not widen `WorkflowArtifact` yet for this slice.

Instead, treat the approved plan revision as:

- `source_plan_artifact_id`
- `source_plan_updated_at`
- `source_plan_fingerprint = sha256(normalized artifact.data JSON)`

This is enough to:

- prove exactly which plan revision activation used
- detect when the latest approved plan no longer matches the prepared batch
- keep the activation seam local instead of changing every artifact kind in the repo

### Materialization Rules

Translate the approved account plan deterministically.

Recommended first-cut rules:

1. Load the latest approved account-plan artifact for the campaign.
2. Refuse activation if no approved account plan exists yet.
3. Refuse activation if the plan has no runnable `scheduled_posts` with non-empty `message_text`.
4. Resolve community routing data from the latest shortlist or campaign memory:
   - prefer stored `community_id`
   - fall back to stored `handle`
   - keep `community_name` for operator-facing audit
5. Create one prepared item per scheduled post.
6. Store enough metadata to rebuild the originating assignment row without re-reading the LLM output.
7. Enqueue only immediately runnable items in this slice:
   - default rule: `day_offset == 0`
   - future-day items stay durable as `prepared` until a later scheduling slice owns them

Join handling should stay explicit but conservative:

- the prepared-item model should support `join_community`
- the first materializer does not need to synthesize join actions unless the community target is already resolvable and the runtime has a clear present need
- do not infer replies or DM sends from account-planning output in this slice

When queueing a prepared item into `live_execution`, include source metadata in the live action:

- `source_batch_id`
- `source_prepared_item_id`
- `source_plan_artifact_id`
- approval context showing this action came from explicit operator activation

This is needed for later audit and stale cancellation.

### Revision And Invalidation

Use revision invalidation rules that match the current live queue semantics.

When a newer approved account-plan fingerprint differs from the latest active prepared batch:

- mark the old batch `superseded`
- mark prepared items still in `prepared` as `superseded`
- cancel queued live actions only when they are still `queued` or `retry_wait`
- do not cancel actions already `claimed`, `running`, `succeeded`, `failed`, or `blocked`
- keep executed and already-claimed actions immutable for audit

This implies one small live-execution extension:

- add a safe cancellation helper in `telegram_app/live_execution/` that can cancel only not-yet-claimed actions by `source_prepared_item_id` or `source_batch_id`

The account-planning revision path should trigger invalidation when the operator asks for changes after an activated batch exists and a new plan artifact is saved.

### Operator Flow

Keep orchestrator behavior narrow and explicit.

Recommended first flow:

1. Operator approves account plan.
2. Orchestrator marks planning work complete but does not enqueue anything.
3. Orchestrator reports that the plan is approved and activation is now available.
4. Operator says `activate`.
5. Activation service materializes prepared execution state for the latest approved revision.
6. Orchestrator responds with a compact activation summary:
   - prepared item count
   - immediately queued count
   - future-held count
   - any blocked rows that need revision
7. If the operator later revises the plan, the orchestrator invalidates stale unstarted prepared state and asks for re-activation after the new revision is approved.

## File-Level First Cut

The smallest practical coding slice should touch:

- `telegram_app/orchestrator/orchestrator.py`
  Add explicit activation intent handling and post-approval messaging.
- `telegram_app/prepared_execution/models.py`
  Add durable batch and item models.
- `telegram_app/prepared_execution/manager.py`
  Add JSON-backed persistence under each campaign workspace.
- `telegram_app/prepared_execution/service.py`
  Add materialization, queue handoff, and invalidation logic.
- `server.py`
  Compose the prepared-execution manager/service into the runtime bundle.
- `telegram_app/live_execution/models.py`
  Add optional source-link fields for activation audit and stale cancellation.
- `telegram_app/live_execution/manager.py` or `telegram_app/live_execution/service.py`
  Add safe cancel-not-yet-claimed helper(s).

## Validation Plan

Add focused coverage before broad Telegram smoke testing.

Recommended test additions:

- `tests/test_prepared_execution.py`
  Batch creation, restart persistence, immediate queue handoff, and invalidation semantics.
- `tests/test_telegram_runtime_state.py`
  Approval remains non-executing, `activate` creates prepared state, and later revision demands re-activation.
- `tests/test_live_execution.py`
  Safe cancellation of queued-but-unclaimed actions linked to a superseded batch.

Minimum acceptance proof for this slice:

- approving an account plan still creates no live sends
- activating the approved plan creates durable prepared state linked to one exact plan fingerprint
- restart preserves that prepared state
- revising the plan supersedes only unstarted prepared work and queued-but-unclaimed actions

## Non-Goals

- designing the full conversion runtime
- solving all future recurring campaign automation in this slice
- broadening the planning specialists themselves unless activation requires minor contract cleanup

## Acceptance Criteria

- approved plans can become campaign-owned prepared execution state through one explicit runtime path
- prepared state is durable, inspectable, and linked to the source plan revision
- stale prepared state cannot continue silently after operator revisions
- focused coverage proves activation, restart persistence, and invalidation behavior
