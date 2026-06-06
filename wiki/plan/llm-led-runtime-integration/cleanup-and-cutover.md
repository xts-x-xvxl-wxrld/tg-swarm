# Cleanup And Cutover

## Goal

Retire the temporary migration scaffolding once the compiled-intent path is proven, so the runtime does not end up permanently carrying duplicate control planes.

## Why This Needs Its Own Slice

This series intentionally relies on shadow mode, dual-write behavior, and compatibility fallbacks during migration.

That is the right delivery tactic, but it creates a predictable risk:

- markers remain forever because they still work
- phrase parsers remain forever because they still catch edge cases
- fixed ladder helpers remain forever because they still support old sessions
- validators remain fragmented by legacy surface instead of converging around intent kinds

If cleanup is not planned explicitly, the repo will preserve the old control plane and the new one at the same time.

That would weaken the design goal of both source specs.

## What Should Be Cleaned Up

### Marker-First Control Contracts

Candidate surfaces:

- `SCHEDULE_ACTION_JSON`
- `DISCOVERY_SHORTLIST_JSON`
- `ENGAGEMENT_BRAIN_REVIEW_JSON`
- any similar prompt-owned control marker that survives only as a migration artifact

Cleanup direction:

- keep durable artifacts when they still serve a product purpose
- retire bespoke marker parsing when the same meaning can flow through typed proposals
- avoid one-off parser logic per prompt surface

### Phrase-Gated Control Interpretation

Candidate surfaces:

- explicit approval and rejection phrase gates in the orchestrator
- live-ops phrase triggers
- campaign-context and campaign-intent extraction logic that still acts as de facto control-plane authority

Cleanup direction:

- preserve bounded extraction where it still enriches context
- remove or narrow any phrase logic that still decides runtime mutation on its own after the compiler path is stable

### Fixed Planning Ladder Assumptions

Candidate surfaces:

- `FOLLOW_ON_WORK_TYPE`
- direct next-family chaining on review acceptance
- stage-to-routing assumptions that still do more than compatibility projection

Cleanup direction:

- keep readable workflow summaries for operator UX
- remove hardcoded "next step" authority once deterministic proposal evaluation owns follow-on planning

### Duplicate Validation Paths

Candidate surfaces:

- marker-specific validation helpers
- bespoke post-parse schema checks that no longer align with the new proposal model

Cleanup direction:

- converge around validation by intent kind
- keep artifact validation only where final artifacts still matter independently of control proposals

## Exit Conditions For Cleanup

Cleanup should begin only after:

- the intent envelope is durable and inspectable
- at least the first operator-control intents are applied through the new path
- proposal-driven work follow-on handling is stable enough to replace the old ladder in normal operation
- specialist proposal adapters have proven that the runtime can inspect and apply typed meaning without depending on bespoke markers

## Recommended Cleanup Order

1. Remove or demote shadow-only comparison helpers that are no longer needed.
2. Collapse marker-specific parsing paths into proposal adapters or remove them entirely.
3. Remove fixed follow-on helpers that still act as routing authority.
4. Narrow remaining phrase parsers to advisory extraction or true fallback behavior only.
5. Update prompts so they no longer describe obsolete marker-first control rules.
6. Refresh wiki specs, plans, code index notes, and tests to describe the post-cutover architecture only.

## Acceptance Criteria

This slice is complete when:

- the repo has one primary control-plane interpretation path
- legacy migration scaffolding is either deleted or clearly fenced as temporary fallback
- prompts no longer instruct the model to emit obsolete control markers
- validation logic is centered on typed proposals and retained artifact schemas, not on old parser seams
- the code index and plan docs describe the cleaned architecture rather than the migration midpoint
