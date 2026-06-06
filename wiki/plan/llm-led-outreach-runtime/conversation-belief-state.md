# Conversation Belief State

## Goal

Persist explicit triage state and belief state so live reasoning accumulates structured meaning across turns instead of re-judging every thread from scratch.

## Why This Slice Exists

The external conversation seam already owns durable thread state.

It is the natural place to persist:

- cheap triage output
- deeper belief-state output

without leaking those responsibilities into ingestion, execution, or live ops.

## Primary Seams

- [telegram_app/external_conversations/models.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/external_conversations/models.py)
- [telegram_app/external_conversations/manager.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/external_conversations/manager.py)
- [telegram_app/engagement_brain/context_builder.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/engagement_brain/context_builder.py)
- [telegram_app/qualification/service.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/qualification/service.py)

## Recommended Shape

Add explicit nested state records rather than scattering many new flat fields directly on the main conversation record.

Recommended concepts:

- `triage_state`
- `belief_state`

### Triage State

Should preserve lightweight current inbound meaning such as:

- interest signal
- urgency signal
- objection hints
- review priority
- promoted flag
- last triaged at

### Belief State

Should preserve deeper accumulated meaning such as:

- current intent posture
- known objections
- known fit signals
- unanswered questions
- commercial stage
- last meaningful shift
- suggested next move
- last belief update timestamp

## Compatibility Rule

Existing fields such as `summary`, `next_action_type`, `next_action_reason`, `qualification_summary`, and `handoff_summary` can remain.

They should become compatibility and operator-facing views built from richer structured state, not the only durable record of meaning.

## Non-Goals

- creating a full CRM schema
- adding broad speculative abstractions for future channels
- moving qualification ownership out of its current seam

## Exit Criteria

- triage and belief state persist in campaign conversation records
- the context builder can read those records back into promoted-thread review
- compatibility fields still render correctly for current operator surfaces
