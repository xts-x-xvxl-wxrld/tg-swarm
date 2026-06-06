# Inbound Account Event Ingestion

## Goal

Add a runtime seam that listens to inbound MTProto events for managed user accounts and converts them into durable engagement events.

## North-Star Link

This workstream primarily supports:

- **Interest Capture**
- **Learning**

from [Campaign North Star](campaign-north-star.md).

## Why This Exists

The current runtime only accepts operator-facing Bot API messages. A live engagement system also needs account-side visibility into:

- new group messages
- replies to managed-account messages
- inbound DMs
- edited or deleted messages when relevant
- membership or moderation signals

Without this layer, the system can send messages but cannot truly engage in conversations.

## Scope

- subscribe to inbound Telethon events per connected managed account
- normalize supported event types into internal runtime payloads
- persist an idempotent event cursor or equivalent resume state
- route inbound events into campaign-linked processing instead of the operator session path

## Recommended MVP Shape

The first implementation cut should create a new live-engagement seam under `telegram_app/engagement/`.

That seam should remain separate from:

- `TelegramUpdate`, which is currently operator-bot specific
- `TelegramAppService`, which is the operator-turn adapter
- the orchestrator turn path, which should not become the first ingress for raw MTProto events

The listener path for this workstream should be:

1. listen on managed-account MTProto events
2. normalize them into engagement event records
3. persist them durably with dedupe
4. mark whether they can be safely routed to a campaign
5. stop there for the first slice

The first slice should not yet generate replies, queue live sends, or invoke campaign reasoning directly from the listener loop.

## Event Model Direction

This workstream should introduce runtime models that are distinct from operator updates and distinct from execution-result records.

Recommended minimum record shape:

- stable `event_id`
- deterministic `dedupe_key`
- `account_id`
- `event_kind`
- `chat_id`, `peer_id`, `sender_id`
- `message_id` and `reply_to_message_id` when present
- compact `text`
- `occurred_at` and `recorded_at`
- optional `campaign_id`, `community_id`, and `conversation_id`
- routing status such as unresolved, routed, ignored, or unsupported
- compact `raw_summary` for debugging without bloating downstream prompt context

Recommended MVP event kinds:

- inbound DM
- group reply to a managed-account message
- message edited
- message deleted
- moderation or membership signal
- unsupported

## Persistence Strategy

The persistence split should follow the repo's broader file-backed runtime style.

Use JSON for compact durable state such as:

- listener state
- recent dedupe keys
- campaign or account routing indexes
- outbound message reference indexes

Use JSONL for append-only evidence such as:

- raw or normalized inbound event logs
- later operator-facing audit trails

Recommended account-scoped storage shape:

- `data/managed_accounts/<account_id>/listener-state.json`
- `data/managed_accounts/<account_id>/inbound-events.jsonl`
- `data/managed_accounts/<account_id>/outbound-message-index.json`

Campaign-scoped engagement projections can be added later after routing is reliable.

## Campaign-Safe Routing Rule

Inbound events should be account-scoped first, campaign-scoped second.

This is important because a managed account may eventually touch more than one campaign, community, or external conversation over time. The listener should not assume every event for an account automatically belongs in one campaign workspace.

The safe rule for MVP is:

1. persist every accepted inbound event under the managed account
2. attempt campaign resolution through explicit account-plus-target mapping
3. only project the event into campaign-linked processing when the mapping is confident
4. otherwise keep the event unresolved without discarding it

## Listener Service Shape

The listener service should be thin and long-lived.

Recommended responsibilities:

- connect one Telethon client per authenticated managed account
- subscribe to a small set of inbound event types
- normalize supported events
- persist deduped records
- persist enough routing metadata for later processing
- reconnect safely after transient failures

Recommended non-responsibilities:

- campaign strategy decisions
- reply drafting
- approval interpretation
- direct operator messaging

The listener lifecycle should run through a dedicated worker process rather than being hidden inside webhook or polling request handling.

## Outbound Reference Dependency

Reliable group-reply detection depends on knowing which outbound managed-account messages were previously sent by the runtime.

This workstream therefore depends on a compact outbound message reference index that records at least:

- `account_id`
- `chat_id`
- outbound `message_id`
- `sent_at`
- optional `campaign_id`

Without that index, the listener can still record inbound messages, but it cannot safely classify a message as a reply to one of our managed-account posts.

## First Implementation Slice

Build the first slice as "listen and persist, but do not act yet."

Recommended sequence:

1. add engagement event models
2. add account-scoped event storage plus dedupe state
3. add outbound message reference indexing on successful sends
4. add a thin Telethon listener worker that records inbound DM and group-reply candidates
5. add tests for normalization, dedupe, and restart safety

This slice should stop before external conversation state, reply generation, action queues, or policy-driven execution.

## Deliverables

- a dedicated MTProto listener service for managed accounts
- normalized inbound event models distinct from operator Bot API updates
- durable event deduplication and restart-safe resume behavior
- routing hooks for group replies, inbound DMs, and moderation outcomes

## Core Design Notes

- Do not overload `TelegramUpdate`; that model is currently operator-bot specific.
- Keep the listener thin. It should ingest and normalize events, not decide campaign strategy.
- Preserve raw event evidence for debugging and audit, but keep downstream runtime context compact.
- Prefer deterministic dedupe keys plus compact file-backed listener state over a heavier distributed event system for the first MVP cut.
- Keep unresolved events durable instead of forcing premature campaign attachment.

## Acceptance Criteria

- a managed account can receive a group reply event and the runtime records it once
- a managed account can receive an inbound DM and the runtime records it once
- listener restarts do not replay already-processed events indefinitely
- unsupported event types are skipped safely without crashing the listener
- the first slice can persist accepted inbound events without invoking reply generation or live execution

## Dependencies

- Telethon client wrapper lifecycle management
- campaign-linked conversation state
- execution and observation routing
- outbound message reference indexing for reliable reply classification
