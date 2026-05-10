# Wiki Index

This wiki captures the working design for turning OpenSwarm into a Telegram-native autonomous agent platform.

## Specs

- [Telegram Core Platform](spec/telegram-core-platform.md)
- [Telegram Marketing Operating Mode MVP](spec/telegram-marketing-swarm-mvp.md)
- [App Runtime Architecture](spec/app-runtime-architecture.md)
- [Telegram Capability Layer](spec/telegram-capability-layer.md)
- [Session Lifecycle](spec/session-lifecycle.md)
- [Approval And Guardrails](spec/approval-and-guardrails.md)

## Plans

- [Telegram Platform + Marketing MVP Plan](plan/telegram-marketing-swarm-mvp.md)
- [Telegram Runtime Refactor Plan](plan/telegram-runtime-refactor.md)

## Code Index

- [Code Index](code-index/index.md)

## Logs

- [Change Log](log.md)

## Notes

- The core product is now a Telegram-native agent platform, not a marketing-only swarm.
- The operator UI is intentionally minimal for now: `/new` plus freeform messages to the orchestrator.
- The Telegram runtime layer should stay thin: session and approval state are structured, but the orchestrator interprets follow-up turns and clarifying replies.
- Agents are intended to have broad Telegram capability access and be guided primarily by system prompts and shared rules.
- Guardrails are identified in the design but are not yet planned as enforced controls in code.
- The first operating mode remains discovery, campaign strategy, and account management.
- The architecture docs now separate runtime control flow, Telegram capabilities, session lifecycle, and approval design so implementation decisions can stay narrower than product vision docs.
- The runtime refactor plan now translates those architecture docs into a concrete Phase 1 repo-shaping sequence.
