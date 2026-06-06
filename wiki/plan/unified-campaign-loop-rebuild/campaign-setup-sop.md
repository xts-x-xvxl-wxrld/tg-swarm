# Campaign Setup SOP

## Goal

Move campaign intake from an early one-shot text capture into a guided orchestrator-led setup flow that stays inside the normal Telegram operator session.

## Why This Needs Its Own Slice

Setup changes operator-facing behavior, session state, and downstream discovery assumptions. It should land before live observation steering because it defines the campaign frame the later loop depends on.

## Scope

- add a guided `campaign_setup_state` under `session.workflow_state`
- let the orchestrator ask only the next missing or most useful question
- persist seed target groups as first-class setup inputs
- wait for explicit operator confirmation before discovery or follow-on work begins
- keep the current `campaign_brief` artifact as a compatibility view, not the only source of continuity

## Recommended Runtime Shape

The setup state should track only what the orchestrator needs to continue the SOP cleanly:

- goal
- audience
- offer or product context
- constraints
- success intent when volunteered
- seed target groups
- asset refs
- readiness status
- last missing-question hint

The orchestrator should:

- keep setup conversational instead of dumping a form
- accept partial answers in any order
- recommend readiness when enough context exists
- never auto-start discovery without an explicit operator confirmation

## Seed Group Rules

Seed groups are not a hint to discard later. They are first-class inputs that discovery must validate, annotate, and merge with newly found communities.

Discovery should be allowed to:

- confirm a seed group as valid
- reject it with a clear reason
- keep it as a low-confidence candidate
- add better candidates around it

Discovery should not silently ignore operator-provided seed groups.

## State And Artifact Direction

- `campaign_setup_state` becomes the continuity source for in-progress setup
- `campaign_brief` remains a compact compatibility artifact for current prompts and summaries
- campaign memory files can later mirror the setup outcome, but should not replace the live setup state during the conversation

## Acceptance Criteria

- a new or existing session can stay in setup until the operator explicitly says to begin
- the orchestrator asks one next-step question at a time instead of a full questionnaire
- partial setup answers survive later turns
- seed groups persist in setup state and appear in downstream discovery context
- the current planning flow still works for text-only operator sessions

## Validation

- focused app-service or orchestrator tests for guided setup progression
- tests for `/new` plus inline goal text and follow-up turns
- tests proving discovery receives persisted seed groups from setup state
- a Telegram smoke test where the operator provides setup details across multiple turns before starting discovery

