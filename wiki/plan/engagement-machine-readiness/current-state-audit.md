# Current State Audit

## Purpose

This note is the compact readiness baseline for the live engagement machine.

It maps the current repo state against:

- [Live Engagement MVP](../live-engagement-mvp/index.md)
- [Unified Campaign Loop Rebuild](../unified-campaign-loop-rebuild/index.md)

The goal is to keep three things separate:

1. what is already shipped in code
2. what is designed and partially implemented but still not part of the active runtime loop
3. what is still a real feature gap after the machine becomes runnable

## Summary

The repo is no longer missing the whole engagement machine.

Most of the lower-level runtime foundation is already present:

- campaign setup, assets, work items, and schedules
- inbound listening and durable external conversation state
- live execution queueing, retries, and policy checks
- bounded engagement-brain reasoning
- campaign signals and observation review persistence

The readiness gap is now mostly integration work, not blank-slate architecture work.

## Shipped Baseline

### Campaign Control Plane

- `telegram_app/campaign_setup.py` already owns guided setup state.
- `telegram_app/campaign_assets/` already owns campaign asset storage and summaries.
- `telegram_app/work_items/` and `telegram_app/scheduling/` already provide campaign-attached planning work and recurring schedules.
- `telegram_app/orchestrator/orchestrator.py` already contains the first observation-aware routing cuts.

### Live Conversation Runtime

- `telegram_app/engagement/listener.py` already persists managed-account inbound events.
- `telegram_app/external_conversations/projector.py` already projects inbound activity into durable campaign conversation threads.
- `telegram_app/external_conversations/timing.py` already persists follow-up windows and timing state.
- `telegram_app/live_execution/` already owns durable outbound action queueing, dispatch, retries, and policy checks.

### Reasoning And Safety

- `telegram_app/engagement_brain/` already contains the bounded decision service and queue coordinator.
- `telegram_app/campaign_signals/` already persists signal records, review cursors, and observation pressure refresh state.
- `telegram_app/live_execution/policy.py` and `telegram_app/live_execution/policy_state.py` already enforce cooldown and pause posture.

### Validation Baseline

Focused live-engagement runtime coverage already exists for:

- `tests/test_engagement_listener.py`
- `tests/test_external_conversations.py`
- `tests/test_external_conversation_timing.py`
- `tests/test_live_execution.py`
- `tests/test_engagement_brain.py`

## Remaining Readiness Gaps

The implementation-ready gaps are now split into dedicated step documents:

1. [Plan Activation Contract](./plan-activation-contract.md)
   Turn approved account plans into campaign-owned live execution state.
2. [Conversation Review Triggering](./conversation-review-triggering.md)
   Run bounded engagement-brain reviews automatically for inbound and due follow-up moments.
3. [Autonomous Send Approval Alignment](./autonomous-send-approval-alignment.md)
   Align autonomous proposal execution with the current MTProto approval gate.
4. [Telegram Live Ops Surface](./telegram-live-ops-surface.md)
   Expose live pause, resume, inspection, and escalation control through Telegram.

## Follow-On Gaps After Readiness

These are real product gaps, but they are better treated as the next wave after the core machine is runnable:

1. [Operator Takeover And Closure](./operator-takeover-and-closure.md)
   Explicit operator-owned conversation state and clean return-to-automation flow.
2. [Conversion And Handoff Runtime](./conversion-and-handoff-runtime.md)
   A dedicated runtime seam for conversion progression and strong-lead handoff.

## Recommended Read Order

If the goal is to make the engagement machine runnable soon, start with:

1. [Implementation Sequence](./implementation-sequence.md)
2. [Plan Activation Contract](./plan-activation-contract.md)
3. [Conversation Review Triggering](./conversation-review-triggering.md)
4. [Autonomous Send Approval Alignment](./autonomous-send-approval-alignment.md)
5. [Telegram Live Ops Surface](./telegram-live-ops-surface.md)

That order keeps the work centered on wiring the machine that already exists instead of opening broader product tracks too early.
