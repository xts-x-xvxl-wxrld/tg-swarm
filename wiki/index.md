# Wiki Index

This wiki captures the working design for turning OpenSwarm into a Telegram-native autonomous agent platform.

## Specs

- [Telegram Core Platform](spec/telegram-core-platform.md)
- [Account Capability](spec/account-capability.md)
- [Managed Account Operations](spec/managed-account-operations.md)
- [Campaign Operations Model](spec/campaign-operations-model.md)
- [Telegram Marketing Operating Mode MVP](spec/telegram-marketing-swarm-mvp.md)
- [App Runtime Architecture](spec/app-runtime-architecture.md)
- [Telegram Capability Layer](spec/telegram-capability-layer.md)
- [Session Lifecycle](spec/session-lifecycle.md)
- [Approval And Guardrails](spec/approval-and-guardrails.md)

## Plans

- [Telegram Platform + Marketing MVP Plan](plan/telegram-marketing-swarm-mvp.md)
- [Telegram Runtime Refactor Plan](plan/telegram-runtime-refactor.md)
- [Agency Swarm Replacement Plan](plan/agency-swarm-replacement.md)
- [Workflow Refinement Plan](plan/workflow-refinement.md)
- [Target Search Refinement Plan](plan/target-search-refinement.md)
- [Campaign Operations Runtime Refactor Plan](plan/campaign-operations-runtime-refactor.md)
- [Campaign Memory Implementation Plan](plan/campaign-memory-implementation.md)
- [Campaign Memory Redesign Plan](plan/campaign-memory-redesign.md)

## Code Index

- [Code Index](code-index/index.md)

## Logs

- [Change Log](log.md)

## Notes

- The core product is now a Telegram-native agent platform, not a marketing-only swarm.
- The operator UI is intentionally minimal for now: `/new` plus freeform messages to the orchestrator.
- The Telegram runtime layer should stay thin: session state is structured, conversational planning checkpoints are handled by the orchestrator, and hard approval state should be reserved for consequential write actions.
- Agents are intended to have broad Telegram capability access and be guided primarily by system prompts and shared rules.
- Phase 4 now covers the MTProto capability foundation in code, while the remaining Phase 5 work is mostly live Telegram validation and operational proving against throwaway accounts.
- Operator account onboarding now has a separate auth state machine under `telegram_app/auth/` so MTProto login steps do not interfere with campaign sessions.
- Guardrails are identified in the design but are not yet planned as enforced controls in code.
- The first operating mode remains discovery, campaign strategy, and account management.
- The architecture docs now separate runtime control flow, Telegram capabilities, session lifecycle, and approval design so implementation decisions can stay narrower than product vision docs.
- The runtime refactor plan now translates those architecture docs into a concrete Phase 1 repo-shaping sequence.
- The first campaign-runtime cutover slice now starts at `telegram_app/campaigns/`, where sessions gain durable campaign attachment and a file-backed workspace root.
- The compatibility runtime now also has first-class `telegram_app/work_items/` and `telegram_app/scheduling/` seams, so stages can be treated as operator-facing views while work items and recurring schedules become durable campaign records underneath.
- Campaign memory now also has a first-class runtime seam under `telegram_app/campaign_memory/`, where workspace bootstrap, compatibility artifact views, and campaign-native background context are managed.
