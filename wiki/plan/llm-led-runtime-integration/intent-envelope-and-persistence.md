# Intent Envelope And Persistence

## Goal

Define the smallest compiled-intent contract and persistence seam that can gradually replace the current mix of marker blocks, phrase parsers, and hardcoded control transitions.

## Why This Slice Comes First

The runtime cannot migrate toward freeform reasoning plus structured compilation until there is a stable thing to compile into.

That thing should be:

- typed enough for deterministic code
- broad enough to support new intent kinds over time
- small enough to land without rewriting every current contract at once

## Minimum Intent Envelope

Every compiled intent should preserve at least:

- `intent_id`
- `kind`
- `summary`
- `payload`
- `grounding_refs`
- `source_role`
- `confidence` or `ambiguity`
- `safety_class`
- `status`

Recommended initial lifecycle fields:

- `created_at`
- `updated_at`
- `accepted_at`
- `rejected_at`
- `applied_at`
- `rejection_reason`
- `application_result`

## Recommended Safety Classes

Start with a compact shared set:

- `advisory`
- `state_mutation`
- `schedule_mutation`
- `execution_adjacent`
- `external_write`

These classes should not replace policy.

They should let deterministic policy know what kind of proposal it is evaluating.

## Recommended First Intent Kinds

The first migration wave should focus on high-leverage intent kinds:

- `campaign_control.update_voice`
- `campaign_control.update_safeguard`
- `campaign_control.pause_scope`
- `campaign_control.resume_scope`
- `schedule.create`
- `schedule.pause`
- `schedule.resume`
- `work.propose`
- `work.refresh`
- `memory.note`
- `review.request`

Execution requests should come later.

The first goal is to stabilize control and planning mutation, not to widen external autonomy prematurely.

## Recommended Runtime Seam

Add one narrow runtime package such as:

- `telegram_app/compiled_intents/models.py`
- `telegram_app/compiled_intents/store.py`
- `telegram_app/compiled_intents/compiler.py`
- `telegram_app/compiled_intents/validators.py`
- `telegram_app/compiled_intents/applicators.py`

The exact filenames can vary, but the responsibilities should stay separate:

- models define the envelope
- store persists and queries records
- compiler turns source input into intents
- validators check per-kind contract soundness
- applicators apply accepted intents to existing runtime managers

## Persistence Direction

Compiled intents should become durable records whenever the runtime depends on them for:

- state mutation
- schedule mutation
- work creation or refresh
- authorization
- execution

Not every intermediate thought needs to be persisted.

The durable unit is the compiled proposal the runtime actually relies on.

## Acceptance Criteria

This slice is complete when:

- the repo has one durable compiled-intent record shape
- at least a small shared validator path exists by intent kind
- intent status can move through `proposed`, `accepted`, `rejected`, and `applied`
- existing runtime managers can be targeted by narrow applicators without changing their persistence formats yet
- developers can inspect what was proposed before a mutation is applied
