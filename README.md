# tg-swarm

`tg-swarm` is a Telegram-native autonomous agent platform forked from OpenSwarm and reshaped around a purpose-built runtime.

The active product is no longer the stock OpenSwarm terminal swarm. The live path today is:

- Telegram webhook or long-polling input
- session-aware runtime in `telegram_app/`
- purpose-built orchestrator in `telegram_app/orchestrator/`
- specialist agents for discovery, strategy, and account planning

## Current Status

This repo is mid-transition away from its OpenSwarm and Agency Swarm roots.

What is active now:

- `server.py` as the main entrypoint
- Telegram Bot API transport
- local JSON-backed session and approval state
- a staged workflow for discovery -> strategy -> account planning
- prompt files in `prompts/` that drive the current orchestrator and specialists

What is still transitional:

- some legacy docs and packaging metadata
- inactive OpenSwarm-oriented folders and helpers
- dependencies retained for older agent/tool modules that are not on the active runtime path

## Quick Start

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Configure `.env` with at least:

```env
TELEGRAM_BOT_TOKEN=...
ANTHROPIC_API_KEY=...
DEFAULT_MODEL=anthropic/claude-sonnet-4-6
```

4. Run one of the active modes:

```bash
python server.py
```

```bash
python server.py --poll
```

`python server.py` starts the FastAPI runtime on port `8080` by default.

`python server.py --poll` runs a local long-polling Telegram bot, which is the simplest way to test the real message loop without deploying a webhook.

## Repo Map

```text
server.py                         <- FastAPI + Telegram polling entrypoint
telegram_app/                     <- runtime, transport, sessions, approvals, orchestrator
agents/                           <- active specialist agents
prompts/                          <- orchestrator and specialist prompts
tools/                            <- framework-agnostic helper tools
shared_tools/                     <- shared and partly legacy integrations
wiki/                             <- specs, plans, code index, change log
tests/                            <- focused runtime tests
```

## Development Notes

- Start with `wiki/index.md` and `wiki/code-index/index.md` before changing architecture.
- Treat `server.py` and `telegram_app/` as the active runtime source of truth.
- Do not assume old `swarm.py`-style topology is still valid; that path has been removed from the live runtime.
- Keep workflow state changes aligned with the session and approval managers.

## Validation

Run the smallest relevant check for your change:

```bash
python -m pytest tests/
```

```bash
python server.py --poll
```

## License

MIT - see [LICENSE](LICENSE).
