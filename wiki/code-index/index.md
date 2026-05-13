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

## Read First

- [AGENTS.md](C:/Users/ravil/OneDrive/Desktop/tg-swarm/AGENTS.md)
- [server.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/server.py)
- [telegram_app/app_service.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/app_service.py)
- [telegram_app/orchestrator/orchestrator.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/orchestrator/orchestrator.py)
- [prompts/orchestrator.md](C:/Users/ravil/OneDrive/Desktop/tg-swarm/prompts/orchestrator.md)
- [wiki/spec/telegram-core-platform.md](C:/Users/ravil/OneDrive/Desktop/tg-swarm/wiki/spec/telegram-core-platform.md)
- [wiki/spec/app-runtime-architecture.md](C:/Users/ravil/OneDrive/Desktop/tg-swarm/wiki/spec/app-runtime-architecture.md)

## Top-Level Areas

### Telegram App Runtime

Primary folders:

- [telegram_app](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app)
- [telegram_app/app_service.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/app_service.py)
- [telegram_app/transport](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/transport)
- [telegram_app/sessions](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/sessions)
- [telegram_app/campaigns](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/campaigns)
- [telegram_app/campaign_memory](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/campaign_memory)
- [telegram_app/work_items](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/work_items)
- [telegram_app/scheduling](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/scheduling)
- [telegram_app/approvals](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/approvals)
- [telegram_app/capabilities](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/capabilities)
- [telegram_app/models](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/models)

What lives here:

- the thin runtime that sits between Telegram transport and orchestration
- session, campaign, campaign-memory, work-item, schedule, approval, and workflow state persistence
- the dedicated scheduled-work worker entrypoint and lease-protected recurring dispatch loop
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
- runtime service composition

### Orchestrator And Specialists

Primary files:

- [telegram_app/orchestrator/orchestrator.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/orchestrator/orchestrator.py)
- [telegram_app/orchestrator/context_builder.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/orchestrator/context_builder.py)
- [agents/discovery/agent.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/agents/discovery/agent.py)
- [agents/strategy/agent.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/agents/strategy/agent.py)
- [agents/account_manager/agent.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/agents/account_manager/agent.py)
- [prompts/orchestrator.md](C:/Users/ravil/OneDrive/Desktop/tg-swarm/prompts/orchestrator.md)
- [prompts/discovery.md](C:/Users/ravil/OneDrive/Desktop/tg-swarm/prompts/discovery.md)
- [prompts/strategy.md](C:/Users/ravil/OneDrive/Desktop/tg-swarm/prompts/strategy.md)
- [prompts/account_manager.md](C:/Users/ravil/OneDrive/Desktop/tg-swarm/prompts/account_manager.md)

What lives here:

- direct LLM orchestration
- runtime context assembly
- specialist work-family execution with stage compatibility views
- prompt contracts for the active discovery -> strategy -> account planning flow

Related map:

- [Discovery Search Map](C:/Users/ravil/OneDrive/Desktop/tg-swarm/wiki/code-index/discovery-search.md)

### Shared Runtime Configuration

Primary files:

- [shared_instructions.md](C:/Users/ravil/OneDrive/Desktop/tg-swarm/shared_instructions.md)
- [config.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/config.py)
- [helpers.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/helpers.py)
- [run_utils.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/run_utils.py)

What lives here:

- shared behavior and provider configuration
- transitional bootstrap helpers
- supporting utilities that are not the primary Telegram runtime path

### Shared Tools And Legacy Assets

Primary folders:

- [shared_tools](C:/Users/ravil/OneDrive/Desktop/tg-swarm/shared_tools)
- [tools](C:/Users/ravil/OneDrive/Desktop/tg-swarm/tools)
- [patches](C:/Users/ravil/OneDrive/Desktop/tg-swarm/patches)

What lives here:

- reusable helper logic
- shared integrations
- inactive or transitional migration leftovers

## How To Use This Index

1. Read the relevant spec first.
2. Use this file to identify the active runtime entrypoints.
3. Verify symbols and files with `rg` before opening large modules.
4. Update this map when the live runtime path changes.
