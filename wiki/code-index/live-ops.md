# Live Ops Map

## Purpose

This map covers the operator-facing live-ops seam that turns natural-language Telegram control requests into deterministic runtime actions.

Use it when the task touches live status summaries, pause or resume flows, autonomous-send posture changes, campaign voice or safeguard overrides, review approval or dismissal, or control completeness reporting.

## Read First

- [telegram_app/live_ops/models.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/live_ops/models.py)
- [telegram_app/live_ops/manager.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/live_ops/manager.py)
- [telegram_app/live_ops/service.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/live_ops/service.py)
- [telegram_app/live_ops/formatter.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/live_ops/formatter.py)
- [telegram_app/orchestrator/orchestrator.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/orchestrator/orchestrator.py)
- [telegram_app/autonomous_send/service.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/autonomous_send/service.py)
- [telegram_app/engagement_brain/context_builder.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/engagement_brain/context_builder.py)
- [server.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/server.py)
- [wiki/plan/engagement-machine-readiness/telegram-live-ops-surface.md](C:/Users/ravil/OneDrive/Desktop/tg-swarm/wiki/plan/engagement-machine-readiness/telegram-live-ops-surface.md)

## What Lives Here

- `models.py`: normalized live-ops intents, durable control-profile records, attention items, and control-completeness states
- `manager.py`: campaign-backed JSON persistence for operator-owned live-ops controls
- `service.py`: natural-language intent detection, safe scope resolution, status assembly, pause/resume routing, posture changes, review approval or dismissal, control-gap detection, and campaign-scoped tone-policy extraction for more Telegram-native messaging
- `formatter.py`: compact Telegram-friendly rendering for status, blocked reasons, and pending reviews

## Boundaries

- Keep live-ops intent interpretation here and in `orchestrator.py`, not inside the execution queue or autonomous-send authorizer.
- Keep direct live execution ownership in `telegram_app/live_execution/`.
- Keep pending autonomous-review lifecycle ownership in `telegram_app/autonomous_send/`.
- Keep live reply drafting and bounded conversation reasoning in `telegram_app/engagement_brain/`.
- Keep control storage durable and campaign-scoped so the operator can adjust settings conversationally without relying on recent chat memory alone.
- Keep tone policy explicit and operator-owned here, while downstream prompts and reply builders consume the persisted profile instead of re-inferring style from recent chat turns.

## Related Tests

- [tests/test_live_ops.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/tests/test_live_ops.py)
- [tests/test_autonomous_send.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/tests/test_autonomous_send.py)
- [tests/test_engagement_brain.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/tests/test_engagement_brain.py)
- [tests/test_telegram_runtime_state.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/tests/test_telegram_runtime_state.py)
