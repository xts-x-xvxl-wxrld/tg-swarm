# Live Execution Runtime

## Goal

Create one consistent runtime path for live engagement actions such as joins, posts, replies, and read-state updates.

## North-Star Link

This workstream primarily supports:

- **Presence**
- **Engagement**
- **Conversion Progression**

from [Campaign North Star](campaign-north-star.md).

## Why This Exists

The current orchestrator plans work, but it does not own a restart-safe live action queue. A live engagement MVP needs a dedicated execution seam that can:

- accept normalized action requests
- apply policy and approval context
- perform the action through account capabilities
- record results
- retry or back off safely

## Scope

- normalized live action records
- queueing and dispatch for engagement actions
- idempotency keys and duplicate suppression
- retry, backoff, and terminal failure handling
- persistence of action outcomes as execution records

## Deliverables

- an execution service for managed-account actions
- persistent action records with lifecycle states
- dispatch workers for bounded live actions
- execution-result records linked to campaigns, accounts, and conversations

## Action Types For MVP

- join community
- send group message
- send group reply
- send DM reply after inbound contact
- mark dialog or message as read

## Core Design Notes

- Keep strategy out of this layer. By execution time, the runtime should already know the campaign, account, target, policy posture, and expected outcome.
- Route all visible account actions through one audited wrapper rather than bespoke per-feature paths.
- Make retries explicit and bounded. Silent repeated retries are too risky for user-account engagement.
- Keep live-action execution separate from operator planning work. Existing campaign `work_items` and schedules may request or enqueue live actions, but they should not also be the durable queue, retry ledger, or dispatch claim mechanism for those actions.
- Prefer a dedicated runtime seam such as `telegram_app/live_execution/` over widening the current orchestrator path. The execution worker should be the only place that turns a queued action into a visible Telegram write.

## Recommended Build Order

The practical build order for this workstream should be slightly narrower than the folder index implies.

Recommended sequence:

1. finish the execution-facing gaps in external conversation state, especially outbound linkage and helper methods that update `last_outbound_*`, `status`, and `next_action_*`
2. build the live execution core with durable action records, idempotency, retry state, and a worker entrypoint
3. wire the executor to the capability methods that already exist safely today, such as joins and basic sends
4. add the minimum capability expansion needed for real reply-driven execution, especially `send_reply(...)`, `mark_read(...)`, and bounded dialog-history reads
5. only then let later policy or specialist reasoning paths produce queued live actions automatically

This keeps the queue, worker, and result model stable before the runtime becomes more autonomous.

## Implementation Checklist

Build this workstream in three slices so we do not mix planning state, policy logic, and live Telegram writes.

### Slice 1: Execution Core

- create a dedicated runtime seam for live actions, preferably `telegram_app/live_execution/`
- define durable action records with:
  - stable `action_id`
  - `campaign_id`, `account_id`, and optional `conversation_id`
  - normalized `action_type`
  - compact `payload`
  - lifecycle status such as queued, claimed, running, succeeded, retry_wait, failed, blocked, or cancelled
  - idempotency key
  - retry count, next-attempt time, and terminal-failure reason
- define result or attempt records linked back to each action
- persist queue state in campaign-backed JSON files consistent with the repo's existing runtime style
- add lookup helpers for:
  - queued actions by campaign
  - queued actions by account
  - active actions by conversation
  - action lookup by idempotency key
- add conversation-facing helpers so successful outbound actions can update `last_outbound_at`, `last_outbound_message_id`, `status`, and `next_action_*`

### Slice 2: Worker And Current Capability Wiring

- add a dedicated worker entrypoint alongside the existing scheduler and engagement-listener workers
- implement claim-and-dispatch logic so only one worker instance handles a queued action at a time
- route joins and basic outbound sends through the existing audited membership and messaging capability wrappers
- record normalized outcomes for:
  - success
  - retryable rate limit or flood-wait
  - blocked or permission failure
  - terminal failure
- make retries explicit and bounded with stored next-attempt timestamps
- make duplicate dispatch harmless by enforcing idempotency before visible account actions are attempted
- ensure the executor, not the scheduler or orchestrator, is the only runtime path that performs visible live Telegram writes

### Slice 3: Reply And Read-State Unlocks

- add capability support for `send_reply(account_id, chat_id, reply_to_message_id, text, ...)`
- add capability support for `mark_read(account_id, chat_id, message_id=None)`
- add bounded dialog or thread-history reads for grounded reply construction
- add any outbound-message and conversation indexes needed so group replies and DM replies can be matched back to the correct thread deterministically
- enforce basic execution-time posture checks before dispatch:
  - DM reply allowed only when the conversation proves inbound-first DM contact
  - group reply uses the reply-specific action path, not a generic send
  - paused, blocked, escalated, or closed conversations do not dispatch automatically
  - account health and approval context are checked before the visible action

## Design Constraints

- Do not reuse `WorkItemRecord` as the live-action queue model. Work items represent planning or review units, while live actions need claim state, idempotency, retries, and execution outcomes.
- Do not let schedule dispatch perform direct joins or sends. Schedules may enqueue actions or refresh work, but the execution worker should remain the single external-write path.
- Keep `next_action_type` on the conversation record advisory. The durable source of truth for pending external behavior should be the queued execution action, not the conversation summary alone.
- Treat `send_group_reply` and `send_dm_reply` as separate action types even if they temporarily share implementation pieces. The policy and capability constraints differ enough that collapsing them too early will blur safety checks.

## Acceptance Criteria

- queued actions survive process restarts
- duplicate dispatch of the same action is prevented or becomes harmless
- successful, failed, rate-limited, and blocked actions are distinguishable in stored results
- DM replies cannot be sent through the wrong action type or wrong conversation posture

## Dependencies

- account event ingestion
- external conversation state
- capability expansion
- safety policy

## Dependency Note

There is a small implementation loop between this workstream and managed-account capability expansion.

The recommended way to break that loop is:

1. build the execution core first
2. wire it to the capability methods that already exist
3. then add the reply, read-state, and dialog-context capability additions needed for the full MVP action set
