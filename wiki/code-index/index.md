# Code Index

## Purpose

This index is the human-readable map for the Telegram-native runtime that now drives this repository.

Use this file to find the active entrypoints before opening larger modules.

## Current State

The repository still contains some OpenSwarm-era assets, but the live request path now centers on:

- `server.py`
- `telegram_app/app_service.py`
- `telegram_app/orchestrator/orchestrator.py`
- `agents/`
- `prompts/`

Important implications:

- the active runtime is not driven by `swarm.py` or Agency Swarm communication topology
- some surviving files are transitional and should not be treated as architecture truth
- the Telegram session layer is first-class, while hard approvals should be reserved for future external write actions rather than normal planning turns
- the repo should now be read primarily through `control brain + reasoning surfaces + compiled intents + late deterministic execution`, not through a fixed planning ladder
- the next major product-facing runtime direction is agentic campaign interpretation and conversion-target-aware continuous operation layered on top of the current planning and live-execution foundations
- the live engagement machine should be LLM-led in outreach reasoning and adaptive prioritization, with a cheaper inbound-read tier feeding selective higher-capability commercial reasoning and deterministic seams acting mainly as evidence, policy, and execution scaffolding
- the current discovery/strategy/account-planning specialist roster is increasingly a compatibility and planning-work-family layer, not the intended permanent top-level runtime architecture

## Read First

- [AGENTS.md](C:/Users/ravil/OneDrive/Desktop/tg-swarm/AGENTS.md)
- [server.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/server.py)
- [telegram_app/app_service.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/app_service.py)
- [telegram_app/orchestrator/orchestrator.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/orchestrator/orchestrator.py)
- [prompts/orchestrator.md](C:/Users/ravil/OneDrive/Desktop/tg-swarm/prompts/orchestrator.md)
- [wiki/spec/telegram-core-platform.md](C:/Users/ravil/OneDrive/Desktop/tg-swarm/wiki/spec/telegram-core-platform.md)
- [wiki/spec/app-runtime-architecture.md](C:/Users/ravil/OneDrive/Desktop/tg-swarm/wiki/spec/app-runtime-architecture.md)
- [wiki/spec/agentic-campaign-runtime.md](C:/Users/ravil/OneDrive/Desktop/tg-swarm/wiki/spec/agentic-campaign-runtime.md)
- [wiki/spec/llm-led-outreach-runtime.md](C:/Users/ravil/OneDrive/Desktop/tg-swarm/wiki/spec/llm-led-outreach-runtime.md)

## Top-Level Areas

### Telegram App Runtime

Primary folders:

- [telegram_app](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app)
- [telegram_app/app_service.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/app_service.py)
- [telegram_app/transport](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/transport)
- [telegram_app/sessions](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/sessions)
- [telegram_app/campaign_setup.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/campaign_setup.py)
- [telegram_app/campaign_intent.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/campaign_intent.py)
- [telegram_app/campaign_context.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/campaign_context.py)
- [telegram_app/conversion_target.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/conversion_target.py)
- [telegram_app/campaigns](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/campaigns)
- [telegram_app/agent_runtime](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/agent_runtime)
- [telegram_app/compiled_intents](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/compiled_intents)
- [telegram_app/campaign_assets](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/campaign_assets)
- [telegram_app/monitoring](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/monitoring)
- [telegram_app/campaign_memory](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/campaign_memory)
- [telegram_app/campaign_signals](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/campaign_signals)
- [telegram_app/continuous_ops](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/continuous_ops)
- [telegram_app/live_ops](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/live_ops)
- [telegram_app/operator_notifications](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/operator_notifications)
- [telegram_app/qualification](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/qualification)
- [telegram_app/work_items](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/work_items)
- [telegram_app/scheduling](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/scheduling)
- [telegram_app/engagement](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/engagement)
- [telegram_app/engagement_triage](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/engagement_triage)
- [telegram_app/engagement_brain](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/engagement_brain)
- [telegram_app/engagement_brain/drafting_skills.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/engagement_brain/drafting_skills.py)
- [telegram_app/engagement_policy](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/engagement_policy)
- [telegram_app/autonomous_send](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/autonomous_send)
- [telegram_app/external_conversations](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/external_conversations)
- [telegram_app/prepared_execution](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/prepared_execution)
- [telegram_app/live_execution](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/live_execution)
- [telegram_app/approvals](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/approvals)
- [telegram_app/capabilities](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/capabilities)
- [telegram_app/models](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/models)

What lives here:

- the thin runtime that sits between Telegram transport and orchestration
- session, campaign, campaign-memory, work-item, schedule, approval, and workflow state persistence
- the campaign-intent seam that turns mixed operator text, links, and stored asset refs into one durable `campaign_intent` artifact before compatibility mapping back into legacy brief-shaped state
- the agent-runtime seam that gives reasoning surfaces one bounded read-side broker for active work, active schedules, runtime pressure, worker-health facts, proposal outcomes, and compact capability lookups without widening direct write access
- the compiled-intent seam that turns accepted runtime proposals into durable `compiled-intents.json` records with typed kind, safety class, grounding refs, lifecycle status, and narrow applicators into existing live-ops, schedule, work-item, campaign-context, campaign-memory, and prepared-execution invalidation managers
- the compiled-intent seam also now separates low-risk live actions from explicit operator-approved outbound sends, so joins/read-side actions and direct message sends do not share the same execution contract
- the campaign-context seam that promotes operator preferences, revision intent, voice guidance, execution constraints, persistent decisions, and open ambiguities into one compact durable artifact instead of leaving them stranded in recent chat turns
- the conversion-target seam that turns campaign-intent signals into one durable normalized `conversion_target` artifact for downstream qualification, handoff, reporting, and prompt context
- the qualification seam that derives one campaign-specific qualification frame from persisted campaign artifacts, stores live conversation qualification plus handoff state, and records delivered versus blocked conversion routing outcomes
- the campaign-setup seam that keeps setup conversational, stores `campaign_setup_state`, and gates discovery until explicit operator confirmation
- the campaign-asset seam that normalizes inbound Telegram documents and images, stores raw files under each campaign workspace, maintains `assets/manifest.json`, persists inferred additive asset roles plus conservative uncertainty notes, and exposes compact prompt-safe asset refs back to setup and prompt context
- the monitoring seam that writes structured runtime events into both `monitoring/runtime_events.jsonl` and `monitoring/runtime_events.sqlite3`, derives threshold-aware health plus alert snapshots from that history, and exposes queryable history plus summaries plus alerts plus Prometheus-style metrics through the FastAPI runtime
- the campaign-signal seam that turns major live runtime outcomes into deduped `signals/signals.json` records and refreshes bounded `observation` work pressure without running LLM review inside the write path
- the continuous-ops seam that turns campaign posture, open work, recurring schedules, unresolved signals, and latest observation review into one durable `continuous_ops/state.json` summary for prompt context and campaign memory
- the live-ops seam that lets the operator steer live execution mainly through orchestrator chat, with deterministic pause/resume, review resolution, posture changes, and campaign control-completeness reporting behind one runtime surface
- the operator-notification seam that derives compact intervention events from continuous-ops state plus unresolved live risk signals, persists delivery plus acknowledgement plus resolution state, and exposes a small operator recovery surface through ordinary Telegram turns
- the observation-review seam that persists `signals/reviews.json` plus `signals/cursor.json`, runs bounded observation review only from explicit work or schedules, and maps structured advice back into normal planning work-item refreshes
- the dedicated scheduled-work worker entrypoint and lease-protected recurring dispatch loop
- the account-scoped live-engagement seam for inbound managed-account event capture, dedupe, and outbound reply matching
- the dedicated cheap-triage seam for low-cost inbound reading, compact signal extraction, and promotion decisions before deeper commercial reasoning runs
- the dedicated live-engagement brain seam for bounded conversation-level next-move proposals before policy and execution
- the bounded drafting-skill selector seam inside `telegram_app/engagement_brain/`, where one small LLM-chosen Telegram-native skill packet may be injected into live draft generation for copy-writing surfaces without widening policy or execution authority
- the campaign-owned engagement-policy seam for reply latency tiers, quiet hours, negative-signal suppression, and lightweight reply-outcome metrics before outbound queueing
- the dedicated autonomous-send seam that stamps explicit approved-send context for grounded supported replies and retires stale review-state before live execution
- the campaign-scoped live-engagement seam for deterministic external conversation threads, lookup indexes, and narrow inbound-driven campaign-signal promotion for repeated or blocked thread pressure
- the prepared-execution seam that snapshots an approved account-plan revision into campaign-owned executable items before they enter the live queue
- the dedicated live-execution seam for durable action queueing, idempotent dispatch, conservative retry behavior, and conversation-linked outbound result updates, with ambiguous visible-send failures failing closed unless delivery is verified
- campaign workspace bootstrap, compatibility artifact views, specialist-owned working-memory files, and background-session hydration for scheduled work
- orchestrator-authored recurring schedule actions for create, pause, and resume flows during normal operator turns
- Telegram transport client and update models
- capability interfaces and runtime data contracts

### API Entrypoint

Primary files:

- [server.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/server.py)

What lives here:

- FastAPI bootstrap
- Telegram webhook routes
- Telegram webhook management routes
- local long-polling mode
- dedicated worker switches for scheduler, managed-account inbound listening, queued live execution, and background conversation review
- runtime service composition

### Orchestrator And Specialists

Primary files:

- [telegram_app/orchestrator/orchestrator.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/orchestrator/orchestrator.py)
- [telegram_app/orchestrator/context_builder.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/orchestrator/context_builder.py)
- [telegram_app/llm/capability_tools.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/llm/capability_tools.py)
- [agents/discovery/agent.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/agents/discovery/agent.py)
- [agents/observation/agent.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/agents/observation/agent.py)
- [agents/strategy/agent.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/agents/strategy/agent.py)
- [agents/account_manager/agent.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/agents/account_manager/agent.py)
- [prompts/orchestrator.md](C:/Users/ravil/OneDrive/Desktop/tg-swarm/prompts/orchestrator.md)
- [prompts/discovery.md](C:/Users/ravil/OneDrive/Desktop/tg-swarm/prompts/discovery.md)
- [prompts/observation.md](C:/Users/ravil/OneDrive/Desktop/tg-swarm/prompts/observation.md)
- [prompts/strategy.md](C:/Users/ravil/OneDrive/Desktop/tg-swarm/prompts/strategy.md)
- [prompts/account_manager.md](C:/Users/ravil/OneDrive/Desktop/tg-swarm/prompts/account_manager.md)
- [prompts/sales_skills](C:/Users/ravil/OneDrive/Desktop/tg-swarm/prompts/sales_skills)

What lives here:

- direct LLM orchestration
- shared Anthropic tool-use wiring for read-side Telegram capability calls during orchestrator and planning-surface runs
- runtime context assembly
- shared bounded read-side agent-runtime inspection for planning and observation prompts
- prompt-safe Telegram capability readiness reporting, including stub-versus-live visibility for operator-facing planning runs
- durable context promotion and prompt-safe campaign-context injection for downstream specialists
- work-family routing with explicit reasoning-surface metadata plus stage compatibility views
- bounded planning-surface execution plus explicit observation-review execution from signal work
- planning-surface artifact outputs plus shared advisory proposal persistence, so planning conclusions are inspectable as typed proposals instead of living only inside artifact schemas
- review prompts and planning follow-on routing now read persisted planning advisory proposals first, with legacy fixed-ladder defaults demoted to narrow compatibility fallback
- compact compiled-intent outcome feedback, including blocked and rejected reasons, flowing back into later reasoning runs as prompt-safe context
- prompt contracts for the active discovery -> strategy -> account planning flow
- reusable Telegram-native sales drafting skill assets under `prompts/sales_skills/`, intended for outbound DM drafting, follow-ups, objection replies, and first-post group outbound guidance without importing a separate external skill runtime
- transitional planning-specialist seams that are expected to converge toward a broader `control brain + reasoning surfaces + compiled-intent proposals + late deterministic execution` model

Related map:

- [Discovery Search Map](C:/Users/ravil/OneDrive/Desktop/tg-swarm/wiki/code-index/discovery-search.md)
- [Engagement Brain Map](C:/Users/ravil/OneDrive/Desktop/tg-swarm/wiki/code-index/engagement-brain.md)
- [Engagement Policy Map](C:/Users/ravil/OneDrive/Desktop/tg-swarm/wiki/code-index/engagement-policy.md)
- [Live Execution Map](C:/Users/ravil/OneDrive/Desktop/tg-swarm/wiki/code-index/live-execution.md)
- [Live Ops Map](C:/Users/ravil/OneDrive/Desktop/tg-swarm/wiki/code-index/live-ops.md)

### Shared Runtime Configuration

Primary files:

- [shared_instructions.md](C:/Users/ravil/OneDrive/Desktop/tg-swarm/shared_instructions.md)
- [config.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/config.py)
- [helpers.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/helpers.py)
- [run_utils.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/run_utils.py)
- [telegram_app/llm/model_selection.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/llm/model_selection.py)
- [telegram_app/llm/capability_tools.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/llm/capability_tools.py)

What lives here:

- shared behavior and provider configuration
- centralized role-based Anthropic model selection, including a cheaper summary-model override for bounded observation-style work
- shared tool-loop support that lets orchestrator and planning surfaces call bounded Telegram capability reads directly during Anthropic runs
- transitional bootstrap helpers
- supporting utilities that are not the primary Telegram runtime path

### Shared Tools And Transitional Assets

Primary folders:

- [tools](C:/Users/ravil/OneDrive/Desktop/tg-swarm/tools)

What lives here:

- reusable helper logic
- a small path-translation seam for repo-local `/mnt` access
- a few transitional packaging/runtime helpers that are not on the primary Telegram turn path

## How To Use This Index

1. Read the relevant spec first.
2. Use this file to identify the active runtime entrypoints.
3. Verify symbols and files with `rg` before opening large modules.
4. Update this map when the live runtime path changes.
