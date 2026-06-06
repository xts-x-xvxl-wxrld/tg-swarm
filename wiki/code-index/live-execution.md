# Live Execution Map

## Purpose

This map covers the dedicated runtime seam that turns queued campaign-linked live actions into audited managed-account Telegram actions.

Use it when the task touches action queueing, retries, dispatch workers, or conversation-linked outbound execution.

## Read First

- [telegram_app/live_execution/models.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/live_execution/models.py)
- [telegram_app/live_execution/manager.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/live_execution/manager.py)
- [telegram_app/live_execution/policy.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/live_execution/policy.py)
- [telegram_app/live_execution/policy_state.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/live_execution/policy_state.py)
- [telegram_app/live_execution/service.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/live_execution/service.py)
- [telegram_app/engagement_policy/service.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/engagement_policy/service.py)
- [telegram_app/live_ops/service.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/live_ops/service.py)
- [telegram_app/live_execution/runner.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/live_execution/runner.py)
- [telegram_app/prepared_execution/service.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/prepared_execution/service.py)
- [telegram_app/external_conversations/manager.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/external_conversations/manager.py)
- [server.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/server.py)
- [wiki/plan/live-engagement-mvp/live-execution-runtime.md](C:/Users/ravil/OneDrive/Desktop/tg-swarm/wiki/plan/live-engagement-mvp/live-execution-runtime.md)

## What Lives Here

- `models.py`: durable action and attempt records plus lifecycle enums, including low-risk non-send actions such as `mark_read` and `leave_dialog`
- `manager.py`: campaign-backed JSON persistence, idempotency lookup, queue indexes, claim state, and deterministic non-uniform tie-breaking for ready actions
- `policy.py`: normalized execution-time guardrail evaluation, approval-context validation, account cooldowns, and account-warmup-aware action-class pacing
- `policy_state.py`: durable account pause/cooldown posture used by the policy seam
- `service.py`: policy-gated capability dispatch, low-risk action execution, structured approval-context pass-through, bounded retry jitter, conversation updates, sparse observation/memory promotion for major live-engagement incidents, and compact feedback hooks for campaign-owned engagement timing metrics
- `telegram_app/live_ops/service.py`: the operator-facing composition layer that inspects this seam, applies pause or resume controls, and materializes approved autonomous reviews without turning `live_execution/` into chat-routing code
- `runner.py`: dedicated worker loop for `server.py --run-live-executor`
- `prepared_execution/service.py`: the upstream activation bridge that snapshots approved account plans, links queued actions back to a plan revision, and cancels stale unclaimed actions safely when a later revision supersedes them
- `telegram_app/capabilities/mtproto/warmup.py`: shared 5-day action-class warmup budgets used by the registry and surfaced into prompt-safe account views
- `telegram_app/compiled_intents/applicators.py`: the deterministic compiled-intent seam that can enqueue bounded low-risk actions without opening raw prompt-to-write execution

## Boundaries

- Keep planning and strategy out of this seam. It executes already-normalized actions only.
- Keep account-plan activation out of this seam. `telegram_app/prepared_execution/` may enqueue actions here, but plan revisioning and stale invalidation ownership should stay upstream.
- Keep visible Telegram writes and low-risk queueable non-sends here. Scheduler and orchestrator paths may enqueue actions, but should not bypass this worker for live sends or autonomous low-risk account actions.
- Keep operator-facing chat control out of this seam. `telegram_app/live_ops/` may call its narrow helpers, but live status formatting and natural-language routing should stay upstream.
- Keep approval-context enforcement here as a deterministic backstop. Flexible drafting upstream should never be able to bypass this seam.
- Keep reply-latency selection and quiet-hours sampling out of this seam. Campaign-owned humanized timing now belongs to `telegram_app/engagement_policy/`, while this seam records only execution outcomes back into that policy.
- Keep raw inbound evidence in `telegram_app/engagement/` and compact campaign conversation state in `telegram_app/external_conversations/`.
- Keep higher-consequence outbound sends policy-mediated. Low-risk autonomy may widen here, but direct prompt-to-write execution should still stay out.

## Related Tests

- [tests/test_live_execution.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/tests/test_live_execution.py)
- [tests/test_external_conversations.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/tests/test_external_conversations.py)
- [tests/test_engagement_listener.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/tests/test_engagement_listener.py)
