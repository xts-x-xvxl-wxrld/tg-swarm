# Wiki Index

This wiki captures the working design for turning OpenSwarm into a Telegram-native autonomous agent platform.

## Specs

- [Agentic Campaign Runtime](spec/agentic-campaign-runtime.md)
- [LLM-Led Outreach Runtime](spec/llm-led-outreach-runtime.md)
- [Freeform-To-Structured Compilation](spec/freeform-to-structured-compilation.md)
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

- [Agentic Campaign Runtime Plan](plan/agentic-campaign-runtime/index.md)
- [LLM-Led Runtime Integration Plan](plan/llm-led-runtime-integration/index.md)
- [LLM-Led Outreach Runtime Plan](plan/llm-led-outreach-runtime/index.md)
- [Telegram Platform + Marketing MVP Plan](plan/telegram-marketing-swarm-mvp.md)
- [Live Engagement MVP Plan](plan/live-engagement-mvp/index.md)
- [Unified Campaign Loop Rebuild](plan/unified-campaign-loop-rebuild/index.md)
- [Engagement Machine Readiness](plan/engagement-machine-readiness/index.md)
- [Telegram Runtime Refactor Plan](plan/telegram-runtime-refactor.md)
- [Agency Swarm Replacement Plan](plan/agency-swarm-replacement.md)
- [Workflow Refinement Plan](plan/workflow-refinement.md)
- [Target Search Refinement Plan](plan/target-search-refinement.md)
- [Campaign Operations Runtime Refactor Plan](plan/campaign-operations-runtime-refactor.md)
- [Campaign Memory Implementation Plan](plan/campaign-memory-implementation.md)
- [Campaign Memory Redesign Plan](plan/campaign-memory-redesign.md)
- [Telegram Live Sandbox Day Plan](plan/telegram-live-sandbox-day-plan.md)
- [Testing Group Mock Campaign Scenario](plan/testing-group-mock-campaign.md)

## Code Index

- [Code Index](code-index/index.md)

## Logs

- [Change Log](log.md)

## Notes

- The highest-priority product direction is now the agentic campaign runtime: mixed-input campaign interpretation, inferred asset roles, first-class conversion targets, campaign-specific qualification, and continuous operation with operator escalation.
- The core product is now a Telegram-native agent platform, not a marketing-only swarm.
- The operator UI is intentionally minimal for now: `/new` plus freeform messages to the orchestrator.
- The Telegram runtime layer should stay thin: session state is structured, conversational planning checkpoints are handled by the orchestrator, and hard approval state should be reserved for consequential write actions.
- Agents are intended to have broad Telegram capability access and be guided primarily by system prompts and shared rules.
- The long-term LLM-led runtime shape is no longer "one orchestrator plus a fixed discovery/strategy/account-planning ladder"; those planning roles are increasingly treated as bounded work families inside a broader proposal-first runtime with separate planning, triage, promoted-thread reasoning, and observation surfaces.
- Phase 4 now covers the MTProto capability foundation in code, while the remaining Phase 5 work is mostly live Telegram validation and operational proving against throwaway accounts.
- Operator account onboarding now has a separate auth state machine under `telegram_app/auth/` so MTProto login steps do not interfere with campaign sessions.
- Guardrails are identified in the design but are not yet planned as enforced controls in code.
- The first operating mode remains discovery, campaign strategy, and account management.
- Runtime model routing now supports a separate summary-model override so bounded summary work can use a cheaper Claude model without downgrading the main planning flow.
- Orchestrator and planning surfaces now also have a shared direct read-side Telegram capability tool path during Anthropic runs, while the runtime still keeps external writes behind deterministic execution seams.
- Campaign-owned continuous operations now have a first-class runtime seam under `telegram_app/continuous_ops/`, where autonomy posture, loop status, blocked reasons, schedule pressure, and review pressure are summarized into one durable campaign state.
- The architecture docs now separate runtime control flow, Telegram capabilities, session lifecycle, and approval design so implementation decisions can stay narrower than product vision docs.
- The runtime refactor plan now translates those architecture docs into a concrete Phase 1 repo-shaping sequence.
- The first campaign-runtime cutover slice now starts at `telegram_app/campaigns/`, where sessions gain durable campaign attachment and a file-backed workspace root.
- The compatibility runtime now also has first-class `telegram_app/work_items/` and `telegram_app/scheduling/` seams, so stages can be treated as operator-facing views while work items and recurring schedules become durable campaign records underneath.
- Campaign setup now also has a dedicated deterministic seam under `telegram_app/campaign_setup.py`, where guided setup state, readiness hints, explicit discovery confirmation, and seed target-group persistence are managed without making `campaign_brief` the only source of continuity.
- Conversion targets now also have a dedicated runtime seam under `telegram_app/conversion_target.py`, where natural-language destination signals become one durable normalized campaign-owned contract for downstream qualification, handoff, reporting, and prompt context.
- Campaign memory now also has a first-class runtime seam under `telegram_app/campaign_memory/`, where workspace bootstrap, compatibility artifact views, and campaign-native background context are managed.
- Campaign asset intake now also has a dedicated runtime seam under `telegram_app/campaign_assets/`, where inbound Telegram documents and images are normalized, stored under the campaign workspace, summarized once, and surfaced back into setup state and prompt context as compact asset refs.
- Campaign qualification and handoff now also have a dedicated runtime seam under `telegram_app/qualification/`, where campaign artifacts are synthesized into a reusable qualification frame, live conversations persist latest qualification plus handoff state, and blocked or delivered handoffs surface back into campaign memory.
- Live engagement now also starts at a dedicated `telegram_app/engagement/` seam, where managed-account inbound events are normalized, deduped, and stored outside the operator-turn path.
- Campaign-linked live conversation state now also has a dedicated `telegram_app/external_conversations/` seam, where persisted inbound events are projected into deterministic thread records and lookup indexes without polluting operator sessions.
- Campaign-linked live actions now also have a dedicated `telegram_app/live_execution/` seam, where outbound joins and sends are queued, claimed, retried, and recorded behind one worker-controlled execution path.
- Operator-facing live campaign control now also has a dedicated `telegram_app/live_ops/` seam, where natural-language Telegram requests become deterministic pause/resume, posture, review-resolution, and control-readiness actions.
- Live engagement reasoning now also has a dedicated `telegram_app/engagement_brain/` seam, where one bounded conversation moment is translated into a small structured next-move proposal without re-owning policy or execution.
- Campaign-owned humanized reply timing now also has a dedicated `telegram_app/engagement_policy/` seam, where quiet hours, reply-latency tiers, negative-signal suppression, and compact reply-outcome metrics are resolved before live replies are queued.
- Live reply drafting is now driven by a structured voice/claims/community contract, while send-time authorization and execution policy remain deterministic and auditable.
- Supported live DM and group replies now flow directly from bounded autonomous authorization into live execution without per-message operator review; live ops should stay focused on pause/resume, status, and inspection while MTProto still requires structured approved-send context.
- Operator-directed outbound sends now have a first-class compiled-intent path distinct from low-risk join/read/leave actions, so direct send requests do not need to masquerade as low-risk execution proposals.
- Ambiguous transient failures on visible MTProto sends now fail closed unless delivery can be verified immediately, so the live queue does not auto-repost the same message and create duplicate public sends.
- Campaign-linked observation pressure now also has a dedicated `telegram_app/campaign_signals/` seam, where major live outcomes are deduped into compact signal records and can refresh `observation` work without pulling LLM review into the live write path.
- Observation review now also has an explicit bounded execution path through `agents/observation/`, where persisted signal batches become one structured steering brief, one compact review cursor update, and conservative planning-work refreshes without silently hijacking normal operator turns.
- Operator notifications and recovery now also have a dedicated `telegram_app/operator_notifications/` seam, where intervention events are derived from campaign loop state plus live risk pressure, persisted with delivery and acknowledgement state, and surfaced back through normal operator turns with compact Telegram alert copy.
- Runtime observability now also has a dedicated `telegram_app/monitoring/` seam, where structured events are mirrored into JSONL plus SQLite, FastAPI exposes authenticated history plus summaries plus threshold-backed alerts plus Prometheus-style metrics, and the same monitoring surface works locally or against deployed server state.
- Reasoning surfaces now also share a dedicated read-side `telegram_app/agent_runtime/` seam, where active work, active schedules, runtime pressure, worker-health facts, and recent compiled-intent outcomes are exposed back into prompt context without widening direct mutation power.
