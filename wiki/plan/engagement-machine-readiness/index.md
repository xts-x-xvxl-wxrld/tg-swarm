# Engagement Machine Readiness

## Goal

Capture the current implementation status of the live engagement machine across the existing:

- [Live Engagement MVP](../live-engagement-mvp/index.md)
- [Unified Campaign Loop Rebuild](../unified-campaign-loop-rebuild/index.md)

This folder is not a replacement plan.

It is a status bridge that answers:

- what is already landed in code
- what is designed but still not connected into the runtime path
- what remains genuinely unbuilt

## Why This Exists

The original MVP and rebuild plans were written before several newer runtime seams landed in code.

That creates a gap between:

- what the plans still describe as future work
- what the repo already implements
- what is actually blocking end-to-end engagement-machine readiness now

This folder keeps that distinction explicit so future implementation work can focus on the real remaining gaps instead of re-planning already-landed slices.

## Relationship To Existing Plans

- [Live Engagement MVP](../live-engagement-mvp/index.md) remains the product-level north-star and workstream map.
- [Unified Campaign Loop Rebuild](../unified-campaign-loop-rebuild/index.md) remains the campaign-control-plane integration series.
- This readiness folder is a current-state audit layered on top of both.

## Document Map

1. [Current State Audit](./current-state-audit.md)
   A compact baseline of what is already shipped, what still blocks readiness, and how the remaining work is grouped.
2. [Implementation Sequence](./implementation-sequence.md)
   The recommended execution order for turning the existing seams into one runnable engagement machine.
3. [Plan Activation Contract](./plan-activation-contract.md)
   Step 1: how approved account plans become campaign-owned live execution state.
4. [Conversation Review Triggering](./conversation-review-triggering.md)
   Step 2: how inbound and due follow-up moments start bounded engagement-brain reviews in production.
5. [Autonomous Send Approval Alignment](./autonomous-send-approval-alignment.md)
   Step 3: how bounded autonomous proposals align with the current MTProto approval posture.
6. [Telegram Live Ops Surface](./telegram-live-ops-surface.md)
   Step 4: how operators inspect, pause, resume, and steer live execution through Telegram.
7. [Operator Takeover And Closure](./operator-takeover-and-closure.md)
   Step 5: how a live conversation becomes operator-owned, pauses automation safely, and can later be returned.
8. [Conversion And Handoff Runtime](./conversion-and-handoff-runtime.md)
   Step 6: how qualified conversations progress into a concrete business next step instead of stopping at engagement.

## Intended Use

- Read this folder before starting new live-engagement implementation slices.
- Use [Implementation Sequence](./implementation-sequence.md) as the default delivery order unless a narrower blocker forces a local reorder.
- Use the step documents as the source of truth for execution-ready readiness work.
- Update this folder when a designed-but-unwired item becomes part of the real runtime path.
