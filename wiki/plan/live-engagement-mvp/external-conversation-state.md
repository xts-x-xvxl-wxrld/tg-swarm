# External Conversation State

## Goal

Persist campaign-linked state for conversations between managed Telegram accounts and external Telegram users or chats.

## North-Star Link

This workstream primarily supports:

- **Interest Capture**
- **Qualification**
- **Conversion Progression**

from [Campaign North Star](campaign-north-star.md).

## Why This Exists

The current session model is designed for the human operator. A live engagement runtime also needs durable state for:

- public group threads
- inbound-first DMs
- follow-up decisions
- opt-out, pause, or escalation status

Without this layer, the system has no memory of who it talked to, under which account, in which community, and what should happen next.

## Scope

- define campaign-linked conversation records for external chats and users
- preserve account ownership, target identifiers, source community, and last activity
- preserve engagement status, consent posture, and escalation state
- persist compact summaries and recent context for reply generation

## Recommended MVP Shape

This workstream should become the bridge between:

- account-scoped inbound evidence under `telegram_app/engagement/`
- campaign-scoped operational memory under `telegram_app/campaigns/` and `telegram_app/campaign_memory/`
- later live action dispatch under the execution runtime

The first implementation cut should introduce a dedicated runtime seam such as `telegram_app/external_conversations/`.

That seam should remain separate from:

- operator `SessionRecord` state
- raw inbound event storage in `telegram_app/engagement/`
- execution queue or retry logic
- campaign Markdown memory files used for human-readable planning context

The responsibility of this seam is not "store every message forever." Its job is to hold the compact durable state that lets the runtime answer:

1. which external thread this event belongs to
2. what the current conversation posture is
3. whether replying is allowed, blocked, paused, or awaiting review
4. what action should happen next

## Relationship To Inbound Event Ingestion

Inbound account event ingestion should stay account-scoped and append-only.

External conversation state should sit one level higher:

1. read normalized inbound events that were safely persisted already
2. resolve or create the correct campaign-linked conversation thread
3. update durable thread state from those events
4. expose compact thread summaries to downstream policy and execution paths

This separation matters because the listener currently creates a provisional `conversation_id` from account and peer identifiers. That identifier is useful for ingestion, but it should not become the only durable conversation model for the campaign runtime.

## Record Model Direction

The durable conversation record should be thread-shaped, not message-shaped.

Recommended minimum record shape:

- stable `conversation_id`
- `campaign_id`
- `account_id`
- `peer_id`
- `chat_id`
- `community_id` when the thread originated in a group or channel context
- `thread_origin` such as `group_reply`, `group_follow_up_dm`, or `direct_inbound_dm`
- `external_user_id` when one user is the primary peer
- `status` such as `active`, `cooling_down`, `paused`, `blocked`, `escalated`, or `closed`
- `consent_posture` such as `inbound_only`, `group_context_only`, `do_not_contact`, or `operator_override`
- `last_inbound_at`
- `last_outbound_at`
- `last_inbound_message_id`
- `last_outbound_message_id`
- `last_event_id`
- `next_action_type` and compact `next_action_reason`
- `operator_hold_reason` or escalation reason when relevant
- `summary`
- `recent_message_refs` or similarly compact references rather than full raw transcripts
- `created_at` and `updated_at`

Recommended companion indexes:

- account-plus-peer to active conversation
- account-plus-chat to active conversation
- inbound event id to conversation id
- outbound message id to conversation id

## Conversation Boundary Rules

The MVP should prefer simple deterministic thread boundaries over clever heuristics.

Recommended rules:

1. A direct inbound DM creates or refreshes one DM conversation for `account_id + external_user_id`.
2. A group reply to a managed-account message creates or refreshes one group-thread conversation for `account_id + chat_id + reply target lineage`.
3. A later DM from the same external user may link back to the earlier group-origin thread only when the runtime has explicit evidence that the same user is continuing the same engagement path.
4. If campaign resolution is ambiguous, keep the event durable but leave the conversation unresolved rather than forcing attachment.

The first slice should avoid cross-group thread merging, speculative identity linking, or fuzzy contact unification.

## Storage Strategy

This state should follow the repo's existing campaign-centered file-backed style.

Recommended campaign-scoped storage shape:

- `data/campaigns/<campaign_id>/external-conversations/conversations.json`
- `data/campaigns/<campaign_id>/external-conversations/indexes.json`
- `data/campaigns/<campaign_id>/external-conversations/events-to-conversations.json`

Optional account-side lookup helpers may remain under `data/managed_accounts/<account_id>/` when they exist only to help the listener or outbound reply matching.

Use JSON for the current active conversation graph because:

- the records are mutable state, not append-only evidence
- the runtime needs fast point lookups by peer, chat, and status
- the file-backed style is already established in campaigns, schedules, and work items

Raw transcripts, audit logs, and full event evidence should stay outside this seam.

## Summary And Context Strategy

Conversation state should store compact operational memory, not a full prompt transcript dump.

Recommended MVP context split:

- conversation record stores the latest message refs, status, and a concise rolling summary
- raw inbound and outbound evidence stays in engagement logs and execution records
- prompt builders assemble a bounded recent-thread view only when a live reasoning path needs it

The summary should answer:

- who this thread is with
- how the thread started
- what the external party appears to want
- what we last said or did
- whether the runtime should wait, reply, escalate, or stop

## State Lifecycle

The first version should support a narrow explicit lifecycle.

Recommended statuses:

- `active`: conversation can be considered for bounded follow-up
- `cooling_down`: recent activity exists, but pacing rules say to wait
- `paused`: operator or policy paused the thread
- `blocked`: policy or platform state says no further contact
- `escalated`: requires operator review or another workstream decision
- `closed`: no further action is expected

Recommended lifecycle triggers:

- inbound DM moves a thread toward `active`
- successful outbound reply updates activity fields and may move the thread to `cooling_down`
- opt-out, moderation, or hard policy signals move the thread to `blocked`
- ambiguous routing or sensitive content moves the thread to `escalated`
- explicit operator action can move the thread to `paused` or `closed`

## Campaign Memory Interaction

External conversation state should not be copied wholesale into campaign Markdown memory.

Instead, campaign memory should only receive durable campaign-level learning such as:

- repeated objections worth updating strategy
- qualified interest worth changing next actions
- moderation friction that changes execution posture
- notable operator decisions about how this campaign should engage

This keeps conversation state operational, while campaign memory remains strategic and reusable.

## First Implementation Slice

Build the first slice as "resolve and persist conversation threads, but do not reason or send yet."

Recommended sequence:

1. add conversation runtime models and a small manager under a dedicated seam
2. add campaign-scoped persistence plus lookup indexes
3. add a projector or updater that consumes persisted inbound engagement events
4. create or refresh DM and group-reply conversation records with deterministic rules
5. expose compact lookup helpers for later execution and policy checks
6. add tests for thread creation, refresh, ambiguity handling, and restart-safe reload

This slice should stop before reply drafting, queue dispatch, policy evaluation, or operator UX beyond persistence and lookup.

## Deliverables

- runtime models for external conversation threads
- storage and retrieval helpers under the campaign runtime
- links between conversation records, campaigns, accounts, communities, and execution events
- compact summary fields for prompt-safe reuse

## Core Design Notes

- Keep this seam distinct from operator sessions. A conversation with an external Telegram user is not a `SessionRecord`.
- Keep raw evidence and durable thread state separate. Append-only engagement logs should not become the only conversation database.
- Prefer deterministic routing and identity rules over speculative thread merging in MVP.
- Treat "external user messaged first" as durable state, not something recomputed ad hoc from raw logs each time.
- Store compact summaries and references so prompt context stays bounded even when a thread becomes long.
- Let campaign state own the durable conversation view, while account-scoped engagement storage remains the source of raw inbound evidence.

## Acceptance Criteria

- the runtime can load the active thread for a managed account plus external peer pair
- group-origin and DM-origin conversations are distinguishable
- the runtime can resolve persisted inbound events into durable conversation records without creating duplicate active threads on restart
- the conversation record preserves whether the external side initiated DM contact first
- operator pause, escalation, and closure decisions persist across restarts
- prompt builders can access a compact recent-thread summary without scanning raw logs

## Dependencies

- inbound event ingestion
- live execution runtime
- operator controls
