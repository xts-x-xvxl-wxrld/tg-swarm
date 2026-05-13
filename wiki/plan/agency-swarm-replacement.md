# Agency Swarm Replacement Plan

## Goal

Replace the Agency Swarm orchestration framework with a purpose-built orchestrator and implement the Telegram capability layer with real MTProto account access.

This plan picks up where Phase 1 left off. Phase 1 established the runtime shape: session contracts, approval contracts, capability interfaces, and a thin app service wired to the existing Agency Swarm backend. This plan replaces that backend and fills in the capability implementations.

## Why We Are Replacing Agency Swarm

Agency Swarm is built on the OpenAI Assistants API. Its value-adds - persistent threads, file search, code interpreter - are OpenAI-specific infrastructure. This repo runs Claude via a LiteLLM compatibility shim, which means none of those benefits apply. We are carrying framework overhead while getting nothing back.

The second problem is control flow shape. Agency Swarm's all-to-all handoff model is not the right primitive for a session-aware, approval-gated workflow. The session layer, approval state machine, and workflow artifacts already being built in `telegram_app/` are being constructed around Agency Swarm, not inside it. The `orchestrator_adapter.py` already treats Agency Swarm as a dumb LLM call. The logical conclusion is to replace it with one.

The new orchestrator needs to own:

- session context loading per turn
- workflow stage awareness (intake, discovery, approval-pending, execution)
- specialist routing (Discovery, Strategy, Account Manager)
- approval gate interpretation

None of this maps cleanly onto Agency Swarm's model.

## What We Keep From The Existing Infrastructure

A meaningful portion of the existing codebase is reusable after stripping the framework wrapper.

### Keep Verbatim

| Asset | Location | Notes |
|-------|----------|-------|
| Orchestrator instructions | `orchestrator/instructions.md` | Role clarity, routing logic, delegation patterns |
| Deep research instructions | `deep_research/instructions.md` | Multi-query research discipline, source ranking, structured output format |
| Virtual assistant instructions | `virtual_assistant/instructions.md` | Priority ladder, confirmation flows, markdown rules |
| Shared runtime instructions | `shared_instructions.md` | Operator UX model, session continuity expectations |
| `model_availability.py` | `shared_tools/` | Pure env-var check, no framework dependency |
| `GetCurrentTime.py` | `virtual_assistant/tools/` | Pure pytz logic |
| `ScholarSearch.py` | `virtual_assistant/tools/` | Clean API integration pattern |

### Extract And Adapt (Remove BaseTool, Keep Logic)

| Asset | What To Keep |
|-------|-------------|
| `helpers.py` | Composio client caching pattern, `execute_composio_tool()` shape - adapt for new tool provider |
| `CopyFile.py` | Filesystem logic, path normalization for Windows/Docker |
| Email tools (8 files) | `strip_html()`, param validation, Composio call patterns |
| Calendar tools (4 files) | Timezone handling, event param validation |
| Slack tools (4 files) | Message formatting, user lookup |
| File tools (4 files) | Encoding handling, error patterns |
| `ExecuteTool.py` | Nested field access logic, JSON response handling |

All `BaseTool` subclasses become plain Python functions or methods. The business logic is sound and not worth rewriting.

### Throw Away

| Asset | Reason |
|-------|--------|
| `orchestrator/orchestrator.py` | Agency Swarm Agent factory |
| `deep_research/deep_research.py` | Agency Swarm Agent factory |
| `swarm.py` | Agency factory, Handoff/SendMessage flows |
| `server.py` (Agency Swarm wiring) | Replace with clean entrypoint |
| All `BaseTool` inheritance | Framework glue |
| `openai_client_utils.py` | Extracts credentials from Agency Swarm context |
| `patches/` | Agency Swarm-specific patches |

## What We Build

### 1. Purpose-Built Orchestrator

A session-aware LLM agent that owns the turn-by-turn control flow. It replaces `orchestrator_adapter.py` plus Agency Swarm with a direct Claude API call loop.

Responsibilities:

- load session context, workflow snapshot, and pending approvals before each LLM call
- determine turn intent: new request, continuation, clarification, or approval response
- route to the right specialist (Discovery, Strategy, Account Manager) or handle directly
- update workflow snapshot after each turn
- format responses back to Telegram

The orchestrator is not a general-purpose agent. It should have a narrow system prompt derived from the existing `orchestrator/instructions.md` with additions for session and approval awareness.

### 2. Three Specialist Agents

Each specialist is a direct LLM call with its own system prompt and tool access. They are called by the orchestrator, not by each other.

**Discovery Agent**

- finds and scores relevant Telegram communities against campaign objectives
- uses research methodology from `deep_research/instructions.md` as the base
- outputs a structured `community_shortlist` artifact
- tool access: web search, community capability layer

**Strategy Agent**

- produces community-aware messaging playbooks
- inputs: `campaign_brief`, `community_shortlist`
- outputs: `strategy_playbook` artifact with positioning, talking points, CTA style
- tool access: read-only capability layer for community profiles

**Account Manager Agent**

- plans account assignments against community targets
- applies pacing rules, warm-up constraints, health risk scoring
- outputs: `account_assignment_plan` artifact
- tool access: account capability layer (read for now, write with approval)

### 3. Telegram Capability Layer Implementations

The capability interfaces already exist in `telegram_app/capabilities/`. This rollout fills them in.

**MTProto Client (Telethon or Pyrogram)**

The Bot API cannot act as a real Telegram account. Community joining, reading message history, posting as a user, and enumerating members all require MTProto. We add Telethon or Pyrogram as the execution backend behind the capability layer.

The capability layer remains the stable interface. The MTProto client is an implementation detail beneath it.

Initial implementations needed in the overall MTProto rollout:

- `CommunityCapability.search()` - find communities by keyword, topic, language
- `CommunityCapability.get_profile()` - read community metadata, moderation signals, posting norms
- `AccountCapability.list_accounts()` - enumerate managed accounts and their health state
- `AccountCapability.get_account()` - account details, warm-up status, risk score
- `MembershipCapability.join()` - join a community as an account (approval-gated)
- `MessagingCapability.read_messages()` - read recent messages for community profiling
- `MessagingCapability.send_message()` - post as an account (approval-gated, deferred to Phase 5)

Account session management - phone auth, 2FA handling, per-account session file storage - lives in the capability layer, not in agents.

## Phases

### Phase 2: Replace Agency Swarm Core

**Outcome:** Agency Swarm is removed from the active code path. The bot still works end-to-end, now through the purpose-built orchestrator.

Steps:

1. Extract prompt files from agent folders into `prompts/` as standalone markdown files.
2. Refactor tool business logic out of `BaseTool` subclasses into plain functions. Start with shared tools and the most-used VA tools.
3. Build `telegram_app/orchestrator/` - a new module containing the orchestrator LLM loop, session context builder, and specialist router.
4. Replace `orchestrator_adapter.py` - wire `app_service.py` to call the new orchestrator instead of Agency Swarm.
5. Remove `agency_swarm` from `requirements.txt` and delete the Agency Swarm glue files.
6. Verify end-to-end turn path works: Telegram update -> app service -> new orchestrator -> response delivered.

**Out of scope for this phase:** specialist agents, capability implementations, MTProto.

### Phase 3: Build Specialist Agents

**Outcome:** Orchestrator routes to Discovery, Strategy, and Account Manager. The marketing workflow runs end-to-end with stubbed capability calls.

Steps:

1. Scaffold `agents/discovery/`, `agents/strategy/`, `agents/account_manager/` with system prompts and tool interfaces.
2. Implement Discovery Agent using deep research methodology. Wire to web search. Stub community capability calls.
3. Implement Strategy Agent. Wire inputs (`campaign_brief`, `community_shortlist`) and outputs (`strategy_playbook` artifact).
4. Implement Account Manager Agent. Wire inputs and outputs. Add pacing rule logic.
5. Wire orchestrator routing so the right specialist is called at each workflow stage.
6. Wire approval-aware orchestrator resumption - when operator replies to an approval pause, orchestrator correctly interprets and continues.

**Out of scope for this phase:** real MTProto capability implementations.

### Phase 4: Implement Telegram Capability Layer Foundation

**Outcome:** The capability layer has real MTProto-backed foundations in place: account onboarding exists, read-side capabilities have implementations, and the runtime can switch between stub and Telethon-backed backends without changing orchestrator flow.

#### Library choice

Use **Telethon**. It is more mature than Pyrogram, has better coverage of edge cases (2FA, flood waits, session management), and has extensive community documentation for the kinds of operations this layer needs.

#### Async bridge strategy

Telethon is fully async. The existing capability interfaces, agents, and orchestrator are all synchronous. Rather than refactoring the entire call stack to async (which is a large, independent effort), the MTProto layer uses a **thread-backed sync wrapper**: a `TelethonClientWrapper` that owns a dedicated background thread with its own event loop. All public methods on the wrapper are synchronous and dispatch to that thread via `concurrent.futures`. This requires zero changes to agents or orchestrator.

#### New folder structure

```text
telegram_app/capabilities/
  mtproto/
    __init__.py
    client.py            <- TelethonClientWrapper: thread + event loop pool, sync public API
    session_manager.py   <- session file path resolution, per-account Telethon client lifecycle
    impl_accounts.py     <- AccountCapabilityImpl
    impl_communities.py  <- CommunityCapabilityImpl
    impl_membership.py   <- MembershipCapabilityImpl
    impl_messaging.py    <- MessagingCapabilityImpl

telegram_app/
  auth/
    models.py           <- onboarding auth state records
    auth_store.py       <- file-backed pending auth store
    auth_manager.py     <- operator-facing auth wizard and state transitions

data/
  accounts.json         <- account registry: id, phone, tier, health, join_count_24h, last_active
  sessions/             <- per-account Telethon .session files (gitignored, restricted permissions)
```

#### Steps

1. **Async bridge** - Add Telethon to `requirements.txt`. Build `TelethonClientWrapper` in `mtproto/client.py`. It manages one `TelegramClient` per account in a thread-backed event loop. Public API: `connect(account_id)`, `disconnect(account_id)`, `run(account_id, coro)`.

2. **Account registry** - `data/accounts.json` stores account metadata: `account_id`, `phone`, `tier` (senior/standard/new), `health` (active/flagged/banned), `join_count_24h`, `last_active`. `AccountCapabilityImpl` reads and updates this file.

3. **Interactive phone auth flow** - Adding a new account is a stateful multi-step process that runs outside the campaign workflow. Triggered by a bot command such as `/addaccount`. App service checks for a pending auth state before routing to the orchestrator. Steps: request phone -> send code request -> operator replies with code -> if 2FA enabled, operator replies with password -> session file saved and account added to registry. Must include a `/cancelauth` escape hatch.

4. **Community capability** - `CommunityCapabilityImpl.search(query)` uses Telethon's `SearchRequest` or username resolution to find channels and groups. `get_profile(community_id)` fetches the full entity: member count, description, username, slowmode, linked chat, creation date.

5. **Account capability** - `AccountCapabilityImpl.list_accounts()` reads the registry and returns current metadata. `get_account(account_id)` returns per-account details including tier, health, and join activity in the last 24 hours.

6. **Messaging capability (read-only)** - `MessagingCapabilityImpl.read_messages(chat_id, limit)` uses `client.get_messages()`. Used by Discovery Agent to sample recent posts for community tone and activity analysis. No write path in this phase.

7. **Membership capability** - `MembershipCapabilityImpl.join(account_id, community_id)` calls `JoinChannelRequest`. Before executing, it checks the pacing rules against the account's `join_count_24h` (enforced in the capability layer, not in agents). `FloodWaitError` is caught and surfaced as a `CapabilityResult` failure with the wait time in `data`.

8. **Wire Discovery Agent to real capabilities** - `DiscoveryAgent.run()` no longer has to stay training-knowledge-only. With real capabilities injected, the flow becomes: (a) Claude produces an initial shortlist from training knowledge, (b) `CommunityCapability.search()` validates which communities exist and fetches live metadata, (c) `CommunityCapability.get_profile()` enriches each entry with current member count and moderation signals, (d) `MessagingCapability.read_messages()` samples recent posts for tone, (e) shortlist is re-scored with real data before operator review. `DiscoveryAgent.__init__` accepts optional `community_capability` and `messaging_capability` parameters; without them, it falls back to training-knowledge-only mode.

9. **Wire into server.py** - `create_telegram_app_service()` in `server.py` builds the capability chain and injects it into the agents. `TelethonClientWrapper` is instantiated once and shared across all capability implementations.

#### Pacing rules (enforced at capability layer)

- No account joins more than 3 communities in any 24-hour window.
- `MembershipCapability.join()` rejects calls that would breach this limit with a clear error.
- Account health is updated after every join attempt (success or failure).
- `FloodWaitError` from Telegram automatically marks the account as temporarily rate-limited.

#### What remains deferred after Phase 4

- Live smoke testing against real Telegram accounts and communities.
- Discovery's full live validation and re-scoring loop against Telegram data.
- `MessagingCapability.send_message()` write path.
- Automated joining at scale.

#### Risks

**Ban risk** - Real Telegram accounts are at risk if pacing is not respected. Any write operation (join, send) must handle `FloodWaitError` and back off. Community reads are lower risk but still need rate-limiting. Test with throwaway accounts before using real ones.

**Session file security** - Telethon `.session` files are equivalent to authenticated Telegram credentials. `data/sessions/` must be in `.gitignore`. Directory permissions should be `700`. Consider encryption at rest for production deployments.

**Phone auth UX** - The multi-step auth flow is stateful. A user sending a campaign message mid-auth must not corrupt the auth state. The auth state machine must be isolated from the workflow state machine in the app service.

#### Open questions

- **Async bridge**: Thread-backed sync wrapper (Option A, recommended) or async refactor of agents and orchestrator (Option B)?
- **Account auth surface**: `/addaccount` bot command, or a separate CLI script for adding accounts outside the Telegram interface?
- **Data directory**: `data/` inside the repo (gitignored) or external at `~/.tgswarm/`?
- **How many accounts**: Affects session pool sizing and the registry design.

### Phase 5: Operationalize Live MTProto Workflows

**Outcome:** The MTProto capability layer is not just implemented in code, but proven live against Telegram and extended to support approval-gated outbound messaging.

#### Code Changes

1. **Onboarding hardening** - Improve the auth wizard to handle expired codes, invalid codes, invalid 2FA passwords, retry messaging, and restart-mid-auth recovery more gracefully.

2. **Account operations surface** - Add a minimal operator-facing account inventory surface so onboarded accounts can be inspected operationally, for example a read-only command that lists accounts, health state, and recent rate-limit status.

3. **Discovery live enrichment** - Complete the Discovery Agent's live Telegram loop so shortlist candidates are validated, enriched, sampled for recent tone and activity, and re-scored using `CommunityCapability.search()`, `CommunityCapability.get_profile()`, and `MessagingCapability.read_messages()`.

4. **Membership hardening** - Tighten `MembershipCapability.join()` around pacing, retries, `FloodWaitError`, and account health transitions so live join attempts are observable and safer.

5. **Outbound messaging capability** - Implement `MessagingCapability.send_message()` as an approval-gated write path. It should post as a real Telegram account, classify failures cleanly, surface flood-wait metadata, and update account health and audit state after each send attempt.

6. **Guardrail and audit shaping** - Add the minimum structured audit metadata needed for live joins and live sends so later execution and reporting phases can reason about who acted, where, when, and with what result.

#### Live Testing

1. **Real onboarding smoke test** - Run `/addaccount` end-to-end with a throwaway Telegram account using live `TELEGRAM_API_ID` and `TELEGRAM_API_HASH`, verifying phone-code auth, optional 2FA, persisted session files, and account registry writes.

2. **Read-side capability validation** - Validate live `search`, `get_profile`, and `read_messages` results against a small known set of Telegram communities so the returned metadata shape matches what agents need.

3. **Discovery live-flow validation** - Run a real Discovery workflow and confirm that Telegram-derived metadata actually changes shortlist validation and re-ranking instead of remaining prompt-only.

4. **Join safety validation** - Exercise `MembershipCapability.join()` with a throwaway account and low-risk communities to confirm pacing enforcement, flood-wait handling, and health-state updates work in practice.

5. **Outbound send validation** - After `MessagingCapability.send_message()` ships, validate approval-gated live sends in a tightly controlled test environment, confirming message delivery, refusal and error handling, and audit recording.

6. **Restart and recovery validation** - Restart the runtime during pending auth and after successful onboarding to verify auth-state persistence, session reuse, and account registry consistency.

## Folder Shape After Transition

```text
prompts/
  orchestrator.md
  researcher.md       <- from deep_research/instructions.md
  discovery.md
  strategy.md
  account_manager.md
  shared_runtime.md

agents/
  discovery/
  strategy/
  account_manager/

tools/
  composio.py         <- helpers.py pattern, BaseTool removed
  search.py           <- ScholarSearch, WebSearch
  files.py            <- CopyFile + file ops
  email.py            <- VA email tools, plain functions
  calendar.py
  slack.py

telegram_app/
  orchestrator/       <- purpose-built orchestrator LLM loop
  auth/               <- operator-facing account onboarding and auth state
  transport/          <- existing, keep
  sessions/           <- existing, keep
  approvals/          <- existing, keep
  capabilities/       <- existing interfaces + MTProto implementations
  models/             <- existing, keep
```

Files that go away:

- `swarm.py`
- `orchestrator/orchestrator.py`
- `deep_research/deep_research.py`
- `orchestrator_adapter.py` (replaced by new orchestrator wiring)
- `patches/`
- All `BaseTool` subclasses

## Risks

### Risk 1: MTProto Account Safety

Acting as real Telegram accounts carries ban risk if pacing and behavior constraints are not respected. The capability layer must enforce pacing limits before any join or message write operation reaches the MTProto client, even in testing.

### Risk 2: Session Context Size

Loading full session history plus workflow snapshot into every orchestrator turn can grow large fast. The orchestrator's context builder needs a summarization or trimming strategy before this becomes a problem in longer campaigns.

### Risk 3: Tool Extraction Regressions

Refactoring `BaseTool` subclasses into plain functions could introduce subtle bugs if field validation or error handling is missed. Existing tests should cover the business logic before the framework wrapper is removed.

## Acceptance Criteria

- Agency Swarm is not in the import path of any active code.
- Telegram bot works end-to-end through the purpose-built orchestrator.
- All three specialist agents are callable and produce structured artifacts.
- At least community search and profile capabilities have real MTProto implementations.
- Capability layer is the only code that touches MTProto directly - agents never import it.
- Phase 5 closes only when live onboarding, live read capabilities, and approval-gated outbound messaging have all been validated against Telegram with throwaway accounts.
