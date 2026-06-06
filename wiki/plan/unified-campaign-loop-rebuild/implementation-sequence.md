# Implementation Sequence

## Goal

Translate the rebuild series into a delivery order that can land safely in the current runtime.

## Recommended Order

### Slice 1: Campaign Setup SOP

Land [Campaign Setup SOP](./campaign-setup-sop.md) first.

Why first:

- it establishes the campaign frame the rest of the loop should inherit
- it improves the operator experience immediately
- it does not require the live-engagement worker path to change yet

Exit criteria:

- guided setup works across multiple turns
- operator confirmation is required before discovery begins
- seed groups persist into downstream discovery context

### Slice 2: Campaign Asset Intake

Land [Campaign Asset Intake](./campaign-asset-intake.md) second.

Why second:

- assets naturally plug into setup
- attachment support is easier to reason about before observation steering is added
- it produces durable campaign inputs other slices can reference by ref

Exit criteria:

- document and image uploads persist in the campaign workspace
- asset summaries and refs are available to setup and later prompts
- sendable tagging remains explicit and operator-controlled

### Slice 3: Planning Work Families Transition

Land [Planning Work Families Transition](./planning-work-families-transition.md) third.

Why here:

- setup and assets define the durable campaign context the work families should consume
- this is the slice that actually turns the current staged planning runtime into a campaign control loop
- later signal and routing work become much cleaner once planning is clearly work-item-owned

Exit criteria:

- discovery, strategy, and account planning are described and treated as campaign work families
- work items and schedules are the durable planning control objects
- completed artifacts no longer imply the campaign loop is done
- `workflow_stage` is explicitly a compatibility summary rather than the real driver

### Slice 4: Campaign Signals

Land the deterministic half of [Campaign Signals And Observation Review](./campaign-signals-and-observation-review.md) next.

This slice should stop at:

- signal record shape
- signal storage
- dedupe rules
- signal bridge from existing live seams
- observation work refresh rules

It should not yet require the full review agent.

Exit criteria:

- important incidents create deduped signal records
- observation work can be refreshed from deterministic runtime pressure
- no live write path depends on LLM review

### Slice 5: Observation Review

Finish the review-agent half of [Campaign Signals And Observation Review](./campaign-signals-and-observation-review.md).

Why after deterministic signals:

- the review agent needs a clean bounded input
- testing is easier once signal generation is stable
- the runtime can already accumulate useful signal history before review is turned on

Exit criteria:

- observation review consumes compact unresolved signals
- the review returns a structured steering brief
- repeated old signals are not repeatedly re-prompted
- review results and cursor state persist under the campaign workspace
- deterministic follow-on mapping from review advice into planning refresh actions is locked before routing-priority work begins

### Slice 6: Routing Integration

Land [Orchestrator Routing And Compatibility](./orchestrator-routing-and-compatibility.md) last.

Why last:

- setup, assets, and signals need to exist before routing can prioritize them coherently
- routing changes are easier to validate after the underlying states and work items are real

Exit criteria:

- setup gating, planning work, and observation pressure coexist cleanly
- current discovery -> strategy -> account-planning behavior does not regress
- `workflow_stage` remains a compatibility summary

## Transition Coverage

This sequence now maps directly to the six architectural transition moves in the umbrella rebuild note:

1. setup becomes campaign initialization
2. assets become campaign inputs
3. planning stages become work families, not the architecture
4. live runtime outcomes become structured campaign signals
5. observation becomes the steering layer
6. the orchestrator routes by campaign pressure, not by stage

## Non-Goals For The First Delivery Pass

- outbound media sending
- deep transcript analytics
- real-time observation review on every live event
- replacing existing planning specialists wholesale

## Cross-Slice Validation

After each slice:

- run the smallest focused pytest coverage for the touched seam
- verify current text-only Telegram planning still works
- verify new persistence survives restart where applicable

Before calling the series implementation-ready:

- run `python -m pytest tests/` if the local tree is in a stable enough state
- run at least one Telegram smoke flow covering setup, discovery start, and a no-regression planning path
