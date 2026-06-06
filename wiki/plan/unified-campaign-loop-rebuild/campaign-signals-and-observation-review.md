# Campaign Signals And Observation Review

## Goal

Replace ad hoc live note promotion with a compact signal-and-review loop: deterministic runtime code captures important campaign signals, then a bounded `observation` specialist reviews only the signals that matter for campaign steering.

## Why This Is Separate From Lean Observation State

The existing live-engagement observation plan focuses on durable write-protecting state. This slice adds the campaign-steering layer above that state:

- signal records worth reviewing
- a bounded observation review brief
- triggers for when campaign steering should re-run

It should build on lean durable state, not replace it.

## Current Runtime Alignment

This slice should extend the live seams that already exist rather than invent a second observation stack:

- `telegram_app/live_execution/service.py` already sees high-value outbound outcomes, policy blocks, retries, pauses, and major failure summaries
- `telegram_app/live_execution/policy_state.py` already persists compact account and community posture that signals can reference instead of duplicating
- `telegram_app/engagement/listener.py` and `telegram_app/engagement/storage.py` already persist normalized inbound managed-account events
- `telegram_app/external_conversations/projector.py` and `telegram_app/external_conversations/manager.py` already project those events into durable campaign-linked conversation state
- `telegram_app/campaign_memory/operational_notes.py` already provides sparse operator-facing note promotion for the biggest incidents
- `telegram_app/work_items/manager.py`, `telegram_app/scheduling/manager.py`, and `telegram_app/orchestrator/orchestrator.py` already provide the control-plane seams observation work should plug into

The implementation should keep those responsibilities recognizable:

- live seams detect and emit candidate campaign signals
- one campaign-scoped signal seam owns persistence, dedupe, and review eligibility
- work items and schedules own when bounded review runs
- the observation specialist owns steering advice only

## Scope

- define a compact `CampaignSignal` record
- add a reusable signal bridge from live seams into campaign signal storage
- define advisor-only `ObservationReviewAgent` behavior
- create or refresh `observation` work when high-value review is warranted
- keep the review path out of the live execution write path

## Design Principles

- deterministic first: runtime code decides capture, dedupe, severity, and review gating before any LLM review is considered
- signal-first, not transcript-first: review should reason from compact incident digests and refs, not raw chat history by default
- campaign-owned, not session-owned: signal history belongs under the campaign workspace and survives operator sessions and worker restarts
- bounded review: observation should review a small prioritized slice of unresolved pressure, not the full live history
- steering only: observation may advise planning refreshes, posture changes, or operator attention, but should not directly perform live actions or mutate campaign state
- sparse promotion: campaign memory notes remain compact summaries of important conclusions, not a duplicate signal ledger

## Non-Goals

- reviewing every inbound or outbound live event
- building a broad analytics warehouse or dashboard
- replaying full transcripts through the model on every review
- letting observation bypass deterministic live-execution or policy checks
- autonomous strategy rewrites on low-signal noise

## Recommended Runtime Shape

Add a narrow `telegram_app/campaign_signals/` seam instead of spreading signal logic across the live runtime.

Recommended responsibilities:

- `telegram_app/campaign_signals/models.py`
  Own `CampaignSignalRecord`, review cursor state, and small review-result shapes.
- `telegram_app/campaign_signals/manager.py`
  Own campaign-scoped storage, lookup, dedupe, unresolved selection, and state transitions such as `unresolved`, `reviewed`, `dismissed`, or `superseded`.
- `telegram_app/campaign_signals/bridge.py`
  Own a small reusable API that live seams call to emit meaningful signal candidates without owning storage logic themselves.
- `telegram_app/campaign_signals/review.py`
  Own deterministic review-pressure evaluation plus helper logic for creating or refreshing `observation` work items.
- `telegram_app/live_execution/service.py`
  Emit signal candidates for major write outcomes, rate-limit posture changes, account pauses, community pauses, blocked sends, and escalations.
- `telegram_app/engagement/listener.py` or `telegram_app/external_conversations/projector.py`
  Emit signal candidates for meaningful inbound moments such as high-stakes escalations or repeated moderation friction, but not for routine low-signal replies.
- `telegram_app/orchestrator/context_builder.py`
  Expose only compact signal digests and recent review results to the observation specialist.
- `agents/observation/agent.py` and `prompts/observation.md`
  Own the bounded review behavior and structured steering brief.
- `telegram_app/orchestrator/orchestrator.py`
  Treat `observation` as a work family that can be routed when review pressure exists, while keeping deterministic follow-on decisions outside the agent itself.

This keeps the runtime thin: live services emit facts, the signal seam owns campaign signal state, and the orchestrator decides when review is worth paying for.

## `CampaignSignal` Shape

Recommended fields:

- `signal_id`
- `campaign_id`
- `source_kind`
- `source_ref`
- `signal_type`
- `severity`
- `state`
- `dedupe_key`
- `summary`
- `context_refs`
- `account_id`
- `community_id`
- `conversation_id`
- `first_happened_at`
- `last_happened_at`
- `occurrence_count`
- `review_eligible`
- `last_reviewed_at`
- `last_review_result_ref`
- `created_at`
- `updated_at`

Notes:

- `source_kind` should stay narrow, such as `live_execution`, `engagement_event`, `external_conversation`, `schedule`, or `operator`
- `source_ref` should point to the smallest useful durable runtime record, such as an action id, event id, conversation id, or schedule id
- `state` should distinguish at least `unresolved`, `reviewed`, `dismissed`, and `superseded`
- `first_happened_at`, `last_happened_at`, and `occurrence_count` let the runtime collapse repeated incidents without losing trend information
- `review_eligible` should let deterministic code store a signal without automatically making it part of observation pressure

## Signal Taxonomy Direction

The first pass should prefer a small stable taxonomy over broad free-form categories.

Recommended initial `signal_type` families:

- `account_flagged_or_banned`
- `account_rate_limited`
- `account_paused_for_risk`
- `community_write_friction`
- `community_paused_for_risk`
- `policy_block_repeated`
- `conversation_escalated`
- `conversation_high_intent_shift`
- `strategy_assumption_invalidated`
- `scheduled_review_due`
- `operator_requested_review`

Recommended initial severity bands:

- `low`
- `medium`
- `high`
- `critical`

The runtime should assign severity deterministically from known conditions instead of asking the model to classify severity after the fact.

## Dedupe And Refresh Rules

Signal persistence should collapse repeated pressure instead of creating one record per raw event.

Recommended v1 dedupe rules:

- repeated incidents of the same `signal_type` on the same `(campaign_id, account_id, community_id, conversation_id)` path should refresh one open signal when the pressure meaning is still the same
- repeated account rate limits within the active cooldown window should usually refresh one signal instead of creating a new one
- repeated `write_forbidden` or moderation friction on the same campaign-community path should refresh one signal and increment `occurrence_count`
- operator-triggered and schedule-triggered reviews should create distinct review-pressure signals only when there is not already an unresolved equivalent
- once a signal is marked `reviewed` or `dismissed`, a materially new incident after a meaningful time gap may open a new signal instead of rewriting history

Recommended first `dedupe_key` inputs:

- `campaign_id + signal_type + account_id`
- `campaign_id + signal_type + community_id`
- `campaign_id + signal_type + conversation_id`
- `campaign_id + signal_type + source_ref`

The exact key depends on the signal family, but the rule should be deterministic and owned by the signal seam, not by each caller.

## Workspace Shape

Recommended campaign workspace layout:

```text
data/campaigns/<campaign-id>/
  signals/
    signals.json
    reviews.json
    cursor.json
```

Recommended storage direction:

- `signals.json` is the compact ledger of current and historical signal records
- `reviews.json` stores sparse structured review outputs, not prompt transcripts
- `cursor.json` stores the last reviewed window or signal refs so repeated reviews do not re-prompt the same incidents by default
- campaign memory markdown remains a downstream projection, not the source of truth for observation state

## Slice 5 Lock Decisions

The remaining observation-review half should not be implemented from broad intent alone.

Lock these decisions for Slice 5:

- observation review runs only from a persisted `observation` work item or an `observation` review schedule, not ad hoc from the live write path
- the observation specialist returns one strict structured result block plus a short operator-facing summary, not free-form advisory prose alone
- runtime code, not the agent, owns signal state transitions after review
- runtime code, not the agent, owns mapping review advice into planning-work refresh actions
- Slice 5 may persist review outputs and make them available to prompts before Slice 6 teaches the main router to prioritize them

This means Slice 5 can be fully built before full observation-priority routing lands, as long as entry into review stays explicit and deterministic.

## Signal Bridge Contract

Current note-promotion logic should not be copied into every live seam.

Instead, extract one reusable bridge with a narrow call shape such as:

- campaign id
- signal type
- severity
- summary
- source kind and source ref
- optional account, community, and conversation refs
- optional review-eligible override
- optional compact context refs

The bridge should:

1. normalize the candidate
2. compute its dedupe key
3. upsert the signal record
4. decide whether review pressure changed
5. optionally promote one sparse campaign-memory note when the incident is major enough

This keeps live execution, engagement projection, and future policy seams consistent.

## Review Triggers

Trigger observation review only for meaningful pressure such as:

- flagged or banned accounts
- repeated campaign-relevant policy blocks
- repeated moderation or community friction
- high-stakes conversation escalations
- strategy-invalidating live outcomes
- scheduled review windows
- explicit operator request

Do not trigger observation review for:

- ordinary inbound replies
- normal successful sends
- one-off low-severity cooldowns with no campaign impact
- conversation noise that does not change campaign posture

## Observation Work Lifecycle

Observation should become a normal campaign work family, not an ad hoc side effect.

Recommended lifecycle:

1. deterministic runtime pressure creates or refreshes an `observation` work item
2. the work item points at the unresolved signals or review window through `context_refs`
3. the observation specialist reviews the bounded digest and returns a structured steering brief
4. deterministic runtime code stores that brief, advances the review cursor, and updates signal states
5. the orchestrator decides whether to create or refresh downstream planning work from the brief

Recommended work-item posture:

- `work_type="observation"`
- `owner_role="observation"`
- `trigger_source` values such as `signal_bridge`, `schedule`, or `operator`
- `refresh_reason` should summarize why review was reopened, such as `repeated community write friction` or `weekly strategy drift review`
- `context_refs` should point to signal ids, review ids, or schedule ids instead of raw logs

The observation specialist should never directly reopen discovery, strategy, or account-planning work. It only returns advice that deterministic runtime code may translate into follow-on work.

## `ObservationReviewBrief` Shape

Recommended output fields:

- `summary`
- `material_change`
- `priority_pressure`
- `suggested_work_item_changes`
- `suggested_posture_updates`
- `operator_attention_needed`
- `recommended_next_step`
- `memory_note_lines`

Recommended shape guidance:

- `material_change` should be a strict yes or no signal for whether the campaign meaningfully changed
- `priority_pressure` should stay small and ordinal, such as `low`, `medium`, `high`
- `suggested_work_item_changes` should name bounded campaign work families or actions like `refresh_strategy`, `refresh_account_planning`, or `keep_current_plan`
- `suggested_posture_updates` should advise, not directly enforce, campaign-level posture changes
- `memory_note_lines` should stay sparse and operator-readable so they can be appended to campaign memory without replaying the whole review

## Locked Review Result Contract

For implementation, persist one exact `ObservationReviewResult` shape in `reviews.json`.

Recommended fields:

- `review_id`
- `campaign_id`
- `work_item_id`
- `trigger_source`
- `review_reason`
- `signal_ids`
- `signal_digest_count`
- `summary`
- `material_change`
- `priority_pressure`
- `suggested_work_item_changes`
- `suggested_posture_updates`
- `operator_attention_needed`
- `recommended_next_step`
- `memory_note_lines`
- `created_at`

Locked field semantics:

- `review_id` is the durable ref later written back to `CampaignSignal.last_review_result_ref`
- `signal_ids` are the exact reviewed signal ids in this result, not a broader campaign window label
- `signal_digest_count` is stored so later debugging and tests can prove bounded input behavior
- `summary` is the canonical compact review conclusion reused in later prompt context
- `memory_note_lines` is the only part of the review automatically eligible for sparse campaign-memory promotion

Recommended first persistence rule:

- append one new review result per completed observation work item rather than rewriting a prior result

## Locked Review Cursor Contract

Persist one compact `ObservationReviewCursor` shape in `cursor.json`.

Recommended fields:

- `campaign_id`
- `last_review_id`
- `last_reviewed_at`
- `last_reviewed_signal_ids`
- `last_reviewed_signal_dedupe_keys`

Locked cursor rules:

- the cursor exists only to avoid immediately re-prompting the same unresolved incidents
- the cursor is not the source of truth for whether a signal is unresolved; signal state still owns that
- `last_reviewed_signal_ids` should contain only the ids reviewed in the latest completed review
- `last_reviewed_signal_dedupe_keys` should be stored too so a newly opened signal with the same dedupe key can still be recognized as recent pressure when helpful

Recommended first-selection rule:

- when assembling a new review batch, prefer unresolved review-eligible signals that are not in the latest cursor set
- if pressure remains high and only cursor-covered unresolved signals exist, allow re-review after a meaningful new refresh such as increased severity, increased occurrence count, or a newer `last_happened_at`

## Locked Agent Output Enums

To keep parsing simple and deterministic, Slice 5 should constrain the agent output values.

Locked `material_change` values:

- `yes`
- `no`

Locked `priority_pressure` values:

- `low`
- `medium`
- `high`

Locked `operator_attention_needed` values:

- `none`
- `recommended`
- `required`

Locked `recommended_next_step` values:

- `keep_current_plan`
- `refresh_strategy`
- `refresh_account_planning`
- `operator_review`

Locked `suggested_work_item_changes[*].action` values:

- `none`
- `refresh`
- `create_if_missing`

Locked `suggested_work_item_changes[*].work_type` values:

- `strategy`
- `account_planning`

Locked `suggested_posture_updates[*].kind` values for Slice 5:

- `campaign_pause_review`
- `community_avoidance_review`
- `account_rest_review`

These posture-update kinds remain advisory only in Slice 5. They may surface operator attention or later policy work, but they do not directly mutate runtime posture.

## Deterministic Follow-On Mapping

The observation specialist should not invent arbitrary next actions.

Runtime code should apply this first mapping:

- `recommended_next_step=keep_current_plan`
  Do not create or refresh planning work unless explicit `suggested_work_item_changes` still asks for a safe `create_if_missing`.
- `recommended_next_step=refresh_strategy`
  Create or refresh `strategy` work.
- `recommended_next_step=refresh_account_planning`
  Create or refresh `account_planning` work.
- `recommended_next_step=operator_review`
  Do not automatically refresh planning work; surface the review summary and any `memory_note_lines` for operator-visible follow-up.

For `suggested_work_item_changes`:

- `action=none` means ignore the row
- `action=create_if_missing` means create the work item only when no open or review-pending item of that type already exists
- `action=refresh` means reopen or refresh the latest item of that type using the same lifecycle helpers used elsewhere in the runtime

Recommended first conflict rule:

- if `recommended_next_step` and `suggested_work_item_changes` disagree, prefer the more conservative interpretation
- specifically, do not auto-refresh a planning family unless both the top-level recommendation and the row-level action support doing so

## Locked Post-Review Signal Transitions

Slice 5 should keep signal state transitions small and deterministic.

Recommended first rules:

- set `last_reviewed_at` and `last_review_result_ref` on every reviewed signal
- keep a signal `unresolved` when the review concludes the pressure still exists and no deterministic runtime change has cleared it
- move a signal to `reviewed` when the review consumed it and the runtime believes the incident was understood but not yet dismissed as irrelevant
- move a signal to `dismissed` only when the review explicitly concluded there is no campaign-steering significance
- reserve `superseded` for a later deterministic state where a newer signal or newer review has clearly replaced the old one

Recommended first simplification for implementation:

- after Slice 5 review, default reviewed signals to `reviewed` unless the deterministic post-review handler has a clear reason to leave them `unresolved`
- keep `dismissed` rare in the first pass
- do not implement `superseded` behavior until a later slice actually needs it

## Temporary Invocation Rule Before Slice 6

Before observation priority is added to the main router, Slice 5 should still have one explicit invocation rule.

Locked first rule:

- scheduled work or a dedicated deterministic handler may run observation review when there is an open or pending `observation` work item
- normal operator turns should not silently enter observation review unless a later routing slice explicitly teaches that behavior

This keeps Slice 5 usable and testable without coupling it to unfinished route-priority work.

Recommended first execution path:

1. deterministic signal pressure creates or refreshes `observation` work
2. a schedule tick or explicit runtime review path selects that work
3. the observation specialist produces the structured result
4. deterministic code persists the review, advances the cursor, updates signal states, and optionally refreshes planning work

## Runtime Responsibilities

Deterministic runtime code should own:

- capturing execution and conversation signals
- deduping repeated incidents
- refreshing small posture state
- storing compact signal records
- deciding whether `observation` work should exist or be refreshed
- selecting the bounded unresolved signals to include in one review
- applying post-review state transitions such as cursor advance and signal resolution
- deciding whether follow-on planning work should be created or refreshed from the review brief

The review agent should own:

- reading compact signal digests
- producing a bounded steering brief
- advising the orchestrator on next steps

The review agent should not:

- mutate work items directly
- bypass policy or execution gates
- scan raw logs or full transcripts by default
- redefine deterministic severity or dedupe rules

## Prompt And Context Direction

Observation prompt inputs should stay compact and structured.

Recommended prompt context:

- current campaign objective and setup posture
- active planning work summary
- the highest-priority unresolved signal digests
- relevant account, community, or conversation refs
- the latest observation review summary if one exists
- a very small number of campaign-memory lines when they materially explain the signals

Avoid passing:

- raw event ledgers
- full transcript histories
- repeated previous review text
- the entire campaign memory or full asset manifest

One practical observation-context fragment could include:

- `observation_review_reason`
- `signal_digest_count`
- `signal_digests: [...]`
- `last_observation_review_summary`
- `current_planning_work_summary`

## Token-Efficiency Rules

- prompt with compact signal digests, not raw logs
- cap the number of unresolved signals per review
- prefer newest unresolved plus highest-severity signals
- persist a review cursor so the same signals are not re-prompted repeatedly
- use `result_summary` and sparse memory notes instead of replaying old reviews
- keep campaign-memory promotion to one or a few durable lines per review, not one line per raw incident

Recommended first limits:

- no more than 8 to 12 signal digests per review
- no more than 1 prior review summary in prompt context
- no more than a few compact context refs per signal

## Integration With Routing And Planning Refresh

This slice should prepare the routing layer without forcing all routing changes into the same code pass.

Deterministic post-review outcomes should be able to:

- leave the current plan untouched when live pressure is real but not strategy-changing
- create or refresh strategy work when live outcomes invalidate targeting or posture assumptions
- create or refresh account-planning work when account availability or community suitability changed
- surface operator-attention guidance without blocking the entire campaign loop

The actual priority ordering between setup, observation, review-pending artifacts, and normal planning work belongs in `orchestrator-routing-and-compatibility.md`, but this slice should define the observation-owned inputs that routing will consume.

## Delivery Sequence Inside This Slice

This plan is easier to implement safely as five small steps:

### Step 1: Signal Models And Storage

- add campaign-signal models and a manager
- persist compact signal records under the campaign workspace
- add tolerant reads so empty or missing signal files are harmless

### Step 2: Deterministic Signal Bridge

- add one reusable bridge for live seams
- emit signals from live execution first because that seam already sees the clearest high-value operational outcomes
- keep campaign-memory promotion sparse and deterministic

### Step 3: Observation Work Refresh Rules

- define review-pressure evaluation
- create or refresh `observation` work when unresolved high-value signals justify it
- keep this fully deterministic and testable before any review-agent work lands

### Step 4: Observation Specialist And Review Cursor

- add the `observation` specialist prompt and bounded review contract
- persist review results and cursor state
- mark reviewed signals so identical incidents are not repeatedly re-prompted
- keep Slice 5 entry explicit through observation work selection, not through implicit router priority

### Step 5: Planning Follow-On Integration

- translate structured observation advice into deterministic planning refresh actions
- ensure strategy and account-planning refreshes reuse the same work-item lifecycle helpers as other runtime triggers
- keep execution and policy gates outside the observation specialist
- prefer conservative no-op handling when review advice is ambiguous or mixed

## Concrete File-Level Work List

- `telegram_app/campaign_signals/models.py`
  Add signal, review-result, and cursor records.
- `telegram_app/campaign_signals/manager.py`
  Add persistence, dedupe, unresolved selection, review-result storage, cursor storage, and state-transition helpers.
- `telegram_app/campaign_signals/bridge.py`
  Add the reusable signal-emission API for live seams.
- `telegram_app/campaign_signals/review.py`
  Add deterministic observation-pressure and work-refresh helpers.
- `telegram_app/live_execution/service.py`
  Emit major execution and policy-outcome signals through the bridge.
- `telegram_app/engagement/listener.py`
  Keep raw inbound persistence unchanged, but leave room to emit only meaningful inbound-driven signal candidates.
- `telegram_app/external_conversations/projector.py`
  Emit conversation-linked campaign signals for escalations or material thread-state changes where appropriate.
- `telegram_app/campaign_memory/operational_notes.py`
  Keep sparse memory-note projection as a downstream effect, not the primary signal store.
- `telegram_app/models/work_item.py`
  Add any minimal metadata needed for `observation` work refs if current fields are not enough.
- `telegram_app/work_items/manager.py`
  Reuse or extend helpers so `observation` work refresh behaves like other campaign work families.
- `telegram_app/scheduling/manager.py`
  Support recurring `observation` review schedules where useful.
- `telegram_app/orchestrator/context_builder.py`
  Inject bounded signal digests and recent review summaries into observation context only.
- `telegram_app/orchestrator/orchestrator.py`
  Add the explicit observation-review execution path, persist review outcomes, and translate structured advice into deterministic follow-on actions.
- `agents/observation/agent.py`
  Add the new advisor-only specialist.
- `prompts/observation.md`
  Define the bounded review brief contract and non-goals clearly.
- `tests/`
  Add focused storage, dedupe, review-pressure, cursor, routing, and regression coverage.

## Migration Rules

- keep current campaign-memory note promotion working while signal storage is introduced
- do not require a full backfill of historical live notes into campaign signals for the first cut
- do not make observation review mandatory for all campaigns before deterministic signal capture is already useful on its own
- do not let observation work bypass the existing work-item and schedule control plane
- prefer additive files and tolerant reads over schema-rewriting older campaign workspaces

Recommended migration order:

- land deterministic signal capture first
- prove observation work refresh without LLM review
- then add the specialist, review persistence, and follow-on mapping
- land full route priority only in the later routing slice

## Acceptance Criteria

- major live outcomes create deduped signal records
- repeated incidents refresh existing unresolved signals instead of creating noisy duplicates
- observation review is not invoked inside the live execution path itself
- observation work can become active when meaningful review pressure exists
- the review agent returns structured steering advice without mutating campaign state directly
- repeated identical incidents do not cause repeated expensive reviews
- campaign memory receives sparse durable notes from major incidents or review conclusions without becoming the signal source of truth
- strategy and account-planning refreshes can later consume observation advice through normal work-item helpers

## Validation

- focused tests for signal dedupe and refresh rules
- tests for observation-work creation and reuse
- tests for review-cursor behavior
- tests for structured observation result parsing and enum validation
- tests for deterministic follow-on mapping from review advice into planning refresh actions
- tests proving low-signal live events do not create observation pressure
- scheduled-review tests that consume unresolved signals and persist a compact steering result
- regression tests proving normal planning turns are unchanged when no observation work is active
- manual smoke test where a repeated live-execution policy block produces one refreshed signal and later one bounded observation review

## Open Questions To Resolve Before Coding

- Which inbound conversation moments should count as true campaign-steering signals in the first pass versus stay as conversation-local state only?
- Do we want `reviews.json` only, or also a small human-readable `signals/index.md` compatibility view after the storage contract is stable?
