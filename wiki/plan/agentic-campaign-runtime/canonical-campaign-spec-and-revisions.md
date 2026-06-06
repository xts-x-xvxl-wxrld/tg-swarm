# Canonical Campaign Spec And Revisions

## Goal

Simplify the campaign runtime by making one canonical campaign spec the source of truth, treating planning outputs as derived views, and reducing the number of state transitions required to keep campaigns current.

## Core Direction

The runtime should move away from treating discovery, strategy, and account planning as separate long-lived planning tracks that each own their own refresh choreography.

Instead, the runtime should use one canonical campaign spec plus one revision model:

- `campaign_spec`: the durable source of truth for goal, audience, offer, assets, seed communities, conversion target, constraints, autonomy posture, and other operator-level campaign instructions
- `active_revision`: the currently live revision that execution, monitoring, and downstream reasoning are pinned to
- `proposed_revision`: a full candidate package created from operator edits or major agent suggestions before promotion

Under this model:

- discovery shortlist, strategy playbook, and account assignment plan become derived views generated from the current revision
- live execution always knows exactly which approved or promoted revision it is using
- runtime refresh no longer depends on reopening multiple planning work items in sequence

## Why This Is Simpler

This direction reduces breakage points by removing much of the current chained refresh logic:

- fewer intermediate work states need to stay in sync
- fewer stale-downstream checks are required
- the operator reviews one campaign package revision rather than a long chain of planning artifacts
- execution can switch revisions in one controlled handoff instead of many partial invalidation paths
- monitoring becomes easier because every live event can be tied back to one pinned active revision

## Source Of Truth

The canonical campaign spec should be the only object that is treated as operator-authored intent.

It should own:

- objective and offer context
- target audience and market constraints
- campaign assets and asset refs
- seed communities and targeting hints
- conversion target and routing expectations
- autonomy posture and operator preferences
- campaign-level safety and guardrail settings

Everything else should be renderable from that source plus runtime observations.

## Derived Views

Discovery, strategy, and account planning should remain important, but they should be derived outputs rather than independent roots of truth.

That means:

- discovery renders the current best target-community view from the active revision
- strategy renders the current recommended messaging and campaign tactics from the active revision
- account planning renders the current operational allocation and schedule view from the active revision

If the active revision changes, the runtime regenerates these derived views together instead of reopening each layer as a separate control path.

## Revision Lifecycle

The simplified lifecycle should be:

1. operator starts or extends a campaign through normal chat turns
2. runtime synthesizes or updates the campaign spec
3. runtime produces a proposed revision package
4. operator approves the initial runnable revision
5. runtime promotes it to `active_revision`
6. derived views are regenerated from that revision
7. execution runs only against that pinned active revision

Later changes should follow the same revision model rather than reopening many planning stages independently.

## Approval Policy

The initial runnable campaign revision should still require operator approval before live execution begins.

After a campaign is live, the runtime should distinguish between two classes of change:

### Operator-Level Revision Changes

Changes that redefine campaign intent should still become a `proposed_revision` and wait for operator approval before promotion.

Examples:

- changing the core goal
- changing the target audience substantially
- replacing the offer or major campaign assets
- replacing the seed targeting direction entirely

### Autonomous Operational Revisions

Changes that tune live campaign operations should be autonomous by default and should not block on operator approval.

These autonomous revisions should be promoted automatically, then surfaced back to the operator as a notification plus a compact diff summary.

Examples:

- changing messaging angle
- changing account assignments
- changing schedules
- changing conversion routing
- changing guardrails

The operator should be informed clearly that these changes were applied, why they were applied, which active revision they produced, and how to override or roll them back if needed.

## Runtime Triggers For Revision Updates

The runtime should create or promote revisions from three main triggers:

- operator chat feedback
- scheduled campaign refresh
- live observation pressure from execution or conversation signals

The important simplification is that those triggers should produce revision updates, not independent planning refresh chains.

## Execution Handoff

When the active revision changes:

- derived views are regenerated from the new revision
- unstarted prepared execution tied to the old revision is retired or replaced in one controlled step
- active monitoring and reporting should attribute new work to the new revision id
- the operator receives one notification that explains the revision switch and any execution impact

This keeps execution pinning explicit without requiring the operator to reason about several planning work items at once.

## Monitoring Implications

This model should make campaign monitoring simpler because every metric can be attached to:

- campaign id
- active revision id
- derived view version

That should support clearer reporting such as:

- which revision is live
- what changed in the latest autonomous update
- which conversations and conversions happened under which revision
- whether performance improved or degraded after a revision switch

## Implementation Notes

The practical target is to converge toward a smaller control plane:

- one canonical campaign spec store
- one revision store with active versus proposed state
- one derived-view rendering path
- one execution pinning path
- one operator notification path for autonomous operational changes

The current work-item and stage machinery can be used as a migration bridge, but the destination should be revision-centric rather than choreography-centric.
