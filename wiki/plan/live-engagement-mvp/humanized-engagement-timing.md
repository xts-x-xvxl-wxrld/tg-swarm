# Humanized Engagement Timing

## Goal

Define a later hardening pass for managed-account pacing so live engagement looks less mechanical and avoids deterministic timing patterns.

This note is intentionally downstream of the current MVP plumbing. It should shape how the runtime behaves once the core engagement loop, observation flow, and operator controls are already in place.

## Why This Exists

The current live-engagement safety layer uses deterministic cooldown timing.

That is acceptable as an early safety guardrail, but it is not a good long-term pacing model for human-like operation because:

- exact repeated timing patterns are suspicious to external users
- exact repeated timing patterns may increase Telegram trust and anti-abuse risk
- "wait exactly N minutes" is a safety simplification, not a realistic conversational rhythm

The runtime should eventually move from:

- fixed cooldown durations

to:

- bounded timing windows
- one-time randomized due timestamps
- different pacing behavior for reads, replies, and follow-ups
- quiet-hours-aware scheduling

## Relationship To Current Implementation

Today the runtime already has:

- conversation-local cooldown state on external conversation records
- account-level cooldown state after rate limits
- execution-time deferral when a cooldown is active
- persisted conversation-level follow-up windows with chosen due timestamps
- CET quiet-hours-aware follow-up scheduling for group and DM silence windows

Today the runtime does **not** yet have:

- randomized read timing
- randomized reply timing
- an observation-adjacent pending-window store that lives outside conversation records
- automated due-window review workers that convert follow-up windows into later reasoning passes
- distinct timing policies per action family beyond the new follow-up slice

This note defines that later direction.

## Current Implementation Note

The first implementation slice has now landed narrowly.

What exists now:

- one persisted `follow_up_due_at` per conversation
- conversation-local `follow_up_window_type`
- conversation-local `follow_up_attempt_count`
- CET quiet-hours shaping before the chosen due timestamp is persisted
- successful outbound conversation sends automatically open or roll forward follow-up windows
- inbound-event projection clears pending follow-up windows and resets the silence cycle

What remains intentionally deferred:

- read timing windows
- reply-after-read timing windows
- a dedicated observation-owned pending-window seam separate from conversation records
- automated recurring review workers for due windows

That means the current runtime now has the first durable follow-up-window primitive, but not yet the full humanized-timing stack described in the rest of this note.

## Design Principles

- Safety and anti-spam posture still outrank realism.
- Randomness should be bounded, deterministic after assignment, and persisted.
- Read timing, reply timing, and follow-up timing should be treated as different concepts.
- Quiet hours should constrain autonomous activity even when a sampled window would otherwise allow earlier action.
- Platform-enforced wait times such as Telegram flood waits should stay exact and should not be randomized away.
- A randomized schedule should be chosen once per event or action and then persisted; it should not be rerolled on every worker tick.

## Three Timing Families

### 1. Read Timing

Read timing answers:

- when should this managed account mark a message as read
- when should the runtime treat the message as "seen" for later reply timing

Recommended target range:

- 30 seconds to 10 minutes after inbound arrival

Recommended direction:

- shorter reads for high-priority or already-active threads
- wider reads for lower-priority or colder contexts
- no exact repeated minute boundaries

Important note:

- "read" should become its own scheduled timing event, not an automatic immediate side effect

### 2. Reply Timing

Reply timing answers:

- once a message is considered read, when should the outbound reply actually be sent

Recommended target range:

- 1 to 2 minutes after read time

Why this is separate from read timing:

- people often do not reply the instant a message arrives
- but once they have opened and read the message, the remaining typing delay is usually much shorter

Recommended model:

1. choose and persist `read_due_at`
2. once the runtime reaches that moment or acknowledges the read event, choose and persist `reply_due_at`
3. send only when `reply_due_at` arrives and policy still allows it

This separation should produce more natural behavior than a single combined "reply in X minutes" rule.

### 3. Follow-Up Timing

Follow-up timing answers:

- when should the runtime send another proactive message if the other side never replied

Follow-up timing should now be split by context because group threads and DMs have different tolerance.

#### Group Follow-Up Windows

Group follow-up timing answers:

- when should the runtime re-enter an active public thread if the thread stayed relevant but no one replied

Recommended target range:

- randomized between 24 and 48 hours after silence begins

Recommended direction:

- allow recurring group follow-up windows while the thread remains active and policy still allows participation
- treat each follow-up as a new bounded scheduling decision rather than queueing many future sends at once
- expect each follow-up to be materially different in wording or angle rather than a repeated nudge

Important limit:

- this should still remain one window at a time
- the next group follow-up window should open only after the previous follow-up was sent and no blocking signal arrived

Why:

- public threads can support longer-running re-entry better than DMs
- one-at-a-time windows keep recurring group engagement bounded and observable

#### DM Follow-Up Windows

DM follow-up timing answers:

- when should the runtime send one more proactive DM if the other side went silent after an active conversation

Recommended target range:

- one autonomous follow-up window
- randomized between 24 and 48 hours after silence begins

Recommended MVP-hardening rule:

- keep DM follow-up more conservative than group follow-up
- after the one scheduled DM follow-up, require either inbound activity or a later policy/operator change before another autonomous DM is allowed

Why:

- this preserves the inbound-first DM posture more safely
- this reduces obvious repetitive nudging in the highest-risk channel

## Suggested Timing Model

The runtime should eventually persist timing decisions like:

- `read_due_at`
- `reply_due_at`
- `follow_up_due_at`

Potential additional fields:

- `timing_profile`
- `timing_reason`
- `follow_up_attempt_count`
- `quiet_hours_profile`

The critical point is that the runtime should store **chosen timestamps**, not only duration ranges.

Bad pattern:

- every worker tick rolls a new random number

Good pattern:

- one event arrives
- the runtime samples one allowed time inside the configured range
- the runtime shifts that chosen time forward if it lands inside quiet hours
- that chosen timestamp is persisted
- all later processing uses the same stored timestamp

## Quiet Hours

Quiet hours should act as a cross-cutting scheduling constraint for humanized engagement.

Initial rule for this plan:

- quiet hours run from 00:00 to 08:00 Central European Time
- for now, treat this as a fixed CET policy for managed-account pacing

Recommended behavior:

- autonomous reads should not be marked during quiet hours
- autonomous replies should not be sent during quiet hours
- autonomous follow-ups should not be sent during quiet hours
- if a sampled due time lands inside quiet hours, move it to the next allowed morning window rather than sending immediately at the boundary

Recommended implementation direction:

- evaluate windows in CET wall-clock terms
- persist the chosen `due_at` in UTC after the CET-based quiet-hours adjustment
- add a small wake-up offset after 08:00 so many actions do not cluster exactly at the quiet-hours boundary

Example:

- a DM follow-up window samples to 2026-05-23 02:40 CET
- because that falls inside quiet hours, the runtime shifts it to a later allowed morning time such as 2026-05-23 08:23 CET
- the persisted stored value should still be the final UTC timestamp, not the original blocked sample

## Randomness Rules

Randomness should be constrained and explainable.

Recommended rules:

- choose from bounded ranges only
- avoid exact quarter-hour or hour-aligned repetition where possible
- keep the sampling simple enough to test
- apply quiet-hours adjustment before persisting the final chosen timestamp
- preserve deterministic replay in tests by allowing a seeded or injectable sampler

Recommended implementation direction:

- one small timing policy helper or sampler module
- one persisted schedule record per timing event
- one quiet-hours adjustment helper that runs before persistence
- explicit test seams for "sampled window" and "chosen due time"

## Interaction With Existing Workstreams

This note depends heavily on neighboring live-engagement seams.

### Live Execution Runtime

The execution worker should remain the only path that turns a due reply into a visible Telegram write.

### Safety Policy And Guardrails

Policy still decides whether sending is allowed at the due moment.

Timing humanization should not override:

- campaign pause
- account pause
- account rate-limit windows
- conversation pause or escalation
- approval-required decisions

### Observation And Adaptation

Observation is the most natural home for silence tracking and one-time follow-up scheduling.

This is especially true for:

- opening a delayed follow-up window
- cancelling it when a reply arrives
- ensuring group follow-up windows reopen only one at a time
- ensuring a DM silent thread gets at most one autonomous follow-up
- applying quiet-hours-aware rescheduling without polluting execution policy

### Engagement Brain And Reply Policy

Reply drafting and timing choice should remain separate decisions:

- the engagement brain can decide whether a reply or follow-up is worth doing
- the timing layer decides when it should appear

## Proposed Storage Direction

Do not overload the current deterministic cooldown fields with every future timing concept.

Recommended later direction:

- keep hard policy cooldowns such as rate limits in policy state
- keep conversation-local posture on conversation records
- store humanized read/reply/follow-up due times in observation-adjacent scheduling state
- store recurring follow-up windows as explicit pending records rather than ad hoc conversation flags

The current first slice stores follow-up windows directly on conversation records.

The intended later migration is still:

- move pending timing windows into observation-adjacent scheduling state once that seam exists
- leave conversation records owning posture and compact summary, not the long-term timing queue

Recommended pending-window fields:

- `window_id`
- `conversation_id`
- `window_type` such as `read`, `reply`, `group_follow_up`, or `dm_follow_up`
- `source_event_id`
- `due_at`
- `consumed_at`
- `cancelled_at`
- `timing_profile`
- `follow_up_attempt_count`

## Non-Goals

- imitating human behavior with complex probabilistic personas
- generating arbitrary delays with no business or safety reasoning
- bypassing Telegram-imposed wait times
- replacing approval, pause, or escalation rules with random timing

## Suggested Build Timing

This note should be treated as a **post-MVP hardening pass** or at least a late-phase enhancement after:

1. observation windows exist
2. reply policy exists
3. operator pause and review controls exist

Recommended landing order:

1. finish the core live-engagement MVP
2. add CET quiet-hours shaping to any new humanized timing path
3. replace deterministic conversation follow-up timing with bounded persisted timing windows
4. split read timing from reply timing
5. introduce recurring one-at-a-time group follow-up windows
6. introduce one-DM-follow-up silence timing
7. validate that policy and operator controls still override all chosen timestamps cleanly

## Acceptance Criteria

- read timing is no longer immediate or fully deterministic for live-engagement flows that opt into this model
- reply timing is scheduled separately from read timing
- group follow-up windows can recur at 24-to-48-hour intervals without prequeueing unlimited future sends
- DM silent threads remain more conservative and do not receive unlimited autonomous follow-ups
- quiet hours from 00:00 to 08:00 CET block autonomous reads, replies, and follow-ups from landing overnight
- chosen due times survive restarts without being rerolled
- Telegram-imposed rate-limit windows still remain exact and authoritative
- timing behavior is testable with deterministic sampling in unit tests
