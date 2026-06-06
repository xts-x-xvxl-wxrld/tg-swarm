# Unified Campaign Loop Rebuild

## Goal

Turn the current planning-first runtime plus the newer live-engagement seams into one campaign-centered operating loop that can be implemented in narrow, testable slices.

## Why This Is Now A Series

The earlier rebuild note was doing too many jobs at once:

- setup and intake redesign
- attachment and asset ingestion
- observation and adaptation redesign
- orchestrator routing changes

Those topics are related, but they are not the same slice. Splitting them makes it easier to:

- implement one runtime seam at a time
- keep specs and tests scoped to the same behavior boundary
- avoid mixing operator UX work with worker-side live-state work
- decide sequencing explicitly instead of hiding it inside one broad note

## What This Rebuild Covers

This plan series defines how to converge:

- operator-led campaign setup inside the Telegram session
- campaign-native asset intake and analysis
- deterministic live signal capture
- bounded observation review for campaign steering
- orchestrator routing that can react to both planning work and live campaign pressure

## Relationship To Existing Plans

- [Workflow Refinement Plan](../workflow-refinement.md) remains the plan for tightening the current discovery -> strategy -> account-planning flow and its validation boundaries.
- [Observation And Adaptation](../live-engagement-mvp/observation-and-adaptation.md) remains the lean live-engagement MVP note for durable write-protecting state.
- This rebuild series sits above those narrower plans and describes the next integration layer where planning, live signals, and campaign steering start to work as one loop.

## Document Map

1. [Campaign Setup SOP](./campaign-setup-sop.md)
   The operator-session setup flow, `campaign_setup_state`, explicit readiness confirmation, and seed-group persistence.
2. [Campaign Asset Intake](./campaign-asset-intake.md)
   Attachment normalization, raw asset storage, analysis summaries, and sendable eligibility metadata.
3. [Planning Work Families Transition](./planning-work-families-transition.md)
   How discovery, strategy, and account planning stop behaving like the architecture and become campaign work families under one orchestrated loop.
4. [Campaign Signals And Observation Review](./campaign-signals-and-observation-review.md)
   Deterministic signal capture, `CampaignSignal`, `ObservationReviewAgent`, and bounded review triggers.
5. [Orchestrator Routing And Compatibility](./orchestrator-routing-and-compatibility.md)
   How `observation` fits into work-item routing without breaking existing Telegram UX compatibility.
6. [Implementation Sequence](./implementation-sequence.md)
   The recommended delivery order and acceptance gates for landing this series slice by slice.

## Delivery Principles

- Keep deterministic runtime code responsible for capture, persistence, and gating.
- Keep LLM reasoning bounded, review-oriented, and invoked only when the runtime has something worth reviewing.
- Keep `workflow_stage` as a compatibility summary for Telegram UX, not the real control-plane source of truth.
- Prefer new narrow seams over widening unrelated modules.
- Ship each slice with focused tests before moving to the next one.

## Out Of Scope For This Series

- outbound media sending
- a broad analytics or BI layer
- a full operator dashboard outside Telegram
- generic multi-channel campaign support
- autonomous strategy rewriting on every live event

## Success Criteria

This rebuild series is complete when:

- campaign setup can stay inside one Telegram session until the operator explicitly says to begin
- campaign documents and images become durable campaign assets with usable summaries
- meaningful live outcomes become compact reusable signals instead of ad hoc notes
- observation review can steer campaign work without running inside the write path
- orchestrator routing can prioritize live campaign pressure without regressing the current planning flow
