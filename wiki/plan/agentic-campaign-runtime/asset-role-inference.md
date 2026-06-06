# Asset Role Inference

## Goal

Define how uploaded campaign assets become usable for more than one purpose without requiring manual operator labeling as the default path.

## Core Problem

The current runtime stores assets cleanly, but outbound eligibility still assumes explicit operator labeling.

That is too deterministic for the target product direction.

## Desired Direction

The orchestrator should infer one or more roles for each asset, such as:

- campaign context
- outbound media
- qualification material
- conversion support
- trust signal

## Important Principle

Asset roles should be additive, not exclusive.

One brochure may be:

- useful for campaign understanding
- useful as an outbound image
- useful as proof in a later DM

## First Questions To Lock

- which inferred roles need durable persistence in MVP
- whether operator override is immediate or review-based
- how confidence and rationale are stored
- how inferred roles affect what specialists and live execution can access

## Expected Deliverables

- inferred multi-role asset metadata
- a prompt-safe asset summary view for orchestrator and specialists
- conservative operator-visible notes when asset use is uncertain

## File-Level Direction

Expected touchpoints will likely include:

- `telegram_app/campaign_assets/manager.py`
- `telegram_app/campaign_assets/intake.py`
- `telegram_app/campaign_assets/analyzers.py`
- `telegram_app/orchestrator/context_builder.py`
- later live-execution and strategy consumers
