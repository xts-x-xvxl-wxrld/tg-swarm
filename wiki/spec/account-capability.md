# Account Capability

## Purpose

Define the Telegram account capability surface that lets managed MTProto accounts behave more like real Telegram users while still remaining observable, approval-aware, and safe to evolve.

This document is a narrower companion to [Telegram Capability Layer](C:/Users/ravil/OneDrive/Desktop/tg-swarm/wiki/spec/telegram-capability-layer.md). The broader capability spec defines the overall abstraction boundary; this spec defines the account-focused execution surface that sits underneath account selection, account health, and user-like account actions.

For the operational process that should govern how these actions are prepared, executed, observed, and adapted, see [Managed Account Operations](C:/Users/ravil/OneDrive/Desktop/tg-swarm/wiki/spec/managed-account-operations.md).

## Design Goal

The account capability should let the runtime treat managed Telegram accounts as durable operational actors, not just static credentials.

It should support:

- account inventory and health inspection
- account-state and restriction inspection
- user-like presence and engagement signals
- identity and relationship management
- approval-aware write actions
- structured audit and pacing metadata

The goal is not to mimic a human deceptively. The goal is to expose the real MTProto actions a normal account can perform, then let prompts, approvals, and pacing rules decide when and whether they should be used.

## Why This Needs Its Own Spec

The broad Telegram capability layer groups account operations together with community, membership, messaging, and audit concerns.

That is useful at the architecture level, but it is too coarse for implementation planning now that the runtime needs to reason about questions like:

- which account actions are read-only versus externally visible
- which actions should count as lightweight presence signals versus consequential writes
- which actions require explicit operator approval
- which actions carry meaningful rate-limit, privacy, or account-health risk
- how account state should be exposed to operators and campaign work

## Capability Role

The account capability should act as the account-facing facade between:

- orchestrator and specialists that need account context or account actions
- the account registry, audit log, and approval state
- the MTProto backend that actually executes Telethon calls

Agents should ask for account-domain actions like "set typing", "send reaction", or "inspect account health", not raw Telethon or MTProto methods.

## Account Capability Families

The account-focused surface should map cleanly to the original managed-account capability grouping:

1. `presence`
2. `messaging`
3. `engagement`
4. `dialog`
5. `identity`
6. `social`

The sections below expand those buckets in repo-native terms.

### 1. Presence

This family covers durable metadata about each managed account.

It includes both operational readiness and lightweight visible activity, because both are needed to reason about whether an account can behave like a live user session.

Examples:

- list accounts
- get one account
- inspect health, tier, cooldown, and recent action outcomes
- expose last join/send/presence activity
- expose risk or pacing annotations
- set online or offline status when the backend permits it
- emit typing indicators
- emit upload-photo, upload-video, upload-file, record-voice, choose-sticker, and similar action states
- expose whether an account is currently in a temporary cooldown window for visible activity

The inventory and health parts of this bucket are mostly read-side. The visible activity parts are externally visible and should be auditable even when they are lighter than full message sends.

### 2. Messaging

This family covers the minimum conversation actions needed for a managed account to behave like a normal Telegram user in chats and DMs.

Examples:

- send a basic text message
- send a simple reply to a specific message
- continue an existing DM or group-thread conversation with plain text
- mark messages or dialogs as read
- mark reactions as read
- inspect read-state where Telegram exposes it
- clear unread state in a controlled way

Basic message send should be treated as a consequential write:

- it is externally visible
- it can affect moderation and reputation directly
- it should remain approval-aware by default in the current operating model

Message-state actions are also important because they can materially change conversation state and campaign memory without sending a new message.

This spec is intentionally talking about the smallest outbound messaging surface, not the whole richer messaging capability area like media composition, forwarding, edit flows, or thread-management depth.

### 3. Engagement

This family covers externally visible actions that are smaller than composing a new message.

Examples:

- react to a message
- remove or change a reaction
- react to a story
- view or acknowledge a story when the backend supports it

These are still writes and should not be treated as harmless no-ops.

### 4. Dialog

This family covers account-scoped chat and inbox state that shapes how a managed account behaves operationally across conversations.

Examples:

- archive or unarchive dialogs
- inspect or preserve drafts where relevant
- pin or unpin dialogs when the backend supports it
- leave chats or channels from the account side

These actions are not always as sensitive as outbound messaging, but they still change account state and should remain auditable.

### 5. Identity

This family covers changes to how a managed account appears in Telegram.

Examples:

- inspect profile details
- update display name
- update bio
- update username
- update profile photo

These are high-sensitivity actions because they affect long-lived account identity.

### 6. Social

This family covers account-scoped social and client-state actions.

Examples:

- block or unblock a user
- add or remove contacts
- inspect participants, permissions, or related social context tied to the account's reachable graph

Some of these are low-risk hygiene actions; others are consequential and should be reviewed carefully.

## Capability Principles

### Separate Read, Light Write, And Consequential Write

The account capability should not flatten all actions into one permission bucket.

At minimum it should distinguish:

- read actions: inventory, health, inspect profile, inspect state
- light writes: typing, online/offline, mark read, react
- consequential writes: send a message, change profile, block/unblock, or otherwise change public or relationship state materially

This distinction matters for approvals, pacing, audit shaping, and operator review UX.

### Prefer Stable Domain Actions Over Raw MTProto Method Names

The public capability interface should not expose transport-library jargon as its main abstraction.

For example, a capability operation should look like:

- `set_presence(account_id, chat_id, activity="typing")`
- `send_reaction(account_id, chat_id, message_id, reaction)`
- `mark_read(account_id, chat_id, max_message_id=...)`

The MTProto method mapping should remain an implementation detail beneath the capability layer.

### Preserve Structured Risk Metadata

Every write-like account action should be able to return structured metadata such as:

- action type
- target chat or peer
- account id
- visibility level
- approval requirement or approval id
- cooldown or wait seconds
- resulting health change
- backend source and raw outcome class

This keeps campaign memory, audits, and later policy enforcement consistent.

## Approval Expectations

The account capability should expose hooks for approval-aware routing.

Recommended default posture:

- read actions usually execute directly
- light writes may execute directly in lower-risk workflows, but should still be logged
- consequential writes should usually require explicit operator approval

Examples of actions that should default toward approval:

- basic outbound message sends
- profile or identity changes
- blocking or unblocking
- any future attempt to automate larger bursts of reactions or presence activity
- any action pattern that appears to simulate engagement at scale rather than support one concrete workflow step

## Pacing And Safety Expectations

Account actions should respect that Telegram account health is a durable asset.

The runtime should be able to layer pacing controls around:

- repeated joins
- repeated sends
- repeated reactions
- repeated presence signals in a short window
- identity churn such as frequent username or profile changes

This spec does not define exact rate limits, but it does require the account capability to expose enough metadata for pacing policy to exist.

## Suggested Interface Shape

The exact Python protocol can evolve, but the capability surface should likely grow toward operations like:

- `list_accounts()`
- `get_account(account_id)`
- `get_account_state(account_id)`
- `set_presence(account_id, peer_id, activity)`
- `mark_read(account_id, peer_id, max_message_id=None)`
- `send_message(account_id, peer_id, text, reply_to_message_id=None, approval_context=None)`
- `send_reaction(account_id, peer_id, message_id, reaction)`
- `clear_reaction(account_id, peer_id, message_id, reaction=None)`
- `archive_dialog(account_id, peer_id, archived=True)`
- `leave_dialog(account_id, peer_id)`
- `view_story(account_id, peer_id, story_id)`
- `send_story_reaction(account_id, peer_id, story_id, reaction)`
- `update_profile(account_id, ...)`
- `update_profile_photo(account_id, image_ref)`
- `block_user(account_id, peer_id)`
- `unblock_user(account_id, peer_id)`
- `add_contact(account_id, peer_id, ...)`
- `remove_contact(account_id, peer_id)`

Not every operation needs to land in the first implementation cut, but this is the target shape for a user-like account surface.

Where responsibility boundaries matter, the account capability should remain the place that expresses "this managed account can perform a basic outbound send", even if richer chat-content workflows continue to share code with a broader messaging capability implementation underneath.

## Rollout Recommendation

### Phase A: Extend Operational Visibility

First add read-heavy operational state so the runtime can reason about account readiness before it acts.

Examples:

- richer account health details
- last action summaries
- cooldown/rate-limit exposure
- lightweight action audit visibility

### Phase B: Add Low-Complexity User-Like Actions

Add the smallest account actions that materially improve user-like behavior without opening the full engagement surface.

Examples:

- typing and other presence actions
- mark-read actions
- message reactions

### Phase C: Add Higher-Sensitivity Identity And Relationship Actions

Only after the lower-risk path is proven live should the runtime add:

- profile edits
- profile photo changes
- block/unblock
- story engagement if it becomes operationally important

## Non-Goals

This spec does not:

- define deceptive-behavior policy
- guarantee that every Telegram UI behavior is safely automatable
- commit the runtime to high-volume automated engagement
- replace the separate messaging, membership, or community capability specs

It only defines the account-focused surface and the constraints that should shape it.

## Success Criteria

This spec is successful when:

1. The team can distinguish account-domain actions from generic messaging or membership work.
2. The runtime has a clear place to add user-like MTProto actions without leaking Telethon details upward.
3. Light account actions and consequential account actions are not treated as the same risk level.
4. Auditing, approvals, and pacing can evolve without redesigning the whole account surface.
5. Managed accounts can gradually become more operationally capable while remaining observable.

## Open Questions

- Which light-write account actions should ship before broader outbound engagement?
- Should typing and presence actions be orchestrator-owned directly, or mostly invoked by specialist workflows?
- Which account actions should always require explicit approval regardless of workflow?
- How much story-related support is actually useful for the campaign operating model versus nice to have?
