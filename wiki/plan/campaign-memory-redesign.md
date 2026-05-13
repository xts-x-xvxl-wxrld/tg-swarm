# Campaign Memory Redesign Plan

## Goal

Replace the current rigid planning-artifact persistence model with a hybrid campaign memory system that keeps runtime control flow simple while giving the agent flexible, durable space to think, adapt, and accumulate marketing knowledge over time.

## Why This Plan Exists

The current runtime persists campaign work primarily as a small set of fixed workflow artifacts:

- `campaign_brief`
- `community_shortlist`
- `strategy_playbook`
- `account_assignment_plan`

That shape works for a narrow linear workflow, but live operator sessions are already showing a more valuable pattern:

- the operator goal evolves during the session
- planning often branches instead of moving linearly
- positioning and persona can change after initial planning
- the most important knowledge is often not a finalized field but an observation, hypothesis, or decision rationale
- future execution will need memory of what was learned, what changed, and why

For an agentic Telegram marketing product, the planning layer should behave less like a rigid form and more like a living campaign dossier.

## Core Design Direction

Do not move deeper into a fully normalized campaign database first.

Do not make raw message history the main source of truth.

Instead, adopt a hybrid model:

1. Keep a very small structured runtime state layer for orchestration continuity.
2. Add a flexible file-backed campaign memory workspace for strategic and exploratory knowledge.
3. Keep operational logs separate from campaign memory.

This preserves runtime safety without over-restricting how the agent stores campaign understanding.

## Current Limitations

The current persistence model has four important weaknesses:

1. It assumes campaigns move through a fixed artifact pipeline even when the operator conversation changes direction.
2. It stores finalized outputs better than evolving reasoning, corrections, or intermediate discoveries.
3. It makes downstream reuse depend too heavily on a handful of predefined JSON fields.
4. It does not yet offer a natural durable home for research notes, community observations, positioning shifts, or execution learnings.

## Target Outcomes

This redesign is successful when:

1. The runtime can still resume sessions safely after restart.
2. The agent can maintain rich campaign memory without needing a new schema for every new campaign style.
3. Campaign knowledge is readable and editable by humans outside the app.
4. Operator intent changes, persona shifts, and planning pivots are preserved explicitly instead of disappearing into message history.
5. The system can distinguish durable facts, tentative hypotheses, decisions, plans, and execution results.
6. Future execution agents can build on prior campaign memory instead of re-deriving context from chat alone.

## Proposed Storage Model

### Layer 1: Runtime State

Keep a small structured JSON layer for app continuity and orchestration.

This layer should answer questions like:

- which operator session is active
- which campaign workspace the session is attached to
- which campaign-level work items, schedules, and approvals are active
- whether a consequential approval is pending
- which memory files are canonical for the current turn

This layer should stay intentionally small and stable.

### Layer 2: Campaign Memory Workspace

Add a file-backed campaign workspace for the substantive planning and memory.

Recommended location:

```text
data/campaigns/<campaign-id>/
```

This workspace should be the durable home for:

- strategy thinking
- research notes
- audience and persona definitions
- community-specific memory
- experiment plans
- execution notes
- operator decisions
- open questions

### Layer 3: Operational Logs

Keep low-level runtime and delivery logs separate from strategic memory.

These logs are useful for debugging and audit, but they should not become the primary place where campaign understanding lives.

## Recommended Campaign Workspace Shape

The exact file set should remain flexible, but a strong default shape is:

```text
data/campaigns/
  <campaign-id>/
    campaign.json
    overview.md
    operator-intent.md
    strategy.md
    research-log.md
    personas.md
    experiments.md
    next-actions.md
    execution-log.md
    communities/
      <community-slug>.md
    assets/
    snapshots/
```

### `campaign.json`

Use this for lightweight machine-readable metadata only.

Suggested fields:

- `campaign_id`
- `created_at`
- `updated_at`
- `status`
- `operator_id`
- `primary_goal`
- `tags`
- `canonical_files`

This should remain intentionally compact and should not become a giant replacement database.

It should not store one `active_session_id` or a campaign-level `current_stage`.

Sessions, work items, schedules, approvals, and later execution records should point to the campaign rather than the campaign pretending to own one live session or one linear stage.

### Markdown Memory Files

Use Markdown files for the real campaign memory.

Examples:

- `overview.md`: campaign summary, current posture, canonical framing
- `operator-intent.md`: what the operator wants, how it has changed, explicit constraints
- `research-log.md`: notable findings, observed patterns, unresolved questions
- `strategy.md`: positioning, sequencing, hypotheses, current direction
- `personas.md`: operator-approved personas and tone rules
- `experiments.md`: planned or completed marketing experiments
- `next-actions.md`: current recommended actions and blockers
- `execution-log.md`: future live joins, observations, outreach, posts, and responses
- `communities/<community-slug>.md`: community-specific memory and history

## Memory Primitive Direction

The system should stop assuming every important campaign object is a fixed artifact type.

Instead, memory should support a small set of conceptual primitives that can live inside Markdown documents or lightweight sidecar metadata:

- fact
- observation
- hypothesis
- decision
- plan
- asset
- experiment
- result
- open question

This gives the agent room to capture both certainty and ambiguity without needing a new table for every workflow idea.

## Suggested Markdown Convention

Markdown memory files may optionally use YAML frontmatter for lightweight indexing.

Example:

```md
---
kind: community_memory
community_handle: "@CTOFounder"
status: active_candidate
confidence: high
last_updated: 2026-05-12T15:20:00+03:00
tags: [ai-founders, europe, research]
---

# aiCTO Founders

## Why it matters

...

## Observations

...

## Messaging hypotheses

...

## Risks

...

## Next action

...
```

This keeps the content human-readable while still giving the runtime a lightweight way to discover and rank memory.

## Runtime Responsibilities After Redesign

After this redesign, the runtime should not try to structure every planning detail into JSON.

Instead, the runtime should:

1. create or resolve the active campaign workspace
2. attach the current session to that workspace when the work came from an operator turn
3. update minimal structured state needed for orchestration
4. read canonical memory files before major specialist turns
5. let specialists append or update campaign memory documents
6. promote important decisions into canonical memory files when the conversation changes direction

Scheduled and background work should resolve campaign state directly and should not require an active session.

## Canonical Versus Ephemeral Memory

Not every note should be treated equally.

The redesign should distinguish:

- canonical memory: stable campaign direction the runtime should trust by default
- working memory: temporary notes, scratch reasoning, or transient turn-level context
- operational history: execution traces, runtime logs, and delivery events

This distinction is important so the agent remains flexible without becoming noisy or forgetful.

## Migration Direction

The current artifact model should not be deleted immediately.

Instead, migrate in phases.

### Phase 1: Introduce Campaign Workspace Alongside Current Artifacts

- add campaign workspace creation and discovery helpers
- keep current `workflow_artifacts` intact
- write a first `overview.md` and `operator-intent.md` from the current session state
- store campaign pointers in session state

### Phase 2: Make Markdown Memory First-Class For Planning

- route discovery, strategy, and account-planning follow-ups through campaign memory files
- keep structured artifacts only for the minimum fields the runtime truly needs
- move richer reasoning and rationale into Markdown

### Phase 3: Reframe Existing Artifact Types As Views, Not Truth

- treat `campaign_brief`, `community_shortlist`, `strategy_playbook`, and `account_assignment_plan` as generated snapshots or compatibility views
- stop assuming those four artifacts fully define the campaign

### Phase 4: Add Execution Memory

- once live join/send/observe capabilities exist, append execution outcomes to `execution-log.md`
- preserve observations, moderation responses, audience reactions, and follow-up decisions in campaign memory

## File-Level Work Proposal

### New Runtime Areas

- `telegram_app/campaigns/`
- `telegram_app/campaign_memory/`

These modules would handle:

- campaign workspace creation
- campaign metadata persistence
- canonical memory file resolution
- Markdown read/write helpers
- promotion of important session turns into durable memory

### Current Areas Likely To Change

- `telegram_app/app_service.py`
- `telegram_app/intake.py`
- `telegram_app/orchestrator/context_builder.py`
- `telegram_app/orchestrator/orchestrator.py`
- `telegram_app/sessions/session_manager.py`
- `telegram_app/models/session.py`

## Proposed Session-State Adjustments

Session state should become lighter and more campaign-aware.

Suggested additions:

- `campaign_id`
- `campaign_workspace_path`
- `canonical_memory_files`

Suggested reductions over time:

- stop treating `workflow_artifacts` as the only durable representation of campaign knowledge
- avoid storing large strategy reasoning blobs directly inside session JSON
- avoid making session-local workflow stages the primary source of campaign operational truth

## Non-Goals

This redesign should not:

- introduce a large normalized relational schema for campaign planning
- force every campaign into the same lifecycle
- require every memory update to fit a strict artifact schema
- replace all structured state with freeform notes
- turn runtime debug logs into strategic memory

## Risks And Mitigations

### Risk: Markdown Memory Becomes Chaotic

Mitigation:

- define a small default workspace layout
- define canonical files
- use optional frontmatter for indexing
- distinguish canonical from working memory

### Risk: The Runtime Loses Reliable State

Mitigation:

- keep minimal structured runtime JSON
- treat campaign metadata and workflow stage as required fields
- preserve lightweight compatibility views during migration

### Risk: Specialists Write Inconsistent Memory

Mitigation:

- add prompt instructions for memory update discipline
- define a small set of memory primitives
- prefer append-and-summarize patterns instead of unconstrained overwrites

## Validation

The redesign should be considered ready when:

1. A new session can create and attach to a campaign workspace automatically.
2. The runtime can restart and still resolve the active campaign and canonical memory files.
3. Discovery, strategy, and account-planning turns can read and update campaign memory without relying only on the current artifact JSON blobs.
4. A human can understand the current campaign state by reading the Markdown workspace without replaying raw chat history.
5. Existing workflows continue to function during migration, even if some downstream consumers still expect legacy artifacts.

## Recommended Delivery Order

1. Define the campaign workspace metadata contract.
2. Add campaign workspace creation and session linkage.
3. Add canonical Markdown memory files and helpers.
4. Teach intake/orchestrator to read from and write to campaign memory.
5. Keep legacy artifacts as compatibility views while the prompts and specialists transition.
6. Add execution-memory support only after live Telegram action capabilities are ready.

## Plain-Language Summary

The app should stop pretending that a campaign is fully captured by a few rigid JSON artifacts.

Instead, it should keep a small amount of structured runtime state and let the agent build a living campaign memory workspace around that state.

That workspace should be readable by humans, flexible enough for different operator goals, and structured just enough that the runtime can still resume, reason, and act safely.
