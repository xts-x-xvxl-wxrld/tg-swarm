# Campaign Memory Implementation Plan

## Goal

Implement the campaign memory subsystem described by [Campaign Operations Model](C:/Users/ravil/OneDrive/Desktop/tg-swarm/wiki/spec/campaign-operations-model.md).

This plan focuses on how campaign knowledge should be stored, structured, migrated, and accessed in code. It supersedes the earlier exploratory direction captured in [Campaign Memory Redesign Plan](C:/Users/ravil/OneDrive/Desktop/tg-swarm/wiki/plan/campaign-memory-redesign.md) by turning that design direction into an implementation-focused roadmap.

## Why This Plan Exists

The current runtime persists campaign thinking mainly through:

- session message history
- workflow snapshot
- fixed workflow artifacts such as:
  - `campaign_brief`
  - `community_shortlist`
  - `strategy_playbook`
  - `account_assignment_plan`

That gives partial continuity, but it does not yet provide a strong durable home for:

- evolving operator intent
- persona changes
- community-specific memory
- research notes
- decisions and rationale
- tactical agent working state
- long-lived execution learning

The new operating model requires campaign memory to be first-class.

## Scope

This plan covers:

- campaign workspace layout
- campaign metadata shape
- shared memory versus agent-local working memory
- Markdown conventions
- session-to-campaign linkage data
- compatibility with current workflow artifacts
- file-level runtime helpers for reading and writing memory

This plan does not fully define:

- work-item orchestration
- schedule dispatch behavior
- specialist task routing

Those belong to the runtime refactor plan.

## Implementation Direction

Use a hybrid memory model:

1. small structured runtime state for continuity
2. file-backed campaign workspace for durable campaign knowledge
3. separate operational logs for audit and debugging

Do not move toward a database-first schema for all planning knowledge.

Do not rely on raw session chat as the durable source of truth.

## Current Persistence Gaps

The existing model has these concrete gaps:

1. Major campaign pivots are easy to lose in message history.
2. Different kinds of campaign knowledge have no natural durable home beyond generic artifact blobs.
3. Specialist tactical state has nowhere explicit to live.
4. Current artifacts capture outputs better than evolving beliefs, observations, or rationale.
5. Humans cannot easily inspect the campaign as a living dossier without parsing JSON session files.

## Target Memory Model

Campaign memory should be split into:

### 1. Campaign Metadata

Compact machine-readable metadata used by the runtime.

### 2. Shared Campaign Memory

Canonical memory that represents current campaign truth.

### 3. Agent Working Memory

Tactical memory owned by specialists.

### 4. Compatibility Views

Transitional structured artifacts kept for current runtime compatibility.

## Recommended Workspace Layout

Recommended root:

```text
data/campaigns/<campaign-id>/
```

Recommended initial shape:

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
    agents/
      discovery.md
      strategy.md
      account_manager.md
    assets/
    snapshots/
```

This layout should be a strong default, not a rigid ceiling.

## `campaign.json` Contract

`campaign.json` should stay small and runtime-oriented.

Suggested first fields:

- `campaign_id`
- `created_at`
- `updated_at`
- `status`
- `operator_id`
- `primary_goal`
- `tags`
- `canonical_files`
- `agent_memory_files`

Optional later fields:

- `schedule_ids`
- `active_work_item_ids`
- `latest_review_at`
- `memory_version`

This file should not become a giant dumping ground for campaign reasoning.

It also should not store one `active_session_id`, and it should not become a second workflow machine through fields like `workflow_stage` or `operating_mode`.

The campaign should be the durable root record. Sessions, work items, schedules, approvals, and later execution records should reference `campaign_id` downstream.

## Shared Memory Files

### `overview.md`

Purpose:

- concise campaign summary
- current posture
- canonical framing
- most important current priorities

### `operator-intent.md`

Purpose:

- operator goals
- constraints
- changes in direction
- unresolved operator-level tensions

### `strategy.md`

Purpose:

- current positioning
- audience framing
- campaign-level hypotheses
- messaging posture

### `research-log.md`

Purpose:

- durable research findings
- campaign-wide observations
- notable changes in understanding

### `personas.md`

Purpose:

- operator-approved personas
- tone choices
- role-specific framing

### `experiments.md`

Purpose:

- experiment ideas
- current experiment status
- outcomes and lessons

### `next-actions.md`

Purpose:

- campaign-level priorities
- active blockers
- upcoming recommended actions

### `execution-log.md`

Purpose:

- future execution events
- join/post/outreach results when live execution exists
- operator-visible operational history

## Community Memory

Each meaningful target community should eventually have its own memory file under:

```text
communities/<community-slug>.md
```

Community memory should hold:

- why the community matters
- validation status
- norms and moderation posture
- relevant observations
- messaging hypotheses
- risks
- next action

This is likely a stronger long-term home than overloading shortlist artifacts forever.

## Agent Working Memory

Each specialist should have a tactical working memory file under:

```text
agents/
```

Initial suggested files:

- `agents/discovery.md`
- `agents/strategy.md`
- `agents/account_manager.md`

These should hold tactical state such as:

- open leads
- rejected paths
- unresolved questions
- working hypotheses
- local reasoning that is not yet canonical campaign truth

The key rule is:

- specialists can write their own working memory
- only durable, campaign-relevant findings should be promoted into shared campaign memory

## Markdown Convention

Markdown should remain human-readable first.

Optional YAML frontmatter should be allowed for lightweight indexing.

Initial frontmatter fields may include:

- `kind`
- `status`
- `last_updated`
- `tags`
- `owner_role`
- `confidence`

Avoid overloading frontmatter with the entire business object.

## Memory Primitive Direction

The implementation should support these conceptual primitives, even if they are embedded in Markdown sections rather than separate database rows:

- fact
- observation
- hypothesis
- decision
- plan
- asset
- experiment
- result
- open question

This should shape both prompts and memory-writing helpers.

## Session-State Changes

Session state should become campaign-aware but remain lightweight.

Suggested additions:

- `campaign_id`
- `campaign_workspace_path`
- `canonical_memory_files`

Suggested reductions over time:

- avoid storing large planning outputs directly in session JSON
- avoid treating `workflow_artifacts` as the sole durable campaign representation
- avoid treating session-local workflow stages as campaign operational truth

## Compatibility Strategy

Do not remove current artifacts immediately.

During migration:

- keep `campaign_brief`, `community_shortlist`, `strategy_playbook`, and `account_assignment_plan`
- treat them as compatibility views or snapshots
- allow the runtime to generate them from richer campaign memory where useful
- gradually reduce downstream reliance on them as primary truth

## File-Level Work Proposal

### New Runtime Areas

- `telegram_app/campaigns/`
- `telegram_app/campaign_memory/`

Suggested responsibilities:

- campaign workspace creation
- campaign metadata persistence
- shared-memory read/write helpers
- agent-memory read/write helpers
- canonical file resolution
- memory promotion helpers

### Existing Areas Likely To Change

- `telegram_app/app_service.py`
- `telegram_app/intake.py`
- `telegram_app/orchestrator/context_builder.py`
- `telegram_app/orchestrator/orchestrator.py`
- `telegram_app/models/session.py`
- `telegram_app/sessions/session_manager.py`
- specialist agents and prompts that currently assume JSON artifact truth

## Phased Implementation

### Phase 1: Campaign Workspace Creation

Goals:

- create a durable campaign workspace
- write `campaign.json`
- attach sessions to campaign identifiers and workspace paths
- make `campaign_id` the root reference for downstream campaign memory records

### Phase 2: Canonical Shared Memory Bootstrap

Goals:

- generate `overview.md` and `operator-intent.md`
- bootstrap shared memory from current session and artifact state
- keep existing JSON artifacts unchanged during this phase

### Phase 3: Memory Read Path Integration

Goals:

- teach orchestrator context building to read canonical memory files
- allow specialists to receive campaign memory context in addition to workflow snapshot state

### Phase 4: Memory Write Path Integration

Goals:

- let orchestrator and specialists update shared or local memory deliberately
- promote major campaign pivots from conversation into durable documents
- add basic memory-write discipline to prompts and runtime helpers

### Phase 5: Compatibility View Refactor

Goals:

- keep structured artifact outputs where the runtime still needs them
- reduce dependence on those artifacts as the only truth source
- begin generating them as compatibility snapshots from richer campaign memory where appropriate

### Phase 6: Execution Memory

Goals:

- once live execution exists, append results into `execution-log.md`
- preserve joins, moderation reactions, audience responses, and follow-up learning in campaign memory

## Validation

The memory implementation should be considered ready when:

1. A new session can create and attach to a campaign workspace automatically.
2. The runtime can restart and still resolve the campaign workspace and canonical memory files.
3. A human can understand the current campaign by reading the workspace without replaying raw chat.
4. Specialists can maintain tactical memory without corrupting canonical campaign truth.
5. Existing flows continue to work while compatibility artifacts remain in place.

## Focused Test Tracks

- campaign workspace creation
- session-to-campaign persistence
- canonical file discovery and loading
- agent-memory read/write behavior
- compatibility with current artifact consumers
- promotion of operator-intent changes into durable memory

## Risks And Mitigations

### Risk: Too Much Freedom Creates Memory Chaos

Mitigation:

- define canonical files
- define a small default folder layout
- distinguish shared memory from agent memory
- use prompts and helpers that prefer append-and-summarize behavior

### Risk: Runtime Code Starts Depending On Arbitrary Markdown Structure

Mitigation:

- keep `campaign.json` small but authoritative for runtime pointers
- rely on canonical file names and limited frontmatter instead of deep freeform parsing
- avoid making every section heading a hard contract

### Risk: Artifact Migration Breaks Existing Behavior

Mitigation:

- keep compatibility views during migration
- update readers before removing old assumptions
- phase changes in small slices

## Non-Goals

This plan should not:

- turn campaign memory into a large normalized relational schema
- require every campaign to use identical files beyond a minimal canonical set
- replace runtime logs as the source of technical audit
- remove all structured JSON immediately

## Recommended Delivery Order

1. Define `campaign.json` and campaign workspace creation.
2. Add session-to-campaign linkage.
3. Bootstrap canonical shared memory files.
4. Add shared-memory read helpers to orchestrator context building.
5. Add agent-memory and shared-memory write helpers.
6. Reframe existing artifacts as compatibility outputs.
7. Add execution memory only after live execution capabilities exist.

## Plain-Language Summary

This plan gives the campaign a real memory system.

Instead of forcing all planning knowledge into a few rigid JSON artifacts, the runtime will keep small structured state for continuity and use a campaign workspace with shared and agent-local memory files for the real long-lived marketing knowledge.
