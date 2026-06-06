# Conversation Review Triggering

## Goal

Wire the existing engagement-brain seam into a real production worker path that can notice persisted conversation-review moments and run one bounded review safely.

This is the point where live conversation state stops being "review-ready in theory" and starts producing real background engagement-brain runs in production.

## Current Baseline

Already present in code:

- `telegram_app/engagement/` persists managed-account inbound events outside operator turns.
- `telegram_app/external_conversations/projector.py` already projects routed inbound events into durable conversation threads and marks fresh activity with `next_action_type="review_inbound"`.
- `telegram_app/external_conversations/timing.py` already persists one-at-a-time `follow_up_due_at` windows on conversations.
- `telegram_app/engagement_brain/coordinator.py` already knows how to review one conversation, evaluate queue-time policy, and enqueue an allowed live action.
- `telegram_app/live_execution/service.py` already opens later follow-up windows after successful outbound sends and consumes a due follow-up window after a successful follow-up send.

Missing today:

- a production worker that discovers `review_inbound` moments outside tests
- a production worker that discovers due `follow_up_due_at` windows outside tests
- worker-safe durable claim semantics for one conversation review moment
- one deterministic rule for how a reviewed due window advances when the brain decides not to send anything
- trigger-aware idempotency so later follow-up reviews do not collide with earlier replies on the same conversation

Important current limitation:

- `telegram_app/external_conversations/manager.py` only uses an in-process `RLock` today. That is not enough for safe multi-process review claims because inbound listening, live execution, and the future review worker all mutate the same campaign conversation files from separate processes.

Relevant code touchpoints today:

- `telegram_app/external_conversations/models.py`
- `telegram_app/external_conversations/manager.py`
- `telegram_app/external_conversations/projector.py`
- `telegram_app/external_conversations/timing.py`
- `telegram_app/engagement_brain/coordinator.py`
- `telegram_app/live_execution/service.py`
- `server.py`

## Core Questions To Lock

This step should answer:

1. what exact persisted conversation moments are eligible for automatic review
2. which runtime component discovers those moments
3. how one worker claims a review moment without racing another worker
4. how retries behave when the worker crashes after claiming but before finishing
5. how a due follow-up window advances when the brain returns `wait`, `ignore`, or `escalate`
6. how trigger identity flows into queue idempotency and audit

## Recommended Direction

Use one dedicated conversation-review worker instead of widening the listener or scheduler.

Recommended shape:

- inbound listening should stay thin and deterministic: persist the event, project the conversation, stop
- follow-up due windows should stay conversation-local, not be translated into `ScheduleRecord`s
- one dedicated review worker should scan persisted conversation state, claim the next eligible review moment, invoke the existing coordinator, and persist trigger completion

Why this direction:

- it keeps LLM review out of the managed-account listener path
- it lets inbound and due follow-up reviews share one claim model and one execution loop
- it avoids abusing scheduled work for high-churn conversation-local timing
- it matches the existing dedicated-worker pattern already used for scheduled work and live execution

## Locked Runtime Behavior

### Trigger Sources

The first production cut should support exactly two automatic trigger types:

1. `inbound`
   Discovered when a conversation is marked `next_action_type="review_inbound"` and the latest inbound event has not already been reviewed.
2. `follow_up_due`
   Discovered when a conversation has a non-null `follow_up_due_at` that is now due and that exact due window has not already been reviewed.

The runtime may also record `operator_request` later, but manual review triggering is not required to land this slice.

### Trigger Discovery Rule

Eligibility should come from durable conversation state only.

Recommended first-cut rules:

- only consider conversations whose status is `active`
- skip any conversation that already has a non-expired active review claim
- prefer fresh inbound review over due follow-up review on the same conversation if both appear eligible
- never re-run the same persisted trigger once that exact trigger key was already completed

Recommended deterministic trigger keys:

- inbound: `inbound:{last_event_id}`
- follow-up due: `follow_up:{follow_up_window_type}:{follow_up_due_at.isoformat()}:{follow_up_attempt_count}`

These keys should become the single idempotency identity for one review moment.

### Why Not Trigger Directly From The Listener

Do not call the engagement brain from `ManagedAccountEventListener`.

The listener should remain responsible only for:

- inbound normalization
- dedupe and persistence
- conversation projection

Running the brain directly in the listener would couple live MTProto polling to LLM latency, make retries harder to reason about, and create a second execution path separate from due follow-up handling.

### Why Not Route Due Follow-Ups Through `ScheduleManager`

Do not convert `follow_up_due_at` windows into campaign schedules in this slice.

Those windows are:

- conversation-local runtime pressure
- high-cardinality
- short-lived
- already persisted on the conversation record itself

They are different from operator-authored recurring planning schedules and should keep their own narrow worker path.

## Concrete Runtime Shape

Use one narrow review-trigger seam adjacent to the existing coordinator and extend conversation state with review bookkeeping.

Recommended first files:

- `telegram_app/engagement_brain/review_dispatcher.py`
  Own trigger discovery, claim, coordinator invocation, and completion handling.
- `telegram_app/engagement_brain/review_runner.py`
  Own the dedicated worker loop, mirroring `live_execution/runner.py`.

Recommended conversation-state extensions:

- extend `telegram_app/external_conversations/models.py` with review-claim and review-cursor fields
- extend `telegram_app/external_conversations/manager.py` with worker-safe claim and completion helpers

Why keep the seam here:

- the trigger worker is a runtime wrapper around the existing engagement-brain coordinator
- review discovery should stay close to the reasoning seam it feeds
- conversation state and timing still remain owned by `external_conversations/`

## Implementation Track

### Conversation Review Trigger Contract

Introduce one small trigger model rather than passing raw conversation state around.

Recommended trigger fields:

- `campaign_id`
- `conversation_id`
- `trigger_type`
- `trigger_source`
- `trigger_key`
- `eligible_at`
- `summary`

Recommended first values:

- `trigger_type`: `inbound`, `follow_up_due`
- `trigger_source`: `review_inbound`, `scheduled_group_follow_up_window`, `scheduled_dm_follow_up_window`

This object should be what the worker claims and what the coordinator receives for audit and idempotency.

### Durable Claim And Completion State

Persist review claim state on the conversation record itself.

Recommended claim fields:

- `review_claimed_by`
- `review_claimed_at`
- `review_claim_expires_at`
- `review_claim_trigger_key`

Recommended completion fields:

- `last_completed_review_trigger_key`
- `last_completed_review_at`
- `last_completed_review_source`
- `last_completed_review_disposition`
- `last_completed_review_summary`
- `last_completed_review_action_id`

Recommended claim rules:

1. claims are conversation-scoped, not trigger-scoped
2. only one active review claim may exist per conversation at a time
3. expired claims may be reclaimed safely
4. completion clears the active claim and records the completed trigger key
5. a later inbound event naturally creates a new inbound trigger key and becomes eligible again

This is the minimum durable contract needed to prevent overlapping review of the same conversation while still allowing new later moments to run.

### Worker-Safe Persistence Hardening

Before review claims are added, harden `ExternalConversationManager` for cross-process writes.

Recommended first-cut approach:

- add a filesystem guard under the campaigns root, similar to `LiveExecutionManager`
- ensure claim and save mutations run under that guard
- keep the current JSON file layout for now instead of redesigning storage

Without this, separate listener, review-worker, and live-execution processes can overwrite each other's conversation updates.

### Claiming The Next Eligible Review

Add one manager-level helper similar in spirit to `LiveExecutionManager.claim_next_ready()`.

Recommended helper:

- `claim_next_review(owner_id, claim_ttl_seconds, now)`

Recommended behavior:

1. scan campaign conversation state across campaigns
2. normalize any expired claim back to unclaimed
3. skip non-`active` conversations
4. derive the best current candidate trigger for each conversation
5. skip candidates whose trigger key already equals `last_completed_review_trigger_key`
6. choose the oldest eligible trigger by `eligible_at`
7. persist the claim fields atomically and return the claimed trigger

This keeps review selection deterministic and horizontally safe.

### Coordinator Contract Update

Extend `EngagementBrainCoordinator.review_conversation()` to accept trigger metadata.

Recommended signature shape:

- `review_conversation(campaign_id, conversation_id, *, trigger=None)`

Recommended behavior changes:

- include the trigger key in the live-action idempotency key material
- include trigger metadata in `approval_context`
- return enough result data for the dispatcher to persist completion state cleanly

This matters because the current idempotency key only uses:

- campaign id
- conversation id
- `last_event_id`
- action type
- draft text

That is not enough once follow-up due reviews exist. Two later reviews on the same conversation can legitimately reuse the same `last_event_id` and even the same text.

### Dispatch Flow

The dedicated review dispatcher should own the full background path.

Recommended first flow:

1. claim the next eligible review trigger
2. load the current conversation
3. run the engagement-brain coordinator with the claimed trigger
4. persist trigger completion fields from the returned result
5. apply any trigger-specific follow-up cleanup
6. log one compact review outcome summary

Recommended outcome handling:

- `ENQUEUED`
  Persist completion and leave due follow-up windows intact so the existing live-execution success path can consume them when the actual send succeeds.
- `NO_ACTION`
  Persist completion. If the source trigger was `follow_up_due`, consume or clear that due window immediately so the same overdue window does not keep retriggering.
- `BLOCKED_BY_POLICY`
  Persist completion and keep the blocked-vs-no-action distinction in durable summary fields.
- `None` or missing context
  Release the claim with a retry-safe summary. Do not silently mark success.

### Due Follow-Up Advancement Rules

Lock explicit rules for what happens after a due-window review.

Recommended first-cut rules:

1. if a due follow-up review enqueues a live action, leave the due window in place for the current `LiveExecutionService` success path to consume
2. if a due follow-up review does not enqueue anything, clear the due window immediately
3. do not automatically open a brand-new follow-up window after a no-send result in this slice
4. keep the existing "successful outbound send opens the next window" behavior unchanged

Why this direction:

- it prevents busy-loop review on one stale overdue window
- it avoids changing the already-landed timing policy more than necessary
- it keeps recurring no-send heuristics out of this readiness slice

### Observability

Persist enough state to explain what happened without adding a full metrics stack.

Recommended first-cut observability:

- store the last completed review source, disposition, action id, and summary on each conversation
- emit worker logs that include campaign id, conversation id, trigger key, and disposition
- make `policy_blocked` outcomes visibly distinct from `brain_wait` or `brain_ignore`

Optional later add-on if inspection proves awkward:

- append campaign-local `review-attempts.jsonl` records

## File-Level First Cut

The smallest practical coding slice should touch:

- `telegram_app/external_conversations/models.py`
  Add review claim and review completion fields.
- `telegram_app/external_conversations/manager.py`
  Add cross-process guard logic plus `claim_next_review()` and completion helpers.
- `telegram_app/external_conversations/timing.py`
  Add one helper for clearing a reviewed due window when no live send was queued.
- `telegram_app/engagement_brain/coordinator.py`
  Accept trigger metadata, widen approval-context audit, and widen idempotency-key material.
- `telegram_app/engagement_brain/review_dispatcher.py`
  Add the production trigger-discovery and review-execution path.
- `telegram_app/engagement_brain/review_runner.py`
  Add the dedicated worker loop.
- `server.py`
  Compose the review dispatcher/runner and add a worker flag such as `--run-conversation-reviewer`.

## Validation Plan

Add focused coverage before broader Telegram smoke testing.

Recommended test additions:

- `tests/test_conversation_review_triggering.py`
  Claim discovery, duplicate prevention, expired-claim retry, and due-window advancement rules.
- `tests/test_engagement_brain.py`
  Trigger-aware coordinator idempotency and review audit behavior.
- `tests/test_live_execution.py`
  Preserve the current follow-up-window consume-and-reopen behavior when a due review actually enqueues and later sends a live follow-up.

Minimum acceptance proof for this slice:

- one persisted inbound conversation moment can be claimed and reviewed by a background worker
- one due follow-up window can be claimed and reviewed by a background worker
- the same trigger key is not reviewed twice unless the first claim expires unfinished
- a due window that produces no queued send does not retrigger forever
- later follow-up reviews do not collide with earlier review idempotency on the same conversation

## Non-Goals

- redesigning engagement-brain reasoning policy
- redesigning the follow-up timing heuristics beyond advancing due-window state safely
- building operator-facing live review controls in this slice
- replacing conversation JSON storage with a database

## Acceptance Criteria

- inbound activity can trigger one bounded production review without manual orchestration
- due follow-up windows can trigger one bounded production review without manual orchestration
- duplicate reviews are prevented by durable claim and completion behavior
- follow-up due windows advance safely even when the brain decides not to send anything
- trigger-aware idempotency prevents accidental collision across repeated reviews on the same conversation
- focused coverage proves trigger discovery, idempotency, and retry-safe execution
