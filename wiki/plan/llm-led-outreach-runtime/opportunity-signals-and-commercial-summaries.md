# Opportunity Signals And Commercial Summaries

## Goal

Model positive momentum and expose campaign-level commercial traction through the existing signal, continuous-ops, and live-ops seams.

## Why This Slice Exists

The current runtime is better at surfacing friction than traction.

This slice should correct that imbalance without moving strategy logic into deterministic reporting code.

## Primary Seams

- [telegram_app/campaign_signals/models.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/campaign_signals/models.py)
- [telegram_app/campaign_signals/manager.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/campaign_signals/manager.py)
- [telegram_app/campaign_signals/bridge.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/campaign_signals/bridge.py)
- [telegram_app/continuous_ops/models.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/continuous_ops/models.py)
- [telegram_app/continuous_ops/manager.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/continuous_ops/manager.py)
- [telegram_app/live_ops/models.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/live_ops/models.py)
- [telegram_app/live_ops/service.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/live_ops/service.py)

## Scope

- add opportunity and yield signals alongside risk signals
- summarize commercial traction in continuous ops
- expose commercially meaningful counts and attention items in live ops

## Example Signal Families

- repeated inbound before reply
- clarified need
- objection resolved
- pricing interest
- public-to-DM transition
- CTA acceptance
- conversion-ready thread
- handoff delivered
- high-yield account activity
- high-yield community activity

## Reporting Direction

Continuous ops should gain campaign-level facts such as:

- promising active thread count
- objection-heavy thread count
- conversion-ready thread count
- unresolved high-opportunity thread count
- stale previously promising thread count

Live ops should expose operator-facing status that helps answer:

- where traction is actually happening
- which conversations deserve attention first
- which accounts and communities are producing useful momentum

## Non-Goals

- building a separate BI system
- turning operator status into a verbose analytics dashboard
- moving campaign strategy into reporting code

## Exit Criteria

- positive momentum is persisted as a first-class runtime fact
- continuous ops summarizes commercial traction alongside operational readiness
- live ops status becomes commercially informative without losing its control focus
