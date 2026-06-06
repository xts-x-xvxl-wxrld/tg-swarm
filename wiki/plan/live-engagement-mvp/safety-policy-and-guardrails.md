# Safety Policy And Guardrails

## Goal

Define the smallest policy layer that keeps live engagement safe enough for an MVP while guiding agent behavior softly wherever possible and reserving hard stops for a narrow final-defense set.

## North-Star Link

This workstream primarily supports these operating principles from [Campaign North Star](campaign-north-star.md):

- **Public First, DM By Permission**
- **Account Health Is A Durable Asset**
- **Community Trust Matters**

## Why This Matters

Without this layer, the system may create activity while undermining the actual campaign outcome.

## Why This Exists

Current account safety is still coarse. A live engagement runtime needs explicit, machine-checkable rules around who can be messaged, how often, under which account, and when the system must stop.

There is already a small amount of live-execution safety behavior in code today, especially around:

- DM replies requiring proven inbound-first posture
- blocked, paused, or closed conversations refusing automatic dispatch
- capability outcome codes such as `policy_blocked` and rate-limit outcomes

This workstream should turn those isolated checks into one explicit MVP policy layer instead of letting safety stay scattered across prompts, queue workers, and capability adapters.

The preferred posture for this repo should be soft-first, not error-first. In practice that means the runtime should usually prevent bad actions by shaping plans, delaying dispatch, choosing safer alternatives, or escalating early, instead of letting agents repeatedly collide with `forbidden`-style execution failures.

## Scope

- inbound-first DM policy
- execution-time hard stops for malformed or disallowed actions
- campaign, account, and conversation pause enforcement
- account health stops and real account-scoped rate-limit cooldowns
- a small decision model that explains block vs wait clearly
- later campaign-level quiet hours as the next preferred pacing control

## Out Of Scope

- a general-purpose policy engine for the whole repo
- content moderation for every possible legal or compliance edge case
- behavioral scoring based on opaque model judgments alone
- high-volume anti-spam optimization systems
- a permanent operator review UI beyond the minimum Telegram-facing controls
- conversation-local backoff ladders or multi-step autonomous follow-up pacing
- community-level moderation auto-pause
- sensitive-content review taxonomy unless a later workstream uses it directly

## MVP Safety Posture

The intended MVP posture should stay simple and opinionated.

- No cold outbound DMs.
- DM replies remain allowed only after the external user messaged first.
- Group engagement stays campaign-linked, bounded, and easy to pause.
- Hard blocks should exist only for a narrow last-defense set.
- Account health should outrank short-term engagement opportunities.
- The first MVP should stay lean enough that operators can understand every stop condition quickly.

## Soft-First Enforcement Model

The live-engagement MVP should prefer the following order of operations:

1. shape the agent's behavior in prompts and action-planning contracts
2. preflight proposed actions and steer them toward safer alternatives
3. convert account-level rate limits into durable wait states
4. use hard execution-time refusal only when the action would clearly violate a core boundary

This means the system should usually say, in effect:

- "wait until this account cooldown clears"
- "reply in-group instead of moving to DM"
- "use a different account later"

rather than:

- "action failed"
- "forbidden"
- "policy blocked"

unless the runtime is at a core safety boundary.

## Narrow Hard-Stop Set

For MVP, the hard-stop set should stay intentionally small.

Recommended hard stops:

- no cold outbound DMs
- no DM reply without proven inbound-first posture
- no automatic sends from paused, blocked, escalated, or closed conversations
- no automatic sends from banned or explicitly paused accounts
- no execution after an explicit operator stop

Everything else should prefer softer handling first:

- reroute through safer action selection
- pause the thread or account without treating it like a fatal error when an operator explicitly chooses that

## MVP Policy Defaults

- No cold outbound DMs.
- DM replies are allowed only after inbound contact from the external user.
- First group engagement in a new community should remain bounded and campaign-linked.
- Flagged, banned, or actively rate-limited accounts should not continue autonomous engagement.

Recommended additional defaults for the first cut:

- operator-paused campaigns, accounts, or conversations should block automatic execution immediately
- policy should prefer exact platform cooldown handling over speculative thread-level pacing rules
- quiet hours should be added before any richer autonomous follow-up timing

## Recommended Control Layers

Keep this workstream layered so prompts help, but code remains the final gate for consequential behavior.

### 1. Prompt Layer

Prompts should shape tone, escalation instincts, and business-grounded behavior.

Prompts should not be the only protection for:

- DM consent posture
- pacing and cooldown enforcement
- blocked-account handling
- operator pause state

### 2. Pre-Enqueue Policy Checks

When later reasoning paths propose live actions, the runtime should be able to reject or defer obviously invalid actions before they ever reach the queue.

Examples:

- trying to enqueue a DM reply for a conversation with no inbound-first proof
- trying to enqueue a new action on a paused conversation
- trying to enqueue a first-contact behavior that the campaign policy forbids

Where possible, these checks should return a safer next step, not just a refusal.

Examples:

- convert "send now" into "wait until the account flood-wait expires"
- convert "start DM" into "stay in public thread" when the policy requires that posture

### 3. Execution-Time Hard Checks

The live execution worker should remain the last safety gate before visible Telegram writes.

This is where the runtime must enforce:

- conversation posture checks
- account and conversation status checks
- account-scoped cooldown windows that come from real platform rate limits
- account-health stop conditions

This layer should stay intentionally narrow. If a rule can be handled earlier as planning guidance, queue deferral, or cooldown, it usually should be.

### 4. Capability Feedback

Capability outcome codes should flow back into policy state rather than being treated as one-off failures.

Examples:

- `rate_limited` should open cooldown windows
- `account_flagged` should pause or block the account automatically

## Recommended Implementation Shape

For MVP, keep this logic close to live execution rather than introducing a repo-wide policy engine too early.

Recommended first implementation seam:

- `telegram_app/live_execution/policy.py` for policy evaluation helpers
- optional `telegram_app/live_execution/policy_models.py` if the decision objects grow beyond a small dataclass

That layer should be called by:

- queue-time action creation paths when available
- `LiveExecutionService` immediately before dispatch
- later operator-review or observation code when it needs human-readable policy reasons

Do not spread new guardrail rules across:

- prompts only
- ad hoc checks inside multiple capability adapters
- operator-surface formatting code

## Policy Decision Model

The runtime needs a normalized decision shape so later workstreams do not invent incompatible safety semantics.

Recommended decision states:

- `allowed`
- `suggested_adjustment`
- `cooldown`
- `blocked`

Recommended decision payload:

- `decision`
- `reason_codes`
- `summary`
- `risk_level`
- `cooldown_until` when applicable
- optional `recommended_action` or `recommended_adjustment`
- compact `evidence` fields such as conversation status or recent rate-limit signal

The key point is that policy should answer more than yes or no. It should explain what safer behavior should happen next, and only use `blocked` when the runtime is protecting a core boundary.

## Deliverables

- machine-readable policy checks for live engagement actions
- normalized block reasons for policy refusals
- operator-visible policy notes in execution results
- durable account cooldown state for real rate-limit windows

Recommended additional deliverables:

- persistent stop-condition state that survives restarts
- policy outputs that can steer agents toward safer alternatives before queueing
- focused tests that prove the worker cannot bypass the policy seam accidentally

## Policy Areas

- account safety
- inbound-first consent posture
- duplicate-contact prevention
- operator-controlled stop states

## Policy Families

Translate the broad policy areas above into small, checkable rule families.

### Consent And Contact Rules

These rules decide whether the runtime is allowed to contact this person or thread at all.

Recommended MVP rules:

- DM replies require durable inbound-first proof
- conversation consent posture must explicitly allow the action type
- blocked, closed, paused, or escalated conversations cannot auto-dispatch
- group-reply actions require valid reply-thread lineage

### Pacing And Cooldown Rules

These rules decide whether the action is allowed now, even if it is allowed in principle.

Recommended MVP checks:

- active flood-wait or rate-limit windows for the same account
- exact wait durations returned by Telegram or the capability layer

The first cut does not need conversation-local timers, unanswered-follow-up counters, or retry ladders.

These rules should usually produce defer or wait behavior, not hard refusals.

### Account Health Rules

These rules decide whether the account itself is in a safe enough state to keep acting.

Recommended MVP stop conditions:

- account marked banned
- account marked flagged
- active flood-wait or recent severe rate limit
- operator pause on the account

### Deferred Pacing Work

The following ideas are useful, but they should stay out of the first MVP policy implementation until the observation and timing workstreams are ready:

- conversation-level cooldown timestamps
- unanswered-follow-up backoff ladders
- community-level moderation auto-pause
- approval and escalation taxonomies for sensitive content
- autonomous multi-step follow-up timing

The preferred next pacing addition after the lean safety core is campaign-configurable quiet hours, followed later by the randomized read/reply timing note in [humanized-engagement-timing.md](humanized-engagement-timing.md).

## Policy State And Inputs

The evaluator should not depend only on the immediate action payload. It should read compact durable state.

Recommended minimum inputs:

- `action_type`
- `campaign_id`
- `account_id`
- optional `conversation_id`
- optional `community_id` or `chat_id`
- conversation status and consent posture
- account health snapshot
- recent rate-limit outcomes by account
- pause state at campaign, account, and conversation levels

Recommended minimum persistent policy state:

- account-scoped active cooldown windows from real rate limits
- recent rate-limit outcomes by account when needed for diagnostics
- operator pause markers for accounts

Prefer compact structured fields over freeform notes whenever the runtime needs to make a decision automatically.

## Locked Storage Direction

Before coding, lock the health and pause storage split so we do not create avoidable churn across the conversation and execution seams.

### Account-Level Health And Rate-Limit Posture Lives Outside Conversation Records

Account-scoped safety posture should live in account-scoped or execution-adjacent policy state, not on every conversation record.

This includes fields such as:

- active rate-limit or flood-wait windows
- flagged or degraded account posture
- account-wide pause state

Recommended implementation direction:

- keep this state either under managed-account storage or in a small execution-adjacent policy state file
- do not duplicate the same account-health posture onto each conversation record

Why this belongs outside conversation records:

- it applies across multiple threads
- it should gate account behavior consistently in one place
- duplicating it onto conversation records would create stale or conflicting state

### Practical Rule Of Thumb

When a rule answers "is this account in a safe enough posture to act anywhere right now?", store it in account-scoped or execution-adjacent policy state.

When a rule is only a future pacing preference for one conversation, defer it until the observation and timing workstreams need it.

## Recommended Build Order

Build this workstream in three slices.

### Slice 1: Normalize Existing Hard Checks

- extract current conversation-posture and status checks from `LiveExecutionService` into one policy helper
- normalize policy decision codes and summaries
- identify which current checks should remain hard stops and which should become minimal account cooldown outputs
- keep the worker as the only path that can turn a queued write into a visible Telegram action
- add tests proving current DM and paused-thread protections still hold after refactoring

### Slice 2: Add Minimal Account Cooldown And Pause State

- persist minimal rate-limit and pause state at account scope
- keep conversation records limited to posture and durable thread identity, not timing ladders
- add policy checks for recent rate-limit and operator pause state
- make policy return `cooldown` distinctly from terminal `blocked`
- prefer queue deferral over repeated execution-time throttling failures
- ensure cooldown survives restarts

### Slice 3: Add Quiet Hours Before Richer Timing

- add campaign-configurable quiet hours as the first real pacing control beyond platform flood-waits
- keep quiet hours deterministic, inspectable, and easy to override per campaign
- defer randomized read/reply timing and autonomous follow-up scheduling to later timing work

## Design Notes

- Keep deterministic policy rules ahead of model judgment where possible.
- Keep "blocked" separate from "wait" so operators can tell the difference between a hard stop and a cooldown.
- Keep soft guidance separate from hard refusal so the agent can adapt before it collides with execution-time errors.
- Keep policy reason codes stable because operator UX, tests, and observation summaries will depend on them.
- Keep the live execution worker as the non-bypassable write gate even if earlier layers also validate.
- Treat throttling as a scheduling and pacing concern first, not only as an execution failure mode.
- Prefer deleting speculative policy state over preserving complexity for future autonomous behavior.

## Suggested Reason Codes

The exact names can change, but the runtime should converge on a small stable vocabulary.

- `dm_inbound_required`
- `conversation_paused`
- `conversation_blocked`
- `conversation_closed`
- `conversation_escalated`
- `account_rate_limited`
- `account_flagged`
- `account_banned`
- `duplicate_contact`
- `cooldown_active`
- `suggested_wait`
- `suggested_reroute`

Stable reason codes matter because they become:

- execution summaries
- operator review cues
- observation inputs
- test assertions

## Interaction With Other Workstreams

This workstream is the safety spine for several neighboring plans.

- `external-conversation-state.md` provides the posture and status fields policy reads.
- `live-execution-runtime.md` remains the final enforcement path for visible Telegram writes.
- `managed-account-capability-expansion.md` should emit outcome codes rich enough for policy reactions.
- `engagement-brain-and-reply-policy.md` should respect these safety decisions rather than re-deciding them in prompts.
- `operator-review-and-ops-surface.md` should expose policy blocks, cooldowns, and pause state clearly.
- `observation-and-adaptation.md` should treat policy outcomes as campaign-learning signals, not only errors.

## Acceptance Criteria

- the runtime refuses a DM reply when the external user did not initiate contact
- the runtime refuses actions for blocked or rate-limited accounts
- real account flood-wait windows defer later actions cleanly instead of producing noisy repeated execution failures
- policy refusals are stored clearly enough for operator review

Recommended additional acceptance checks:

- campaign, account, and conversation pause states each stop automatic execution independently
- policy decision summaries are stable enough to appear in operator-facing status views and tests
- the live execution worker cannot bypass policy by calling capabilities directly without an evaluated decision
- quiet hours can be added later without reworking the policy seam or duplicating account health state

## Dependencies

- external conversation state
- execution runtime
- account capability surface
- operator controls

## Dependency Note

This workstream should land after the execution and conversation seams are real enough to supply durable posture and outcome data, but before live engagement becomes more autonomous.

That means the policy layer should be introduced while the live execution seam is still narrow, not after many action paths already exist.
