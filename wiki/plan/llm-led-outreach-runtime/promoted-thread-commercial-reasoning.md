# Promoted-Thread Commercial Reasoning

## Goal

Make the deeper promoted-thread path truly LLM-led in its commercial decisioning while preserving deterministic authorization and execution boundaries.

## Why This Slice Exists

The current deeper review path is not yet truly LLM-led in its next-move decisioning.

The model mainly drafts bounded text, while substantial commercial judgment still lives in heuristics.

This slice changes that.

## Primary Seams

- [telegram_app/engagement_brain/service.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/engagement_brain/service.py)
- [telegram_app/engagement_brain/models.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/engagement_brain/models.py)
- [telegram_app/engagement_brain/context_builder.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/engagement_brain/context_builder.py)
- [telegram_app/engagement_brain/coordinator.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/engagement_brain/coordinator.py)

## Scope

- replace deeper heuristic next-move choice with structured LLM review for promoted threads
- update belief state from the deeper review result
- keep draft generation bounded and separate from authorization

## Structural Boundary

The deeper reasoning layer should own:

- conversation interpretation
- belief-state updates
- commercial next-move selection
- learning-worthy note emission when useful

It should not own:

- DM consent posture
- campaign or conversation pause rules
- cooldowns
- queue claims
- retries
- Telegram capability dispatch

## Recommended Refactor Direction

Split the current service responsibilities more clearly:

- one review contract for promoted-thread commercial reasoning
- one bounded drafting contract for text generation when the chosen next move requires copy

This keeps commercial judgment separate from text realization.

## Non-Goals

- bypassing autonomous-send authorization
- bypassing live execution policy
- turning the runtime into unconstrained freeform autonomy

## Exit Criteria

- promoted-thread review is model-led in next-move selection
- deterministic heuristics are no longer the main commercial decision engine
- the coordinator still hands all sends through authorization and deterministic execution policy
