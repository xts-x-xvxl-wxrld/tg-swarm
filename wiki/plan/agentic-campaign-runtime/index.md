# Agentic Campaign Runtime Plan

## Goal

Turn the new [Agentic Campaign Runtime](../../spec/agentic-campaign-runtime.md) spec into a set of narrow implementation seams that can be expanded and landed incrementally.

## Why This Is A Separate Series

The current repo already has meaningful planning, activation, asset intake, and live-execution foundations.

What it does not yet have is one cohesive implementation series for:

- mixed-input campaign interpretation
- orchestrator-led asset-role inference
- first-class conversion targets
- campaign-specific qualification
- continuous autonomous operation with operator escalation

This folder exists to make that work the current highest-priority build track.

## Relationship To Existing Plans

- [Unified Campaign Loop Rebuild](../unified-campaign-loop-rebuild/index.md) remains the bridge from planning flow into campaign-centered runtime seams.
- [Engagement Machine Readiness](../engagement-machine-readiness/index.md) remains the readiness audit for the already-landed live runtime foundations.
- This new series sits above both and defines the next product-facing convergence target.

## Document Map

1. [Current State Audit](./current-state-audit.md)
   What the repo already supports, what is partially there, and what is still missing for the agentic runtime target.
2. [Canonical Campaign Spec And Revisions](./canonical-campaign-spec-and-revisions.md)
   The simplification direction: one source-of-truth campaign spec, one pinned active revision, and autonomous operational revisions with operator notification instead of chained refresh choreography.
3. [Campaign Intake And Synthesis](./campaign-intake-and-synthesis.md)
   How mixed operator input becomes a durable campaign intent package.
4. [Asset Role Inference](./asset-role-inference.md)
   How uploaded files and media become multi-use campaign assets without manual operator labeling by default.
5. [Conversion Target Contract](./conversion-target-contract.md)
   How campaigns declare where successful leads should end up and how that target becomes runtime-visible.
6. [Qualification And Handoff Runtime](./qualification-and-handoff-runtime.md)
   How campaign-specific qualification and conversion progression should work.
7. [Continuous Autonomous Operations](./continuous-autonomous-operations.md)
   How the runtime continues operating, improves over time, and escalates when blocked.
8. [Operator Notifications And Recovery](./operator-notifications-and-recovery.md)
   How the operator is notified when something breaks, stalls, or needs intervention.
9. [Implementation Sequence](./implementation-sequence.md)
   Recommended delivery order and acceptance gates.

## Delivery Principles

- Keep one canonical campaign spec as the operator-level source of truth.
- Prefer revision promotion plus regeneration over chained downstream refresh choreography.
- Allow autonomous operational changes to promote a new live revision and notify the operator instead of blocking on approval.
- Keep agentic reasoning broad at the interpretation layer and structured at the persistence layer.
- Prefer narrow new seams over overloading the current intake and orchestration modules indefinitely.
- Treat conversion as first-class from the start.
- Preserve the operator's natural mixed-input workflow instead of forcing more manual labeling and formatting.
- Land each slice with focused tests and a runtime-facing explanation.

## Success Criteria

This series is complete when:

- an operator can start a campaign with mixed text, files, and links
- the runtime owns one canonical campaign spec and one pinned active revision
- the runtime can infer campaign assets and roles without manual sendable labeling as the default path
- seed communities and conversion targets can be extracted from natural input
- discovery, strategy, and account planning are derived views regenerated from the same revision source
- qualification and handoff become part of the real runtime rather than a future note
- the campaign can keep running with bounded autonomy and clear operator escalation
- autonomous operational changes notify the operator clearly instead of forcing approval checkpoints for every live tuning update
