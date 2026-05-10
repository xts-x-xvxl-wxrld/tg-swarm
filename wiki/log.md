# Change Log

## 2026-05-11

- Renamed the npm launcher path from `bin/openswarm` to `bin/tg-swarm`, updated package metadata and lockfile to publish `tg-swarm`, and refreshed the macOS smoke-test workflow plus issue template labels to match the new package identity.
- Updated `run_utils.py` and `onboard.py` branding to `tg-swarm` while keeping fallback support for legacy `OPENSWARM_*` environment variables during the transition.

## 2026-05-10 (session 2)

- Normalized git remotes so `origin` points at `xts-x-xvxl-wxrld/tg-swarm` and `upstream` points at `VRSEN/OpenSwarm`, then reset `main` to track `origin/main`.
- Rewrote `AGENTS.md`, `README.md`, and selected metadata files so the repo describes the current Telegram-native runtime instead of the old OpenSwarm / Agency Swarm topology.
- Updated the code index to stop pointing at deleted `swarm.py`-style entrypoints and to reflect the purpose-built orchestrator path.
- Audited existing Agency Swarm infrastructure for reusability. Prompts (orchestrator, deep_research, virtual_assistant instructions) are high-value and framework-agnostic. Tool business logic is extractable with BaseTool wrapper removed. Framework glue (agent factories, swarm.py, patches) gets discarded entirely.
- Decided on total replacement of Agency Swarm rather than retrofit. Key reason: framework runs via LiteLLM compatibility shim on Claude - no Assistants API benefits apply, only overhead.
- Added `wiki/plan/agency-swarm-replacement.md` covering Phase 2 (replace Agency Swarm core), Phase 3 (build three specialist agents), and Phase 4 (implement Telegram capability layer with MTProto).

## 2026-05-10

- Added repository-level pytest configuration in `pyproject.toml` so tests resolve the repo root consistently and `pytest-asyncio` uses an explicit fixture loop scope.
- Prepared the Telegram runtime refactor work for a clean Git commit and push.

## 2026-05-09

- Created initial wiki structure for the Telegram marketing swarm effort.
- Added an MVP spec focused on discovery, strategy, and account management.
- Added an implementation plan for reshaping OpenSwarm into a narrower Telegram-focused harness.
- Reframed the product as a Telegram-native autonomous agent platform rather than a marketing-only swarm.
- Added a Telegram core platform spec covering the minimal bot UI, orchestrator, shared Telegram capability layer, and role-based autonomy.
- Updated the marketing spec so it now describes the first operating mode on top of the broader Telegram platform.
- Updated the implementation plan to build Telegram core concepts before workflow specialization.
- Added scaffolded design specs for app runtime architecture, Telegram capability boundaries, session lifecycle, and approval/guardrail design.
- Added an initial `wiki/code-index/index.md` so future implementation work has a human-readable code navigation entrypoint.
- Updated the wiki index to expose the new architecture-oriented design documents.
- Added a Phase 1 runtime refactor plan that maps the Telegram-native architecture onto concrete repo modules, boundaries, and sequencing.
- Scaffolded the `telegram_app/` runtime package with transport models, session and approval contracts, in-memory stores, capability interfaces, and runtime record models.
- Updated the code index so the new Telegram runtime package is part of the documented code navigation map.
- Added a thin `telegram_app/app_service.py` adapter and updated the runtime docs so the app layer stays focused on transport/session plumbing while the orchestrator interprets clarifications and approval replies.
- Wired a first end-to-end Telegram turn path: `server.py` now exposes a Telegram webhook, `telegram_app/orchestrator_adapter.py` routes turns into the agency orchestrator, session history is preserved in-memory, and the default swarm is narrowed to orchestrator plus deep research.
- Added a Telegram Bot API transport client, wired outbound `sendMessage` delivery into the webhook flow, added `/start` handling, and exposed webhook management endpoints for setup and inspection.
- Added a local long-polling runner and `python server.py --poll` mode so the real Telegram bot can be tested live without deploying a public webhook endpoint.
- Replaced the Telegram runtime's in-memory session and approval stores with local JSON-backed persistence, added structured workflow snapshot/artifact helpers to the session layer, wired the persistent stores into `server.py`, and added focused runtime persistence tests.
- Added a structured intake coordinator that turns operator turns into a persisted `campaign_brief` artifact, updates `workflow_snapshot` stages from intake to discovery, and passes the structured brief/snapshot context into the orchestrator at runtime.
- Added discovery-stage runtime helpers that request a machine-readable community shortlist from the research path, persist that shortlist as a `community_shortlist` artifact, create a pending approval, and move the snapshot to `waiting_for_approval`.
