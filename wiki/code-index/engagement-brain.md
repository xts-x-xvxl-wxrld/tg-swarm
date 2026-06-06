# Engagement Brain Map

## Purpose

This map covers the bounded live-engagement reasoning seam that turns one persisted conversation moment into promoted-thread commercial reasoning, then into a queueable live action when policy allows it.

Use it when the task touches live conversation context assembly, tone/claims contracts, brain proposals, or the proposal-to-queue bridge.

## Read First

- [telegram_app/engagement_brain/models.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/engagement_brain/models.py)
- [telegram_app/engagement_brain/service.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/engagement_brain/service.py)
- [telegram_app/engagement_brain/context_builder.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/engagement_brain/context_builder.py)
- [telegram_app/engagement_brain/coordinator.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/engagement_brain/coordinator.py)
- [telegram_app/engagement_policy/service.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/engagement_policy/service.py)
- [telegram_app/engagement_brain/review_dispatcher.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/engagement_brain/review_dispatcher.py)
- [telegram_app/engagement_triage/service.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/engagement_triage/service.py)
- [telegram_app/engagement_triage/models.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/engagement_triage/models.py)
- [telegram_app/engagement_brain/review_runner.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/engagement_brain/review_runner.py)
- [telegram_app/autonomous_send/service.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/autonomous_send/service.py)
- [telegram_app/autonomous_send/manager.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/autonomous_send/manager.py)
- [telegram_app/external_conversations/manager.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/external_conversations/manager.py)
- [telegram_app/engagement/storage.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/engagement/storage.py)
- [telegram_app/live_execution/service.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/live_execution/service.py)
- [wiki/plan/live-engagement-mvp/engagement-brain-and-reply-policy.md](C:/Users/ravil/OneDrive/Desktop/tg-swarm/wiki/plan/live-engagement-mvp/engagement-brain-and-reply-policy.md)

## What Lives Here

- `models.py`: the promoted-thread review contract, proposal types, tone/claim contract types, qualification state, risk labels, and end-to-end run result
- `service.py`: the deeper commercial-reasoning seam plus bounded drafting; it runs structured promoted-thread review first, updates belief-state meaning, then drafts only when the chosen next move needs copy
- `context_builder.py`: bounded context assembly from conversation state, campaign artifacts, recent engagement evidence, and community/autonomy posture
- `coordinator.py`: the runtime bridge that runs the brain, persists typed `engagement.next_move` / belief-update / learning-note compiled intents, routes actionable proposals through autonomous-send authorization, evaluates execution policy on allowed sends, runs campaign-owned timing or suppression, and enqueues runnable live actions
- `telegram_app/engagement_triage/`: the cheap first-pass read layer that uses the summary-tier model role, persists compact triage state, and decides whether a thread should be promoted into deeper commercial reasoning
- `telegram_app/autonomous_send/`: the narrow control-plane seam that stamps explicit autonomous approved-send context for grounded supported replies and retires stale review-state from the old manual-review path
- `review_dispatcher.py`: the production background path that claims persisted inbound or due follow-up review moments, runs cheap triage first, and records completion safely before or after deeper review
- `review_runner.py`: the dedicated worker loop for continuous conversation review dispatch

## Boundaries

- Keep the brain separate from raw inbound listening. Ingestion still belongs to `telegram_app/engagement/`.
- Keep durable thread posture separate from reasoning. Conversation identity and status still belong to `telegram_app/external_conversations/`.
- Keep typed proposal persistence separate from authorization. Compiled-intent storage and deterministic applicators now hold review meaning and memory updates before send policy runs.
- Keep send authorization separate from the brain. Campaign-owned autonomous-send posture, structured approved-send context, and review-needed persistence belong to `telegram_app/autonomous_send/`.
- Keep hard allow/block/cooldown enforcement separate from the brain. Deterministic execution-time policy still belongs to `telegram_app/live_execution/policy.py`.
- Keep humanized quiet-hours and latency policy separate from drafting. Campaign-owned reply timing now belongs to `telegram_app/engagement_policy/`.
- Keep visible Telegram writes separate from the brain. Queue persistence and dispatch still belong to `telegram_app/live_execution/`.

## Related Tests

- [tests/test_engagement_brain.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/tests/test_engagement_brain.py)
- [tests/test_conversation_review_triggering.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/tests/test_conversation_review_triggering.py)
- [tests/test_external_conversations.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/tests/test_external_conversations.py)
- [tests/test_live_execution.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/tests/test_live_execution.py)
