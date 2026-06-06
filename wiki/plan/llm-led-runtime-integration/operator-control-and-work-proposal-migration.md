# Operator Control And Work Proposal Migration

## Goal

Move operator freeform control and planning refresh behavior onto the compiled-intent path first, before migrating deeper specialist outputs or live execution requests.

## Why This Slice Should Be Early

Operator control is the best first compiler target because it is:

- high leverage
- easy to inspect
- lower risk than outbound execution
- currently spread across multiple phrase-gated and regex-gated surfaces

It is also the place where the two specs meet most directly:

- freeform operator language should stay natural
- runtime mutation should still become typed and inspectable

## Primary Migration Surfaces

### Live Ops Control Interpretation

Current surface:

- `telegram_app/live_ops/service.py`

Migration direction:

- keep the current natural-language UX
- compile the message into one or more typed control intents
- let deterministic applicators route accepted intents into the existing live-ops managers
- keep narrow fallback phrase handling during shadow mode only

### Campaign Context Promotion

Current surface:

- `telegram_app/campaign_context.py`

Migration direction:

- treat voice, safeguard, preference, ambiguity, and decision updates as typed context intents rather than only as extracted clauses
- keep the current artifact shape as an application target during transition

### Campaign Intent And Intake Interpretation

Current surface:

- `telegram_app/campaign_intent.py`

Migration direction:

- keep current interpretation helpers as bounded extraction tools
- move their output behind a compiler seam so campaign control or setup mutations are represented as typed proposals
- avoid letting one extraction helper implicitly own the control plane

### Orchestrator Planning Follow-On Logic

Current surface:

- `telegram_app/orchestrator/orchestrator.py`

Migration direction:

- stop treating artifact approval as a direct hardcoded instruction to run the next family
- compile follow-on planning recommendations into typed work proposals
- let deterministic evaluation decide whether to create, refresh, deprioritize, or leave work untouched

## Recommended Transition Strategy

### Step 1: Shadow Compilation

For selected operator turns:

- compile intents
- persist them
- still let the legacy control path execute
- compare whether compiled meaning matches applied meaning

This step proves the envelope without immediately changing runtime behavior.

### Step 2: Intent-First Application For Narrow Kinds

Promote a small set of intent kinds to the primary path:

- `campaign_control.update_voice`
- `campaign_control.update_safeguard`
- `schedule.create`
- `schedule.pause`
- `schedule.resume`

These are concrete, bounded, and already mapped to deterministic managers.

### Step 3: Work Proposal Evaluation

Once control intents are stable:

- compile planning follow-on decisions into `work.propose` or `work.refresh`
- evaluate those proposals deterministically against campaign state, existing open work, and stale-ness rules
- keep `workflow_stage` as a summary projection only

## Acceptance Criteria

This slice is complete when:

- operator freeform control can compile into multiple typed intents from one message
- accepted control intents can apply through existing deterministic managers
- schedule mutation no longer depends primarily on one prompt-authored marker block
- work follow-on creation can be expressed as proposals rather than a fixed next-step ladder
- legacy phrase and marker paths are either shadow-only or narrow fallbacks
