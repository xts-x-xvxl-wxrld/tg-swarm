# tg-swarm - Repository Guide

This file gives coding agents the minimum context needed to work safely in this repository.

## What This Repo Is

`tg-swarm` is a Telegram-native autonomous agent platform forked from OpenSwarm.

The active product is no longer the stock OpenSwarm or Agency Swarm experience:

- the runtime entrypoint is `server.py`
- Telegram is the primary interface
- orchestration happens through a purpose-built runtime in `telegram_app/orchestrator/`
- the first operating mode is a discovery -> strategy -> account planning workflow

Some legacy OpenSwarm and Agency Swarm files still exist in the tree, but they are no longer the source of truth for the active runtime.

## Read First

When making changes, read these first:

1. `wiki/index.md`
2. `wiki/code-index/index.md`
3. `server.py`
4. `telegram_app/orchestrator/orchestrator.py`
5. `telegram_app/app_service.py`
6. `prompts/`

Use `rg` to verify symbols and file locations before opening large modules.

## Current Structure

```text
server.py                         <- FastAPI + Telegram polling entrypoint
shared_instructions.md            <- shared high-level context used across the repo
config.py                         <- model configuration helpers

telegram_app/
  app_service.py                  <- thin runtime coordinator
  orchestrator/
    orchestrator.py               <- purpose-built orchestrator
    context_builder.py            <- runtime context assembly
  transport/                      <- Telegram Bot API models and client
  sessions/                       <- session persistence and workflow state
  approvals/                      <- approval persistence and state machine
  capabilities/                   <- Telegram/domain capability interfaces
  models/                         <- runtime data contracts

agents/
  discovery/                      <- discovery specialist
  strategy/                       <- strategy specialist
  account_manager/                <- account planning specialist

prompts/
  orchestrator.md
  shared_runtime.md
  discovery.md
  strategy.md
  account_manager.md
  researcher.md

shared_tools/                     <- reusable tool code and legacy shared integrations
tools/                            <- framework-agnostic helper tools
wiki/                             <- specs, plans, code index, and change log
tests/                            <- focused runtime and integration tests
```

## Runtime Shape

The active request path is:

1. Telegram update enters `server.py`
2. `TelegramAppService` loads session and approval state
3. `PurposeBuiltOrchestrator` interprets the turn
4. the orchestrator either responds directly or routes to a specialist agent
5. the runtime persists updated workflow state and returns Telegram messages

The important implication is that agent changes usually involve both prompt logic and runtime state handling, not just prompt text.

## How To Customize Safely

To change the active swarm:

1. Update prompts in `prompts/`
2. Update specialist logic in `agents/`
3. Update orchestration or routing rules in `telegram_app/orchestrator/`
4. Update workflow state transitions in `telegram_app/sessions/`, `telegram_app/approvals/`, or `telegram_app/app_service.py` when behavior changes
5. Update the relevant wiki spec or plan if the architecture or workflow meaning changes

Avoid treating `swarm.py`, `agency.py`, or legacy Agency Swarm topology as the live source of truth. Those paths are no longer the active architecture.

## Key Conventions

- Configure models through `DEFAULT_MODEL` in `.env`; do not hardcode model IDs in new code unless there is a strong reason.
- Keep the Telegram runtime thin. Business logic should live in the orchestrator, specialist agents, or helper modules.
- Persist workflow state through the session and approval managers rather than ad hoc files.
- Prefer framework-agnostic helpers in `tools/` when extracting reusable logic.
- If you change code navigation, architecture docs, or workflow boundaries, update `wiki/code-index/`, `wiki/index.md`, and `wiki/log.md` accordingly.

## Validation

Use the smallest relevant validation step for the change:

- `python -m pytest tests/`
- `python server.py`
- `python server.py --poll`

If you touch only docs or git metadata, a focused verification pass is enough.

## Legacy Notes

These areas may still contain OpenSwarm or Agency Swarm references:

- old documentation
- packaging metadata
- legacy shared tools
- inactive agent folders not used by the Telegram runtime

When cleaning those up, prefer small, explicit updates over broad renames.
