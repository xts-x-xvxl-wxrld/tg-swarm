# Code Index

## Purpose

This index is the human-readable map for the codebase as it evolves from general OpenSwarm into a Telegram-native agent platform.

Use this index to find where runtime responsibilities live before opening large files.

## Current State

The repository is still primarily organized as the stock OpenSwarm application with specialized agents and a shared orchestrator pattern.

Important implication:

- current product intent is more specific than the current code layout
- some code areas still reflect the general-purpose OpenSwarm product rather than the Telegram-native target design

## Read First

- [AGENTS.md](C:/Users/ravil/OneDrive/Desktop/tg-swarm/AGENTS.md)
- [swarm.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/swarm.py)
- [server.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/server.py)
- [shared_instructions.md](C:/Users/ravil/OneDrive/Desktop/tg-swarm/shared_instructions.md)
- [wiki/spec/telegram-core-platform.md](C:/Users/ravil/OneDrive/Desktop/tg-swarm/wiki/spec/telegram-core-platform.md)
- [wiki/spec/app-runtime-architecture.md](C:/Users/ravil/OneDrive/Desktop/tg-swarm/wiki/spec/app-runtime-architecture.md)

## Top-Level Areas

### Agency Composition

Primary files:

- [swarm.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/swarm.py)

What lives here:

- agency creation
- agent instantiation
- communication flow topology
- shared runtime patch application
- current default runtime path narrowed to orchestrator plus deep research

### Telegram App Runtime

Primary folders:

- [telegram_app](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app)
- [telegram_app/app_service.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/app_service.py)
- [telegram_app/discovery.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/discovery.py)
- [telegram_app/intake.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/intake.py)
- [telegram_app/transport](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/transport)
- [telegram_app/sessions](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/sessions)
- [telegram_app/approvals](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/approvals)
- [telegram_app/capabilities](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/capabilities)
- [telegram_app/models](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/models)
- [telegram_app/json_store.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/json_store.py)

What lives here:

- thin runtime adaptation between transport and orchestrator
- Telegram transport models
- Telegram Bot API client for outbound replies and webhook management
- local long-polling runner for live testing without deployment
- session and approval contracts
- JSON-backed runtime state persistence for sessions and approvals
- structured intake parsing that builds a reusable campaign brief artifact
- discovery workflow helpers that turn discovery-stage outputs into a persisted community shortlist plus approval pause
- workflow snapshots and structured workflow artifacts stored inside session state
- Telegram domain capability interfaces
- structured runtime records

### API Entrypoint

Primary files:

- [server.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/server.py)

What lives here:

- FastAPI integration bootstrap
- published agency registration
- Telegram webhook entrypoint
- Telegram webhook management endpoints
- CLI switch for local long-polling mode
- mounted legacy agency API under `/agency`

### Shared Runtime Configuration

Primary files:

- [shared_instructions.md](C:/Users/ravil/OneDrive/Desktop/tg-swarm/shared_instructions.md)
- [config.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/config.py)
- [helpers.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/helpers.py)
- [run_utils.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/run_utils.py)

What lives here:

- shared behavior
- model/provider configuration
- runtime helpers

### Orchestrator

Primary files:

- [orchestrator/orchestrator.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/orchestrator/orchestrator.py)
- [orchestrator/instructions.md](C:/Users/ravil/OneDrive/Desktop/tg-swarm/orchestrator/instructions.md)

What lives here:

- primary coordination agent definition
- orchestration behavior prompt

### Specialist Agents

Representative folders:

- [virtual_assistant](C:/Users/ravil/OneDrive/Desktop/tg-swarm/virtual_assistant)
- [deep_research](C:/Users/ravil/OneDrive/Desktop/tg-swarm/deep_research)
- [data_analyst_agent](C:/Users/ravil/OneDrive/Desktop/tg-swarm/data_analyst_agent)
- [docs_agent](C:/Users/ravil/OneDrive/Desktop/tg-swarm/docs_agent)
- [slides_agent](C:/Users/ravil/OneDrive/Desktop/tg-swarm/slides_agent)
- [image_generation_agent](C:/Users/ravil/OneDrive/Desktop/tg-swarm/image_generation_agent)
- [video_generation_agent](C:/Users/ravil/OneDrive/Desktop/tg-swarm/video_generation_agent)

What lives here:

- agent definitions
- role prompts
- tool bundles per agent

### Shared Tools And Patches

Primary folders:

- [shared_tools](C:/Users/ravil/OneDrive/Desktop/tg-swarm/shared_tools)
- [patches](C:/Users/ravil/OneDrive/Desktop/tg-swarm/patches)

What lives here:

- reusable tools available across agents
- runtime monkey patches and compatibility workarounds

## Target Next Areas

These responsibilities now exist as scaffolding and are the next places to deepen:

- Telegram transport integration
- orchestrator wiring through the thin app service
- session persistence beyond in-memory stores
- concrete Telegram capability implementations
- approval-aware orchestration wiring
- structured workflow persistence integration

Current implementation note:

- one thin end-to-end Telegram turn path now exists through `server.py`, `telegram_app/app_service.py`, the intake and discovery coordinators, the agency orchestrator adapter, and a Telegram Bot API client for outbound replies; it can now run either by webhook or by local long polling, with local JSON persistence for sessions, approvals, workflow snapshots, structured workflow artifacts, a reusable campaign brief, and a persisted community shortlist

## How To Use This Index

1. Read the relevant spec first.
2. Use this file to identify likely code entrypoints.
3. Verify symbols and files with `rg` before opening large modules.
4. Add narrower subsystem shards when the codebase grows into clearer Telegram-specific boundaries.

## Planned Shards

Likely future shard topics:

- `telegram.md`
- `sessions.md`
- `persistence.md`
- `agents.md`
- `tools.md`

These should be added only when the code structure justifies them.
