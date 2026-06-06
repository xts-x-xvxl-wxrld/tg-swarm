# Live Engagement MVP Plan

## Goal

Evolve the current planning-first Telegram runtime into a live engagement MVP for managed user accounts.

The target MVP should be able to:

- join and participate in selected Telegram groups through managed accounts
- continue bounded group conversations when the campaign policy allows it
- reply in DMs only after the external user messages first
- observe outcomes and update campaign state, account state, and next actions
- remain operator-visible, approval-aware, and easy to pause

## Why This Plan Exists

The current runtime is already strong at:

- target discovery
- strategy generation
- account planning
- campaign memory
- MTProto-backed account reads plus basic join/send primitives

What it does not yet have is a live engagement runtime that can listen, decide, act, observe, and adapt over time.

This plan breaks that gap into a small set of concrete additions that can be designed and built independently.

## MVP Boundaries

In scope:

- managed-account group participation
- reply-driven DM handling after inbound contact from an external user
- audited joins, posts, replies, read-state updates, and follow-up observations
- operator pause, review, and escalation controls

Out of scope:

- cold outbound DMs to strangers
- high-volume multi-account growth loops
- rich analytics dashboards
- self-optimizing experimentation systems
- full identity-shaping and advanced social actions

## Read First

- [Campaign North Star](campaign-north-star.md)
- [Managed Account Operations](../../spec/managed-account-operations.md)
- [Account Capability](../../spec/account-capability.md)
- [Approval And Guardrails](../../spec/approval-and-guardrails.md)
- [App Runtime Architecture](../../spec/app-runtime-architecture.md)
- [Campaign Operations Model](../../spec/campaign-operations-model.md)

## Workstreams

1. [Inbound Account Event Ingestion](inbound-account-event-ingestion.md)
2. [External Conversation State](external-conversation-state.md)
3. [Live Execution Runtime](live-execution-runtime.md)
4. [Managed Account Capability Expansion](managed-account-capability-expansion.md)
5. [Safety Policy And Guardrails](safety-policy-and-guardrails.md)
6. [Observation And Adaptation](observation-and-adaptation.md)
7. [Engagement Brain And Reply Policy](engagement-brain-and-reply-policy.md)
8. [Operator Review And Ops Surface](operator-review-and-ops-surface.md)

## Supporting Notes

- [Humanized Engagement Timing](humanized-engagement-timing.md) is a later hardening note for randomized read, reply, and one-time follow-up timing. It is intentionally downstream of the current MVP workstreams and should land after the core live-engagement loop is stable.

## How To Use This Folder

- Use [Campaign North Star](campaign-north-star.md) as the shared operating target for the whole live-engagement MVP.
- Use each workstream file as the implementation-focused translation of one part of that operating target.
- When a workstream grows, keep its technical detail in the workstream file and keep `campaign-north-star.md` short and stable.

## Recommended Build Order

1. Inbound account event ingestion
2. External conversation state
3. Live execution runtime
4. Managed account capability expansion
5. Safety policy and guardrails
6. Observation and adaptation
7. Engagement brain and reply policy
8. Operator review and ops surface

This order keeps the build grounded in runtime plumbing before policy, autonomy, and operator UX.

There is a small dependency loop between live execution and capability expansion, but the recommended way to break it is:

1. land the execution core and worker against today's safe capability methods
2. add the missing reply, read-state, and dialog-context methods under the capability layer
3. wire those richer actions back into the execution worker rather than the operator turn path

## MVP Acceptance

The live engagement MVP is complete when:

- the runtime can ingest inbound MTProto events from managed user accounts
- campaign-linked external conversation records persist across restarts
- the runtime can execute bounded joins, posts, replies, and read-state actions through one audited path
- DM replies only happen after the external user initiates contact
- moderation friction, rate limits, silence, replies, and failures are recorded as operational signals
- the operator can inspect, pause, and escalate live engagement work without editing files manually
