# Autonomous Send Approval Alignment

## Goal

Lock the first implementation-ready contract for bounded autonomous sending so the runtime can decide whether to send and what to send for live engagement without drifting outside approved campaign context, bounded conversation context, and the current safe send posture.

This is the point where engagement-brain proposals stop being "safe in theory" and start becoming explicit approved send context for real MTProto writes.

## Cutover Update (2026-05-27)

Supported reply-path sends have now moved past the transitional operator-review design.

The active direction is:

- `send_group_reply` and `send_dm_reply` no longer wait on per-message operator review
- grounded supported replies should receive structured autonomous approved-send context by default
- `manual_only`, `review_required`, and `pending_autonomous_review_id` are no longer part of the normal reply-path send flow
- any stale review-needed records from the old path should be retired rather than reintroduced into queue admission
- MTProto still requires explicit structured approval context, but that context may now come from the autonomous reply-path authorization seam

## Current Baseline

Already present in code:

- `telegram_app/engagement_brain/coordinator.py` already builds bounded conversation context, runs the engagement brain, evaluates queue-time live-execution policy, and enqueues allowed send proposals.
- `telegram_app/live_execution/policy.py` already enforces deterministic execution-time safety rules such as paused campaigns, paused or blocked conversations, DM inbound-first posture, rate-limit cooldowns, and community risk pauses.
- `telegram_app/live_execution/service.py` already carries `approval_context` through queued message actions into the MTProto messaging capability.
- `telegram_app/capabilities/mtproto/impl_messaging.py` already rejects visible sends that do not carry explicit approved context.
- `telegram_app/external_conversations/` already owns durable conversation status, consent posture, review triggers, and next-action summaries.

Missing today:

- one explicit runtime decision between "proposal looks good" and "this proposal is allowed to count as an approved send"
- one explicit authorization model for bounded autonomous sends at campaign scope
- one durable review-needed record for grounded proposals that are not yet allowed to auto-send
- one structured approved-send context for autonomous sends instead of the current loose `approved=True` convention
- one clear distinction between execution-time policy refusal and review-needed-by-posture outcomes

Important current limitations:

- the current engagement-brain action map only materializes `send_group_reply` and `send_dm_reply`; autonomous first-contact group posts are not yet emitted by the brain seam
- the current MTProto approval check is intentionally coarse and only proves that some caller marked the send as approved
- blocked autonomous proposals currently collapse into conversation `next_action_type` updates such as `policy_hold`, which is not a durable operator review surface

Relevant code touchpoints today:

- `telegram_app/engagement_brain/models.py`
- `telegram_app/engagement_brain/coordinator.py`
- `telegram_app/live_execution/models.py`
- `telegram_app/live_execution/policy.py`
- `telegram_app/live_execution/service.py`
- `telegram_app/external_conversations/models.py`
- `telegram_app/external_conversations/manager.py`
- `telegram_app/capabilities/mtproto/impl_messaging.py`
- `telegram_app/models/approval.py`

## Core Questions To Lock

This step should answer:

1. which live message actions may be autonomously authorized in the first safe cut
2. where autonomous send posture lives and at what scope it is explicit first
3. what proof is required for a proposal to count as campaign-bounded and conversation-bounded
4. how an allowed autonomous proposal turns into explicit approved send context for MTProto writes
5. where grounded-but-not-yet-authorized proposals are stored for later operator review
6. how later operator approval or posture change can re-materialize a blocked proposal without silently sending stale text
7. how this authorization layer stays separate from execution-time safety policy

## Recommended Direction

Use one explicit autonomous-send authorization seam between engagement-brain proposals and the live-execution queue.

Recommended first-cut direction:

- keep execution-time policy in `telegram_app/live_execution/policy.py`
- keep the MTProto capability as the final visible-write gate
- insert one new queue-time authorization decision before enqueueing any autonomous visible send
- make campaign-level autonomous-send posture explicit first, instead of introducing a broad global approval engine
- persist review-needed autonomous proposals as campaign-owned live state, not as session-scoped `ApprovalRecord`s
- land reply-path authorization first, then extend the same contract to autonomous first-contact group posts once their public-thread context carrier is explicit

Why this direction:

- the current policy seam already answers "is this action safe to execute right now?"
- this plan needs to answer a different question: "is this proposal allowed to count as an approved send at all?"
- keeping those concerns separate avoids turning live-execution policy into a mixed posture plus approval plus review queue
- avoiding `ApprovalRecord` reuse prevents background live-review state from becoming coupled to operator session chat state

## Locked Runtime Behavior

### Action Family Scope

The autonomous-send contract should target message writes only.

Recommended first-cut action families:

- `send_group_reply`
- `send_dm_reply`

Reserved next action family after the reply path is stable:

- `send_group_message`

Out of scope for this slice:

- `join_community`
- `mark_read`
- any non-message MTProto write

### Grounding Rule

Every autonomous visible write must be grounded in both campaign context and bounded local message context.

Recommended first-cut rule:

- a reply proposal must carry `campaign_id`
- a reply proposal must carry `conversation_id`
- a reply proposal must be tied to one specific review moment via `trigger_key` or the latest durable `last_event_id`
- a reply proposal must be generated from bounded recent message context rather than free-floating copy

Recommended group-outreach extension rule:

- an autonomous first-contact group message must carry `campaign_id`
- it must carry a resolved target `chat_id` or `community_id`
- it must carry a bounded public-thread or community-window context snapshot, not only a campaign-level message idea
- if that bounded public context object does not exist yet, the proposal cannot count as autonomous-send eligible

If a proposal lacks the required grounding proof, the runtime should not enqueue it as a sendable live action.

### Posture Model

Keep the first explicit posture model narrow and campaign-owned.

Recommended first-cut posture scope:

- campaign-level autonomous-send posture is explicit
- conversation and account state still constrain sends through existing policy and conversation records
- no separate account-level autonomous-send permission matrix is required yet

Recommended posture fields:

- `campaign_id`
- `group_outreach_mode`
- `group_reply_mode`
- `dm_reply_mode`
- `updated_at`
- `updated_by`
- `notes`

Recommended mode values:

- `manual_only`
- `autonomous_allowed`

This means:

- campaign posture decides whether a grounded proposal may auto-send in principle
- conversation and account state still decide whether it may execute safely right now

### Authorization Decision Model

Add one normalized decision shape for autonomous send authorization.

Recommended decision states:

- `allowed`
- `review_required`
- `blocked`

Meaning:

- `allowed`
  The proposal is grounded, fits the current autonomous posture, and may be stamped as approved send context before entering normal execution policy.
- `review_required`
  The proposal is grounded and meaningful, but the current posture says it should not auto-send yet.
- `blocked`
  The proposal is malformed, unsupported, or ungrounded enough that it should not be treated as reviewable executable intent.

Recommended decision payload:

- `decision`
- `reason_codes`
- `summary`
- `action_type`
- `campaign_id`
- `conversation_id`
- `trigger_key`
- `context_fingerprint`
- `review_record_id` when one is created
- `recommended_operator_action`

Important separation:

- authorization should not emit `cooldown`
- timing and cooldown remain execution-policy outcomes, not send-approval outcomes

### Approved Send Context

Allowed autonomous sends must become explicit approved send context before they hit MTProto.

Recommended first-cut autonomous `approval_context` shape:

- `approved: true`
- `approval_mode: "autonomous"`
- `approval_source: "engagement_brain_authorizer"`
- `authorization_decision: "allowed"`
- `authorized_action_type`
- `campaign_id`
- `conversation_id` when available
- `trigger_key` when available
- `context_fingerprint`
- `brain_decision`
- `goal`
- `authorized_at`

Recommended operator-approved send shape should remain compatible but distinct:

- `approved: true`
- `approval_mode: "operator"`
- `approval_id`
- `campaign_id`
- optional `conversation_id`

The important rule is that MTProto should not have to infer whether a send was approved conversationally, manually, or autonomously. The approval context should say so directly.

### Review-Needed Record Model

Grounded proposals that are not allowed to auto-send should become durable review-needed records.

Do not reuse `ApprovalRecord` for this path.

Why not:

- `ApprovalRecord` is session-scoped
- autonomous send review is campaign and conversation scoped
- background review moments may occur with no active operator session
- blocked autonomous proposals need message-level evidence, not only a prompt string

Recommended review record fields:

- `review_id`
- `campaign_id`
- `conversation_id`
- `account_id`
- `action_type`
- `status`
- `draft_text`
- `goal`
- `qualification_state`
- `presentation_hints`
- `trigger_key`
- `trigger_source`
- `context_fingerprint`
- `reason_codes`
- `summary`
- `created_at`
- `resolved_at`
- `resolved_by`
- `resolution_note`
- `materialized_action_id`

Recommended review record statuses:

- `pending`
- `materialized`
- `dismissed`
- `superseded`

Recommended first-cut conversation linkage:

- store `pending_autonomous_review_id` on the conversation record for easy operator lookup
- keep the richer proposal evidence in the dedicated review record, not inline on the conversation itself

### Re-Materialization Rules

Blocked autonomous proposals may later become runnable, but only through one explicit re-check path.

Recommended first-cut re-materialization rules:

1. the review record must still be `pending`
2. the current conversation must still exist and still match the original `conversation_id`
3. the current review trigger or latest conversation state must still match the saved `context_fingerprint`
4. the campaign posture or explicit operator action must now allow the action family
5. the normal live-execution policy check must still pass before enqueue
6. successful materialization marks the review record `materialized` and stores the resulting `action_id`
7. if the context fingerprint no longer matches, mark the review record `superseded` rather than sending stale text

This keeps later operator approval or posture changes safe and deterministic.

### Execution Boundary

Lock the three-layer decision order:

1. engagement brain proposes a next move
2. autonomous-send authorization decides whether that proposal may count as an approved send
3. live-execution policy decides whether the approved send may execute now
4. MTProto capability remains the final visible-write gate

This is the important difference between:

- proposing an action
- authorizing an action
- dispatching an action

## Concrete Runtime Shape

Use one dedicated seam rather than widening the coordinator or the approval manager ad hoc.

Recommended package:

- `telegram_app/autonomous_send/`

Recommended first files:

- `models.py`
  Own posture records, authorization decisions, and review-needed records.
- `manager.py`
  Own campaign-backed JSON persistence for posture plus review-needed records.
- `service.py`
  Own grounding checks, posture evaluation, review-record creation, approved-context stamping, and safe re-materialization.

Recommended storage direction:

- posture file per campaign, for example `autonomous_send/posture.json`
- review-needed record file per campaign, for example `autonomous_send/reviews.json`

Why this seam:

- `engagement_brain/` should keep owning proposal generation and bounded review orchestration
- `live_execution/` should keep owning execution policy, queueing, dispatch, and retries
- `approvals/` should keep owning session-shaped pending approvals rather than background live-review intent
- autonomous send authorization is its own control-plane translation step and deserves one narrow home

## Implementation Track

### Posture Contract

Add the smallest explicit autonomous-send posture object first.

Recommended first-cut behavior:

1. if no posture exists for a campaign yet, default all action families to `manual_only`
2. posture changes are explicit runtime state, not inferred from prompts
3. the first operator surface may remain minimal; this slice only needs the stored contract
4. do not widen `CampaignRecord` immediately if a dedicated campaign-owned posture file is enough

This keeps the first slice local and reversible.

### Authorization Service Contract

The authorization service should answer one question:

"May this specific grounded proposal count as approved send context right now?"

Recommended first input shape:

- `campaign_id`
- `conversation_id`
- `action_type`
- `proposal`
- `trigger`
- `context_fingerprint`

Recommended first output shape:

- `decision`
- `reason_codes`
- `summary`
- `approval_context` when `allowed`
- `review_record` when `review_required`

Recommended first reasons:

- `campaign_manual_only`
- `unsupported_action_family`
- `missing_campaign_context`
- `missing_conversation_context`
- `stale_review_trigger`
- `group_outreach_context_unavailable`

### Context Fingerprint Contract

Lock one deterministic fingerprint so the runtime can tell whether a later operator approval still matches the original proposal context.

Recommended first-cut reply fingerprint material:

- `campaign_id`
- `conversation_id`
- `action_type`
- `trigger_key` when available
- `last_event_id`
- `last_inbound_message_id`
- `reply_target_message_id`
- normalized `draft_text`

Recommended group-outreach extension fingerprint material:

- `campaign_id`
- `chat_id` or `community_id`
- action type
- community-window message refs or thread anchor id
- normalized `draft_text`

The exact hash function can follow the existing `sha256` pattern already used for idempotency.

### Coordinator Contract Update

Update `EngagementBrainCoordinator` so it routes send proposals through authorization before queueing.

Recommended first flow:

1. build bounded context
2. run the brain
3. return `NO_ACTION` immediately for wait, ignore, or escalate
4. build a grounding fingerprint for send proposals
5. call the autonomous-send authorization service
6. if `allowed`, build the live action with explicit autonomous `approval_context`
7. if `review_required`, persist the review record, update conversation next-action state, and return a distinct run disposition
8. if `blocked`, update conversation state with a clear non-runnable summary and stop before enqueue
9. only after `allowed` should the candidate action flow through `LiveExecutionService.evaluate_policy()`

Recommended run-disposition addition:

- add `REVIEW_REQUIRED` to `EngagementBrainRunDisposition`

That keeps "not allowed to auto-send yet" distinct from "execution policy blocked this action."

### MTProto Approval Tightening

Use this slice to converge from a loose approval boolean toward a structured approved-send contract.

Recommended direction:

1. update autonomous callers to emit structured `approval_context`
2. update operator-approved paths to emit `approval_mode="operator"` when possible
3. then tighten `impl_messaging._is_send_approved()` so bare `approved=True` is no longer treated as sufficient forever

Recommended structured allow rule for the capability layer:

- operator-approved context is valid when `approved` is true and `approval_mode=="operator"`
- autonomous-approved context is valid when `approved` is true and `approval_mode=="autonomous"`
- temporary migration compatibility may remain during the first code slice, but the long-term contract should stop trusting untyped `approved=True`

### Review Surface Contract

Keep the first review surface simple and compatible with the later Telegram live ops slice.

Recommended first-cut runtime behavior:

- when a review record is created, set conversation `next_action_type` to a review-needed value such as `review_autonomous_send`
- persist `pending_autonomous_review_id` on the conversation record
- keep `next_action_reason` concise and operator-facing
- let the later live-ops surface read the richer review record for inspection and explicit approval or dismissal

This means the runtime gains a durable operator-readable state now without needing to build the full Telegram control flow in the same slice.

### Delivery Slices

Build this workstream in three small slices.

#### Slice 1: Reply Authorization Core

- add the new autonomous-send seam
- add campaign-level posture defaults
- route `send_group_reply` and `send_dm_reply` proposals through authorization before queueing
- add `REVIEW_REQUIRED` results and durable review records

#### Slice 2: Structured Approval Context Tightening

- convert autonomous and operator send callers to typed `approval_context`
- tighten MTProto approval checks toward the structured contract
- prove that approved autonomous sends still dispatch while loose untyped approval is phased out

#### Slice 3: Group Outreach Extension

- widen the brain contract to support `send_group_message`
- introduce a bounded public-thread or community-window context carrier
- route grounded first-contact group proposals through the same authorization seam

## File-Level First Cut

The smallest practical coding slice should touch:

- `telegram_app/engagement_brain/models.py`
  Add `REVIEW_REQUIRED` and, when the outreach slice lands, widen supported brain action types.
- `telegram_app/engagement_brain/coordinator.py`
  Route send proposals through the authorization service before queue-time policy checks.
- `telegram_app/external_conversations/models.py`
  Add `pending_autonomous_review_id` plus any minimal operator-surface linkage fields.
- `telegram_app/external_conversations/manager.py`
  Persist the conversation linkage updates for pending autonomous review.
- `telegram_app/autonomous_send/models.py`
  Add posture, decision, and review-record models.
- `telegram_app/autonomous_send/manager.py`
  Add campaign-backed persistence for posture and review-needed records.
- `telegram_app/autonomous_send/service.py`
  Add authorization, review-record creation, approval-context stamping, and re-materialization helpers.
- `telegram_app/live_execution/service.py`
  Preserve and pass through the richer approved-send context unchanged.
- `telegram_app/capabilities/mtproto/impl_messaging.py`
  Tighten approved-send validation around a structured context.
- `server.py`
  Compose the new autonomous-send service into the runtime bundle.

## Validation Plan

Add focused coverage before broader Telegram smoke testing.

Recommended test additions:

- `tests/test_autonomous_send.py`
  Posture evaluation, grounding checks, review-record creation, and re-materialization rules.
- `tests/test_engagement_brain.py`
  `REVIEW_REQUIRED` disposition and coordinator behavior around allowed vs review-needed proposals.
- `tests/test_live_execution.py`
  Allowed autonomous approval context survives queue and dispatch without changing existing policy behavior.
- `tests/test_mtproto_capabilities.py`
  Structured autonomous and operator approval contexts pass; malformed or untyped approval contexts fail once the migration step lands.
- `tests/test_external_conversations.py`
  Pending autonomous review linkage persists correctly on conversation records.

Minimum acceptance proof for this slice:

- a grounded reply proposal can become an explicitly authorized autonomous send without manual per-message operator instruction
- a grounded reply proposal in `manual_only` posture becomes a durable review-needed record instead of a runnable live action
- a malformed or ungrounded proposal does not enter the live execution path
- later posture change or operator approval can re-materialize a still-current pending review record safely
- the runtime distinguishes `review_required` from execution-policy `blocked`
- MTProto visible sends remain impossible without explicit approved-send context

## Non-Goals

- opening cold outbound DMs
- building a repo-wide generic policy engine
- replacing the existing live-execution policy seam
- building the full Telegram operator approval UX in this slice
- solving all future autonomous follow-up pacing behavior
- widening autonomous permissioning to every MTProto write family

## Acceptance Criteria

- autonomous proposals and actual send authorization are separated cleanly in runtime state
- campaign-level autonomous-send posture is explicit and defaults conservative
- reply-path autonomous sends can be allowed without manual per-message approval when they are campaign-bounded, conversation-bounded, and posture-allowed
- grounded but not posture-allowed proposals become durable review-needed records instead of runnable queued writes
- malformed or ungrounded proposals are blocked before queue admission
- execution-time safety policy remains a separate later gate after autonomous authorization
- MTProto writes receive structured approved-send context instead of relying forever on a loose boolean
- focused coverage proves allowed, review-needed, blocked, and later-materialized paths behave deterministically
