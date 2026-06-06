# Observation And Adaptation

## Goal

Keep a small amount of durable state that protects future writes and keeps the live engagement loop coherent across restarts.

## North-Star Link

This workstream primarily supports these parts of [Campaign North Star](campaign-north-star.md):

- **Learning**
- **Conversion Progression**
- **Account Health Is A Durable Asset**

## Why This Exists

The live-engagement MVP does not need a large observation engine.

It does need a few durable facts that answer questions like:

- is this account currently safe to write from
- is this conversation still allowed to receive autonomous replies
- did recent moderation or policy friction change what we should do next
- what important incident should survive restart and remain visible to the runtime

Without that compact state, the runtime risks:

- repeating writes that should be delayed or stopped
- losing safety posture after restart
- forcing later reasoning paths to re-scan raw logs for simple operational checks

## Scope

- persist only the small live-engagement state that materially affects future writes
- record major execution and policy outcomes that change account, community, or conversation posture
- expose a compact runtime view that later reasoning paths can consult cheaply
- promote only important incidents or reusable learnings into campaign memory

## Out Of Scope

- a broad observation-event platform
- full transcript-derived analytics
- silence-window tracking machinery in this phase
- semantic qualification or lead scoring
- automatic strategy rewriting from message-level outcomes
- normal human-in-the-loop conversation handling

## Recommended MVP Shape

This workstream should stay lean and should not try to become a separate product inside the runtime.

The main responsibility here is:

1. persist the minimal durable state needed for safe autonomous continuation
2. update that state from inbound events, execution outcomes, and policy outcomes
3. expose only the important pieces to memory and operator-facing surfaces

This means the workstream should focus on durable runtime posture, not on building a large taxonomy of observations.

## Core Definition

The design target for this workstream is:

> a small amount of durable state that protects writes and keeps the autonomous loop coherent across restarts

That is the main filter for every design choice in this file.

If a field or record does not:

- change future write behavior
- preserve safety posture across restart
- make later runtime checks materially simpler

then it probably does not belong in the MVP implementation.

## What Should Be Durable

The MVP should persist only the facts that future writes need to consult directly.

Recommended durable state:

- account cooldown or flood-wait posture
- account flagged, banned, or degraded safety posture when known
- community-level moderation friction or temporary risk pause markers
- conversation status when it changes behavior materially:
  - `active`
  - `paused`
  - `blocked`
  - `closed`
- conversation `last_inbound_at`
- conversation `last_outbound_at`
- compact policy-block or moderation-block reasons when they affect later writes

Recommended optional durable state only if the brain needs it soon:

- one lightweight `recently_contacted` or `awaiting_reply` marker per conversation

That optional marker should exist only if it clearly simplifies follow-up decisions. It should not become a large silence-window subsystem in this phase.

## What Can Stay Derived

Many things do not need special tracking in MVP because they can already be derived from persisted inbound and outbound history.

Examples that can usually stay derived:

- whether a conversation has any inbound message history
- whether a recent inbound reply happened
- whether a send succeeded in the last attempt
- low-level per-message event history

The runtime should avoid creating dedicated durable flags for facts that are already cheap and reliable to derive from the existing conversation, engagement, or execution records.

## Reads And Writes

This workstream exists mainly to protect writes, not to interfere with reads.

Recommended rule:

- inbound reads and event ingestion continue normally
- durable observation state influences whether the runtime should send again, wait, or stop

That means:

- cooldowns primarily gate future writes
- moderation friction primarily gates future writes
- blocked or paused conversation state primarily gates future writes

The system should not stop listening just because a thread or account is currently cooled down.

## Minimal State Families

For MVP, keep the state model small.

### Account Posture

Use this for facts that affect all future writes from one managed account.

Recommended examples:

- active flood-wait or rate-limit cooldown
- flagged or degraded account-health posture
- explicit account pause

### Community Posture

Use this for facts that affect future writes into one group or community.

Recommended examples:

- recent moderation friction
- repeated write-forbidden outcomes
- temporary community risk pause

### Conversation Posture

Use this for thread-local facts that affect whether the runtime should continue autonomous engagement.

Recommended examples:

- `active`
- `paused`
- `blocked`
- `closed`
- `last_inbound_at`
- `last_outbound_at`
- compact stop or caution reason when it matters

## Storage Direction

This workstream should prefer updating the seams that already own the relevant state rather than introducing a large new storage surface.

Recommended direction:

- conversation-local posture continues to live with `telegram_app/external_conversations/`
- account-scoped cooldown and health posture should live in account-scoped or policy-adjacent runtime state
- community risk posture may live in execution-policy-adjacent state or another compact live-engagement store if no better owner exists

Do not add a broad append-only observation ledger in this phase unless implementation pressure later proves it is necessary.

## Major Outcomes Worth Persisting

The MVP should treat only a small set of outcomes as first-class durable incidents.

Recommended examples:

- `rate_limited`
- `account_flagged`
- `account_banned`
- `write_forbidden`
- `policy_blocked`
- `conversation_paused`
- `conversation_blocked`
- `conversation_closed`

These matter because they change what the runtime is allowed or expected to do next.

## Major Outcomes Worth Promoting

Promotion should be sparse and practical.

### Promote To `execution-log.md`

Only promote important operational incidents such as:

- account rate-limit or flood-wait events
- account flagged or banned posture changes
- community moderation friction or repeated write-forbidden outcomes
- conversation paused, blocked, or closed for a meaningful reason
- policy blocks that reflect a recurring campaign behavior issue

Do not promote every success or every normal inbound reply.

### Promote To `next-actions.md`

Only promote items that suggest a campaign-level or runtime-level change, such as:

- pause or avoid a specific community
- rest or replace an account
- adjust campaign guidance because the same policy or moderation issue keeps repeating
- review whether the current engagement style is creating unnecessary friction

### `experiments.md`

For MVP, do not auto-promote anything here by default.

If later work shows repeatable pattern learning is useful, this can be added as a narrow follow-on slice.

## Minimal Adaptation Rules

Adaptation should stay deterministic and boring in MVP.

Recommended rules:

- rate limit or flood wait opens or extends account cooldown
- flagged or banned outcome blocks future autonomous writes from that account
- repeated moderation or write-forbidden outcomes risk-pause the affected community path
- blocked, paused, or closed conversation state prevents future autonomous sends in that thread
- policy-blocked outcomes persist the reason that later write checks should consult
- inbound events update `last_inbound_at`
- successful outbound actions update `last_outbound_at`

That is enough for the first safe operational cut.

## What To Defer

The following ideas should stay out of this phase unless implementation proves they are urgently needed:

- silence-window tracking as a dedicated subsystem
- follow-up timers and automated re-engagement timing logic
- broad observation record vocabularies
- semantic business interpretation of replies
- rich reusable experiment summaries
- normal operator takeover or human manual reply paths

## Human Involvement

Human intervention should not be part of the normal live engagement loop for this MVP.

The preferred posture is:

- the live engagement brain decides whether to continue or stop
- deterministic runtime state protects writes
- human controls remain limited to coarse operational actions such as pause or emergency stop when needed

This workstream should not assume the operator will manually log into managed accounts and continue conversations by hand.

## Recommended Build Order

Build this workstream in three lean slices.

### Slice 1: Durable Write-Protecting State

- lock the minimum durable fields that future writes must consult
- ensure account, community, and conversation posture survive restart
- keep the storage shape close to the seams that already own that state

### Slice 2: Deterministic State Updates

- update the durable posture fields from execution outcomes, inbound events, and policy results
- keep the rules narrow and explicit
- avoid introducing a large observation-record abstraction unless a concrete need appears

### Slice 3: Sparse Memory Promotion

- promote only major incidents to `execution-log.md`
- promote only campaign-changing follow-ups to `next-actions.md`
- leave `experiments.md` manual or empty for now

## Design Notes

- keep the design centered on future write safety, not on tracking everything
- prefer deriving facts from existing records over storing new flags
- only persist what must survive restart and affect later behavior
- keep adaptation deterministic and easy to test
- keep human intervention out of the normal conversation loop

## Acceptance Criteria

- the runtime preserves enough state across restart to avoid unsafe repeated writes
- account cooldown and degraded-health posture can block or delay future autonomous sends
- conversation blocked, paused, or closed state survives restart and gates future writes
- significant moderation or policy friction can change later autonomous behavior without requiring raw-log rescans
- campaign memory receives only major incidents or actionable follow-up items, not routine message traffic

## Dependencies

- inbound account event ingestion
- external conversation state
- live execution runtime
- safety policy and guardrails
- campaign memory integration

## Dependency Note

This workstream should stay downstream of the safety-policy reason shapes where possible, but it does not need to wait for a large policy engine.

As soon as execution and policy outcomes produce stable enough cooldown, block, and friction signals, this workstream can persist the minimum state needed to keep future writes safe.
