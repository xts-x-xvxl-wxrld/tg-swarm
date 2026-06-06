# Engagement Policy Map

## Purpose

This map covers the campaign-owned policy seam that decides when managed-account replies should send now, delay, or intentionally not send.

Use it when the task touches quiet hours, reply-latency tiers, negative-signal suppression, or lightweight reply-outcome metrics.

## Read First

- [telegram_app/engagement_policy/models.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/engagement_policy/models.py)
- [telegram_app/engagement_policy/manager.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/engagement_policy/manager.py)
- [telegram_app/engagement_policy/service.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/engagement_policy/service.py)
- [telegram_app/engagement_brain/coordinator.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/engagement_brain/coordinator.py)
- [telegram_app/external_conversations/timing.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/external_conversations/timing.py)
- [telegram_app/live_execution/service.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/live_execution/service.py)

## What Lives Here

- `models.py`: campaign-scoped quiet-hours config, reply-latency tiers, negative-signal thresholds, and lightweight outcome-metric contracts
- `manager.py`: file-backed `engagement-policy.json` persistence per campaign
- `service.py`: deterministic policy resolution for reply timing, quiet-hours shifts, suppression, and feedback recording
- `engagement_brain/coordinator.py`: queue-time use of the policy seam before any outbound reply is enqueued
- `external_conversations/timing.py`: follow-up-window quiet-hours shaping through the same campaign-owned policy seam
- `live_execution/service.py`: execution-outcome feedback written back into policy metrics when actions carry policy metadata

## Boundaries

- Keep drafting and commercial reasoning out of this seam. The engagement brain still decides what it wants to say.
- Keep hard Telegram safety checks out of this seam. Live execution policy still owns approval, consent, account health, and community pause enforcement.
- Keep campaign-owned timing state here rather than scattering timing heuristics across listener, transport, or MTProto capability code.
- Keep metrics lightweight and prompt-safe. This seam should accumulate compact learning signals, not raw chat transcripts.

## Related Tests

- [tests/test_engagement_policy.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/tests/test_engagement_policy.py)
- [tests/test_external_conversation_timing.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/tests/test_external_conversation_timing.py)
- [tests/test_engagement_brain.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/tests/test_engagement_brain.py)
- [tests/test_live_execution.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/tests/test_live_execution.py)
