# Managed Account Capability Expansion

## Goal

Expand the MTProto capability layer from basic search, join, read-history, and send-message primitives into the minimum account behavior surface needed for live engagement.

## North-Star Link

This workstream primarily supports:

- **Presence**
- **Engagement**
- **Interest Capture**

from [Campaign North Star](campaign-north-star.md).

## Why This Exists

The current capability layer is enough for planning plus basic writes, but a live engagement MVP needs richer account-side behavior to act like a controlled Telegram user.

The missing surface is no longer theoretical. The repo already has:

- approval-aware `send_message(...)` in `telegram_app/capabilities/mtproto/impl_messaging.py`
- compact outbound message reference persistence in `telegram_app/engagement/`
- inbound reply matching in the managed-account listener

What it does not yet have is the next layer needed for reply-driven runtime behavior:

- reply-specific outbound sends
- explicit read-state actions
- bounded account-scoped dialog context reads
- lightweight dialog cleanup actions
- normalized result shapes for those newer operations

## Scope

- reply-to-message send support
- dialog and message read-state support
- bounded inbox and thread context reads
- dialog state actions such as archive or leave
- enough target inspection to build safe context before replying
- compact outbound message reference persistence so inbound listeners can identify replies to managed-account messages

## Deliverables

- messaging capability support for replies to specific messages
- message or dialog read-state methods
- dialog listing or targeted inbox inspection helpers
- conversation history helpers for reply context
- minimal dialog-management methods needed for cleanup and operator control
- outbound message reference recording tied to successful visible sends

## Current-State Snapshot

Today the implementation already proves a few important MVP assumptions:

- visible outbound sends already flow through one audited MTProto wrapper
- successful sends already write a compact outbound reference keyed by `account_id`, `chat_id`, and `message_id`
- inbound group replies can already be recognized when they target a managed-account message

That means this workstream should not try to redesign the whole capability layer.

It should extend the already-working messaging path carefully enough that the live execution worker can call richer account actions through the same normalized wrapper style.

## Recommended Runtime Boundary

For the first MVP cut, keep this work inside the existing messaging-side capability seam rather than introducing a brand-new top-level runtime facade for every new action.

Recommended direction:

- extend `telegram_app/capabilities/messaging.py`
- extend `telegram_app/capabilities/mtproto/impl_messaging.py`
- keep shared audit, retry, and account-health handling in one implementation family
- keep result payloads domain-shaped enough that a later `dialog` split stays easy if the surface grows

This is the smallest change that respects the current runtime shape.

Avoid for now:

- introducing a separate orchestrator-owned dialog service
- letting specialists or workers call raw Telethon methods directly
- duplicating send logic across `send_message(...)` and `send_reply(...)`

The likely internal shape is:

- one shared private send helper
- explicit public methods such as `send_message(...)` and `send_reply(...)`
- read and dialog helpers that reuse the same audit and normalization conventions

This preserves clear action semantics without widening the runtime more than the MVP needs.

Implementation decision for MVP:

- keep `send_reply(...)` as a separate public capability method
- do not widen public `send_message(...)` with a `reply_to_message_id` parameter in this MVP cut
- allow the implementation to share one lower-level private helper that accepts reply metadata internally

This keeps execution policy explicit. A queued plain send and a queued reply are not the same operational intent even if they share transport mechanics underneath.

## Relationship To Live Execution Runtime

This workstream is downstream of the execution core even though the two plans are tightly related.

The executor should land first because it defines:

- the durable action model
- the worker that owns visible Telegram writes
- the retry and idempotency rules
- the conversation updates that happen after successful execution

Then this capability-expansion workstream can add the missing MTProto operations that the executor needs for the full action set.

In practice, the dependency break should be:

1. finish the live-execution core and worker path using today's safe capability methods
2. add the reply, read-state, and dialog-context operations below that worker
3. wire the new operations into queued action dispatch, not directly into the orchestrator turn path

## Minimum MVP Additions

- `send_reply(account_id, chat_id, reply_to_message_id, text, ...)`
- `mark_read(account_id, chat_id, message_id=None)`
- `get_dialog_history(account_id, peer_id, limit=...)`
- `list_recent_dialogs(account_id, limit=...)`
- `leave_dialog(account_id, peer_id)` or equivalent cleanup path
- a compact outbound message index that records successful visible sends by `account_id`, `chat_id`, and `message_id`

## Recommended Build Order

Build this workstream in four slices so write behavior, context reads, and cleanup actions do not blur together.

### Slice 1: Reply-Safe Outbound Send Extension

- add explicit public `send_reply(...)` support rather than hiding replies behind a generic send-only interface
- keep a shared internal send implementation so approval, audit, retries, and account-health updates remain unified
- preserve explicit action metadata so results distinguish `send_message` from `send_reply`
- keep outbound reference recording on successful visible sends so later inbound replies remain matchable
- allow execution callers to pass through `campaign_id` and approval metadata the same way current send paths already do

Recommended result fields:

- `account_id`
- `chat_id`
- `message_id`
- `reply_to_message_id` when relevant
- `action`
- `attempts`
- `wait_seconds` when relevant
- `source`
- approval and audit metadata consistent with the current send path

Locked MVP API shape:

- `send_message(account_id, chat_id, text, *, approval_context=None)` stays the plain visible-send path
- `send_reply(account_id, chat_id, reply_to_message_id, text, *, approval_context=None)` is the reply-specific visible-send path
- internal implementation may still route both methods through one shared helper so retries and audit behavior stay identical where appropriate

### Slice 2: Read-State Support

- add `mark_read(account_id, chat_id, message_id=None)`
- treat read-state actions as auditable light writes rather than invisible internal bookkeeping
- return normalized result metadata instead of raw Telethon objects
- preserve failure classification for flood-wait, permission, and peer-resolution problems

This is important because the runtime will need to distinguish:

- reply was sent successfully
- reply was sent and the thread was marked read
- reply failed but read-state was never changed

### Slice 3: Bounded Dialog Context Reads

- add `get_dialog_history(account_id, peer_id, limit=...)` for grounded reply context
- add `list_recent_dialogs(account_id, limit=...)` for inbox or cleanup workflows
- keep limits small and explicit so prompt builders do not accidentally load full account history
- normalize message fields for later policy and reply-construction paths

Recommended message fields:

- `message_id`
- `chat_id`
- `sender_id`
- `text`
- `date`
- `reply_to_message_id` when present
- lightweight delivery or read metadata only if it is easy to return consistently

These read helpers should stay account-scoped and capability-level. They should not mutate campaign conversation state directly.

Locked read-side contract:

- keep existing `read_messages(chat_id, limit=...)` behavior as the simpler discovery-oriented read helper that uses the default read account
- do not reuse `read_messages(...)` as the live-engagement reply-context primitive
- all live-engagement dialog or reply-context reads should be explicit about `account_id`
- `get_dialog_history(account_id, peer_id, limit=...)` becomes the canonical reply-context read for execution and policy paths
- `list_recent_dialogs(account_id, limit=...)` becomes the canonical inbox-surface read for execution and operator-control paths

This preserves backward compatibility for existing discovery reads while making live-engagement behavior deliberate and account-scoped.

### Slice 4: Dialog Cleanup And Operator Control

- add `leave_dialog(account_id, peer_id)` or the narrowest equivalent cleanup action
- keep the first cut focused on explicit operator or policy-driven cleanup, not autonomous churn
- ensure the action returns the same normalized failure shapes as other capability writes
- leave broader archive, pin, mute, or folder-management work for a later non-MVP phase unless execution proves a real need

Locked MVP behavior for `leave_dialog(...)`:

- the public method stays `leave_dialog(account_id, peer_id)`
- its responsibility is narrow: make the managed account leave or exit the target dialog cleanly when Telegram permits it
- the implementation may use different MTProto operations under the hood depending on peer type, but that backend variation should stay private
- success should cover both `left` and idempotent `already_not_participating` style outcomes
- failure should remain normalized for peer-resolution, permission, and flood-wait cases

Recommended result fields:

- `account_id`
- `peer_id`
- `action`
- `outcome`
- `wait_seconds` when relevant
- `source`
- optional compact target metadata such as resolved dialog type only if it is easy to return consistently

Do not let `leave_dialog(...)` silently archive instead of leaving. Archive or mute semantics should remain future work unless they are added as separate explicit methods.

## Conversation And Indexing Notes

Do not push campaign conversation updates down into the capability layer.

Keep responsibilities separate:

- capability layer executes Telegram actions and returns normalized outcomes
- engagement storage keeps the compact account-scoped outbound reference index
- external conversation state keeps campaign-scoped thread posture and `last_outbound_*` fields
- the live execution worker applies successful execution outcomes back to campaign conversation state

This separation avoids making the capability layer responsible for campaign memory semantics.

## Result Normalization Expectations

All new capability methods should preserve the same operational shape as current join and send methods.

At minimum they should:

- return `CapabilityResult`
- classify success versus failure cleanly
- include a stable `action` value in audit metadata
- preserve `wait_seconds` when Telegram rate-limits the action
- update account health or cooldown state when the failure meaningfully affects future action safety
- avoid leaking raw Telethon entities upward as the public contract

If the implementation needs richer debug detail, keep it under structured `data` or `audit` fields rather than changing the public shape per method.

## Not Required For First MVP

- media composition
- profile mutation
- advanced reaction workflows
- story interactions
- broad social automation
- full transcript persistence in capability results
- a separate `dialog` runtime package before the current messaging-side seam proves insufficient

## Acceptance Criteria

- the runtime can reply to a specific inbound group or DM message
- the runtime can mark handled dialogs or messages as read
- the runtime can fetch enough recent context to build a grounded reply
- capability results preserve audit metadata and normalized failure shapes
- successful outbound sends leave enough structured evidence for the inbound listener to recognize later group replies
- the live execution worker can call these operations without bypassing its queue, retry, or idempotency rules

## Validation Focus

The smallest useful validation set for this workstream should include:

- unit tests for reply-send success, approval failure, and rate-limit failure
- unit tests for outbound reference recording after reply sends, not only plain sends
- unit tests for `mark_read(...)` result normalization and failure handling
- unit tests for bounded dialog-history and recent-dialog listing shapes
- focused integration-style tests proving a reply-driven action can update outbound evidence without breaking inbound listener matching

Live Telegram validation should stay tightly controlled and happen only after the executor can call the new methods through the normal worker path.

## Dependencies

- execution runtime
- engagement reply policy
- safety rules
