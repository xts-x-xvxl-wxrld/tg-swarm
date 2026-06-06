# Telegram Live Ops Surface

## Goal

Expose the live engagement machine's key control and inspection surfaces through the normal Telegram operator experience.

This is the step where the already-landed execution, conversation, and autonomous-send seams stop being "workspace-visible only" and become something an operator can steer safely from chat.

## Cutover Update (2026-05-27)

Supported reply-path sends no longer use per-message operator approval as part of the target runtime.

That means this live-ops surface should now emphasize:

- campaign, account, and conversation pause or resume
- live status, queue inspection, and blocked-send inspection
- campaign-level posture and runtime health only when they still affect a supported execution path

It should not assume that normal grounded DM or group replies need an operator to approve individual message drafts before send.

## Implementation Update (2026-05-27)

The first operator-chat cut is now implemented:

- `telegram_app/live_ops/` exists as the dedicated composition seam for live status, attention summaries, pause/resume routing, autonomous review resolution, posture changes, and control-completeness reporting
- `telegram_app/orchestrator/orchestrator.py` now checks for explicit live-ops chat intent before normal specialist routing and asks a short clarification when a tone/safeguard request could also be review-time planning feedback
- `telegram_app/autonomous_send/service.py` now supports explicit operator materialize and dismiss flows for pending review records
- `telegram_app/engagement_brain/context_builder.py` now overlays durable live-ops control overrides so campaign voice and safeguard changes actually affect bounded live reply drafting
- focused tests now cover natural-language control turns, ambiguous review clarification, control-gap reporting, and live reply context override propagation

## Current Baseline

Already present in code:

- `telegram_app/live_execution/service.py` already exposes campaign, account, and conversation pause/resume helpers.
- `telegram_app/live_execution/manager.py` already exposes queue inspection helpers such as `list_for_campaign()`, `list_queued_for_campaign()`, `list_queued_for_account()`, and `list_active_for_conversation()`.
- `telegram_app/external_conversations/manager.py` already exposes campaign conversation listing plus durable next-action, review, and pending-autonomous-review linkage state.
- `telegram_app/autonomous_send/manager.py` already persists campaign autonomous-send posture and review-needed records.
- `telegram_app/campaigns/manager.py` already persists campaign lifecycle state.
- `telegram_app/app_service.py` and `telegram_app/orchestrator/orchestrator.py` already provide the normal Telegram operator turn path where this surface should live.

Missing today:

- no operator-visible live status summary for the current campaign
- no Telegram-native route for campaign, account, or conversation pause and resume
- no operator-facing inspection surface for blocked live actions, paused conversations, or pending autonomous-send reviews
- no operator-facing flow for resolving one pending autonomous review from Telegram
- no operator-facing flow for changing campaign autonomous-send posture from Telegram
- no focused tests proving live-ops turns do not regress existing planning behavior

Important current limitations:

- the runtime currently has a read-only `/accounts` inventory, but that is not a live-ops surface
- the current runtime has no dedicated global campaign browser, so the first cut should center on the session-attached campaign plus explicitly referenced account or conversation ids
- `telegram_app/autonomous_send/service.py` can authorize proposals and persist review-needed records, but it does not yet expose explicit operator resolution helpers such as approve, materialize, or dismiss

Relevant code touchpoints today:

- `server.py`
- `telegram_app/app_service.py`
- `telegram_app/orchestrator/orchestrator.py`
- `telegram_app/campaigns/manager.py`
- `telegram_app/prepared_execution/`
- `telegram_app/live_execution/manager.py`
- `telegram_app/live_execution/service.py`
- `telegram_app/live_execution/policy_state.py`
- `telegram_app/external_conversations/models.py`
- `telegram_app/external_conversations/manager.py`
- `telegram_app/autonomous_send/manager.py`
- `telegram_app/autonomous_send/service.py`
- `prompts/orchestrator.md`

## Core Questions To Lock

This step should answer:

1. how an operator asks for live status, pause, resume, or review actions through ordinary Telegram turns
2. what campaign-level live summary is shown first and what evidence is intentionally hidden
3. how the runtime resolves scope for campaign, account, conversation, and review-record actions
4. how pending autonomous-send reviews are inspected and explicitly resolved from Telegram
5. how campaign autonomous-send posture is surfaced and changed without blurring into per-message approval
6. how live-ops intent stays separate from normal planning turns so discovery, strategy, and account-planning routing do not regress

## Recommended Direction

Use the orchestrator as the natural-language intent interpreter, but add one dedicated runtime seam for live-ops inspection and control.

Recommended first-cut direction:

- keep live reasoning in `telegram_app/engagement_brain/`
- keep queueing and execution policy in `telegram_app/live_execution/`
- keep autonomous-send authorization and review persistence in `telegram_app/autonomous_send/`
- add one narrow `telegram_app/live_ops/` seam that assembles status summaries, applies explicit operator control actions, and formats compact Telegram-facing results
- keep the first cut centered on the current session campaign rather than adding a broad multi-campaign command surface
- prefer freeform operator intent such as "show live status", "pause this campaign", or "show pending autonomous reviews" rather than adding a large slash-command control plane

Why this direction:

- the operator already works through normal orchestrator turns
- the underlying control hooks already exist, so the main missing layer is composition plus operator UX
- keeping inspection and control in a dedicated seam prevents `live_execution/` from becoming a formatting and orchestration layer
- keeping the first cut session-scoped avoids solving a global operator dashboard before the live loop is fully proven

## Locked Operator Behavior

### Entry Surface

The first cut should stay inside normal operator chat turns.

Recommended first-turn examples:

- "show live status"
- "show queued live actions"
- "show conversations that need me"
- "pause this campaign"
- "resume account acc_123"
- "pause conversation conv_456"
- "show pending autonomous reviews"
- "approve autonomous review abc123"
- "dismiss autonomous review abc123"
- "enable autonomous dm replies for this campaign"

Do not require a new dashboard.

Do not require operators to open workspace files or know raw JSON paths.

Optional slash commands may be added later only if repeated use proves the freeform surface too ambiguous.

### Scope Resolution Rules

Keep scope resolution explicit and conservative.

Recommended first-cut rules:

1. campaign-scoped live ops default to the session-attached `campaign_id`
2. account-scoped actions require an explicit `account_id`
3. conversation-scoped actions require an explicit `conversation_id`
4. autonomous review actions require an explicit `review_id`
5. if the scope is ambiguous, the orchestrator should ask one short clarifying question instead of guessing

This prevents a live pause or review action from landing on the wrong entity.

### Campaign Overview Contract

`show live status` should return one compact campaign summary rather than raw queue dumps.

Recommended first summary sections:

- campaign state
  `campaign_id`, campaign lifecycle status, and primary goal when present
- activation state
  latest prepared-execution batch state or a clear "not activated yet" message
- live queue state
  counts for `queued`, `retry_wait`, `claimed/running`, `blocked`, and recently `succeeded`
- conversation pressure
  counts for `review_inbound`, `review_autonomous_send`, `paused`, `escalated`, and follow-up-due conversations
- autonomous-send posture
  current `group_reply_mode` and `dm_reply_mode`
- next operator action
  one concise recommendation such as review pending autonomous sends, resume a paused conversation, or activate the latest approved plan

Recommended Telegram output shape:

- one short headline
- one compact count summary
- up to five highest-signal items needing attention
- one explicit next-step hint

Do not dump every live action, every conversation, or whole review records in the overview response.

### Attention Queue Contract

Operators also need one explicit "what needs me now" surface.

Recommended first attention categories:

- pending autonomous-send reviews
- escalated conversations
- manually paused conversations with new recent inbound pressure
- blocked live actions whose outcome suggests workflow or policy intervention
- paused campaigns or accounts that are preventing current work

Recommended attention ordering:

1. pending autonomous-send review
2. escalated conversation
3. blocked live action
4. paused conversation with new inbound
5. paused account or campaign

Each returned item should include:

- stable id such as `review_id` or `conversation_id`
- compact reason
- the one suggested operator verb to continue

### Control Actions

Pause and resume should be explicit state changes with clear confirmation copy.

Recommended first-cut writable actions:

- pause campaign
- resume campaign
- pause account
- resume account
- pause conversation
- resume conversation
- enable autonomous group replies for the campaign
- disable autonomous group replies for the campaign
- enable autonomous DM replies for the campaign
- disable autonomous DM replies for the campaign
- approve one pending autonomous review
- dismiss one pending autonomous review

Recommended confirmation behavior:

- apply the state change once
- return the new effective state in operator-facing language
- include any immediate consequence such as "future autonomous replies remain manual-only" or "this conversation will return to bounded review on the next inbound moment"

### Pending Autonomous Review Resolution

Step 4 should not stop at inspection. It should expose explicit resolution flows.

Recommended first-cut operator actions:

- inspect one pending review record
- approve one review record as a one-off operator-approved send
- dismiss one review record with a short note
- change campaign posture separately when the operator wants the whole action family to stop requiring manual review

Important rule:

- approving one review record should not silently widen campaign autonomous posture

Recommended approval flow:

1. load the pending review record
2. verify the conversation still exists
3. verify the saved `context_fingerprint` still matches current conversation context
4. if stale, mark the review `superseded` and explain that the draft was not sent
5. if current, materialize one live action with explicit operator approval context
6. run the normal queue-admission and execution-policy checks
7. if queue admission succeeds, mark the review `materialized`
8. if current policy blocks or cools down the action, keep the review pending and return the blocking reason clearly

Recommended dismissal flow:

1. load the pending review record
2. mark it `dismissed`
3. clear `pending_autonomous_review_id` from the conversation when it still points at that review
4. return concise confirmation

This keeps per-message operator decisions separate from campaign-level autonomous posture.

## Concrete Runtime Shape

Use one dedicated live-ops seam instead of widening the orchestrator or live-execution service ad hoc.

Recommended package:

- `telegram_app/live_ops/`

Recommended first files:

- `models.py`
  Own operator-intent, scope, snapshot, and action-result contracts.
- `service.py`
  Own campaign summary assembly, attention-queue lookup, pause/resume application, posture changes, and autonomous-review resolution.
- `formatter.py`
  Own compact Telegram-facing text formatting so status assembly stays separate from presentation.

Recommended support additions:

- add explicit autonomous-review resolution helpers in `telegram_app/autonomous_send/service.py`
- add small prepared-execution lookup helpers if the current activation seam does not yet expose "latest batch" inspection cleanly

Why this seam:

- `orchestrator.py` should keep interpreting operator intent and choosing the route
- `live_execution/service.py` should keep owning execution control, not operator response formatting
- `autonomous_send/service.py` should keep owning per-review materialization and dismissal semantics
- the live-ops seam is the composition layer that translates operator intent into compact safe runtime actions

## Implementation Track

### Intent Contract

Add one small normalized live-ops intent model instead of scattering string checks through the orchestrator.

Recommended first intent kinds:

- `show_campaign_status`
- `show_attention_queue`
- `show_account_status`
- `show_conversation_status`
- `pause_scope`
- `resume_scope`
- `set_autonomous_posture`
- `show_autonomous_reviews`
- `show_autonomous_review`
- `approve_autonomous_review`
- `dismiss_autonomous_review`

Recommended scope fields:

- `campaign_id`
- `account_id`
- `conversation_id`
- `review_id`
- `posture_field`
- `requested_mode`

The orchestrator should resolve this intent and then hand execution to the live-ops service.

### Campaign Snapshot Contract

Lock one compact campaign snapshot object for the first Telegram surface.

Recommended snapshot fields:

- `campaign_id`
- `campaign_status`
- `primary_goal`
- `activation_status`
- `latest_prepared_batch_id`
- `queued_count`
- `retry_wait_count`
- `active_execution_count`
- `blocked_count`
- `recent_success_count`
- `review_inbound_count`
- `pending_autonomous_review_count`
- `paused_conversation_count`
- `escalated_conversation_count`
- `group_reply_mode`
- `dm_reply_mode`
- `attention_items`
- `recommended_next_action`

Recommended first data sources:

- `CampaignManager`
- `PreparedExecutionManager` or service lookup helper
- `LiveExecutionManager`
- `ExternalConversationManager`
- `AutonomousSendManager`

This gives the operator enough signal without exposing raw internal record payloads.

### Attention Queue Assembly

Build one deterministic attention queue instead of many small ad hoc status views.

Recommended first assembly rules:

1. start from current campaign conversations and pending autonomous reviews
2. enrich with blocked queued actions and campaign/account pause state
3. map each candidate into a compact attention item with one reason and one recommended verb
4. sort by severity and freshness
5. cap the first Telegram response to a small number of items, with a hint to ask for more detail if needed

Recommended first attention item fields:

- `item_type`
- `item_id`
- `campaign_id`
- `account_id`
- `conversation_id`
- `summary`
- `reason_code`
- `recommended_action`

### Control Routing

The live-ops service should route writes to the narrowest existing owner.

Recommended routing:

- campaign pause and resume -> `LiveExecutionService.pause_campaign()` / `resume_campaign()`
- account pause and resume -> `LiveExecutionService.pause_account()` / `resume_account()`
- conversation pause and resume -> `LiveExecutionService.pause_conversation()` / `resume_conversation()`
- campaign autonomous posture changes -> `AutonomousSendManager.update_posture()` or one small wrapper in `AutonomousSendService`
- one-off autonomous review approval or dismissal -> new explicit helpers in `AutonomousSendService`

Do not bypass these owners by mutating JSON files directly from the orchestrator or formatter.

### Autonomous Review Resolution Helpers

Extend `telegram_app/autonomous_send/service.py` beyond authorization-only behavior.

Recommended first helpers:

- `materialize_review(campaign_id, review_id, *, operator_id)`
- `dismiss_review(campaign_id, review_id, *, operator_id, note="")`
- `get_review_summary(campaign_id, review_id)`

Recommended operator-approved live action context when materializing:

- `approved: true`
- `approval_mode: "operator"`
- `approval_source: "telegram_live_ops"`
- `approval_reason: "autonomous_review_approved"`
- `review_id`
- `campaign_id`
- `conversation_id`
- `context_fingerprint`
- `approved_at`
- `approved_by`

This keeps explicit Telegram operator review separate from campaign autonomous mode changes.

### Orchestrator Contract Update

Update the orchestrator so explicit live-ops intent can preempt normal planning routing without hijacking ordinary turns.

Recommended first behavior:

1. detect explicit live-ops intent before ordinary specialist routing
2. if the turn is a live-ops request, call the live-ops service directly
3. if the turn is ordinary planning, keep the current discovery, strategy, account-planning, and observation precedence unchanged
4. if the operator asks for status while no live campaign state exists yet, answer plainly instead of forcing specialist work

This keeps live control additive rather than disruptive.

### Delivery Slices

Build this workstream in four small slices.

#### Slice 1: Campaign Status And Campaign Pause

- add the live-ops seam
- expose campaign summary for the current session campaign
- expose campaign pause and resume
- add orchestrator intent handling for those basic turns

#### Slice 2: Account And Conversation Attention

- expose account- and conversation-scoped inspection
- expose pause and resume for accounts and conversations
- add the first deterministic attention queue

#### Slice 3: Autonomous Review Inspection And Resolution

- expose pending autonomous review listing and detail
- add approve and dismiss review flows
- clear or supersede conversation linkage safely when reviews resolve

#### Slice 4: Posture Controls And Prompt Hardening

- expose campaign autonomous reply posture toggles
- tighten orchestrator prompt instructions around live-ops wording and ambiguity handling
- add Telegram-shaped smoke validation across planning plus live-ops turns

## File-Level First Cut

The smallest practical coding slice should touch:

- `telegram_app/live_ops/models.py`
  Add normalized live-ops intent, snapshot, and action-result models.
- `telegram_app/live_ops/service.py`
  Add status assembly, control routing, and attention-queue logic.
- `telegram_app/live_ops/formatter.py`
  Add compact Telegram-facing status and confirmation formatting.
- `telegram_app/orchestrator/orchestrator.py`
  Detect explicit live-ops intent and route to the live-ops seam.
- `prompts/orchestrator.md`
  Teach the orchestrator when to interpret a turn as live ops rather than planning.
- `server.py`
  Compose the live-ops service into runtime startup.
- `telegram_app/autonomous_send/service.py`
  Add explicit review inspection, materialization, and dismissal helpers.
- `telegram_app/autonomous_send/manager.py`
  Add any small pending-review lookup helpers needed by the live-ops service.
- `telegram_app/prepared_execution/manager.py` or `telegram_app/prepared_execution/service.py`
  Add latest-batch inspection helpers if activation state cannot yet be summarized cleanly.

## Validation Plan

Add focused coverage before broader Telegram smoke testing.

Recommended test additions:

- `tests/test_live_ops.py`
  Campaign summary assembly, attention ordering, pause/resume flows, posture changes, and review resolution.
- `tests/test_autonomous_send.py`
  Operator approval, stale fingerprint supersession, dismissal, and pending-review cleanup behavior.
- `tests/test_telegram_runtime_state.py`
  Explicit live-ops turns route correctly and do not regress current planning flows.
- `tests/test_live_execution.py`
  Operator-materialized review actions preserve explicit approval context and still respect existing execution policy.

Minimum acceptance proof for this slice:

- an operator can inspect current campaign live state from Telegram without reading workspace files
- an operator can pause and resume campaign, account, and conversation scope through normal Telegram turns
- pending autonomous-send reviews are visible and can be resolved from Telegram
- campaign autonomous reply posture is visible and explicitly changeable from Telegram
- explicit live-ops turns do not break ordinary planning-stage routing

## Non-Goals

- building a broad multi-campaign analytics dashboard
- exposing every raw queue or conversation record directly in chat
- replacing the orchestrator with a command-only admin console
- building operator takeover ownership semantics in this slice
- redesigning live-execution policy or engagement-brain reasoning

## Acceptance Criteria

- operators can inspect current campaign readiness and live runtime state through Telegram
- operators can pause and resume campaign, account, and conversation scope through normal runtime turns
- blocked or review-needed live items surface as compact actionable operator-visible queues
- pending autonomous-send reviews can be inspected and explicitly resolved through Telegram
- campaign autonomous reply posture is visible and adjustable through Telegram
- focused validation proves the live-ops surface does not regress the existing planning flow
