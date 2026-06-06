# Implementation Sequence

## Goal

Turn the agentic campaign runtime direction into a practical delivery order.

## Recommended Order

### Step 1: Canonical Campaign Spec And Revision Control

Why first:

- the rest of the runtime should converge on one source of truth instead of many refreshable planning roots
- live execution, reporting, and autonomous adaptation need one pinned active revision before more slices are added
- this is the simplification step that reduces later coordination and invalidation risk

### Step 2: Campaign Intake And Synthesis

Why second:

- the runtime still depends on mixed-input campaign understanding
- intake should now target the canonical campaign spec and proposed revision shape instead of growing more compatibility-only state

### Step 3: Asset Role Inference

Why third:

- uploaded assets are already in the runtime, so this is a high-leverage upgrade on a landed seam
- strategy, execution, and qualification all benefit from richer asset meaning

### Step 4: Conversion Target Contract

Why fourth:

- conversion is the business goal and should stop being implicit
- later qualification and handoff logic need a stable destination contract

### Step 5: Qualification And Handoff Runtime

Why fifth:

- once the runtime knows the offer, assets, and destination, it can reason about qualification concretely
- this is the first slice that turns engagement into measurable business progression

### Step 6: Continuous Autonomous Operations

Why sixth:

- the runtime should continue operating only after the earlier campaign interpretation and conversion primitives exist
- this keeps the autonomy loop grounded in a real campaign model
- autonomous operational changes should promote new live revisions and notify the operator instead of reopening long planning chains

### Step 7: Operator Notifications And Recovery

Why seventh:

- once continuous operation and autonomous revision promotion exist, operator notification and recovery surfaces become higher leverage and easier to design honestly

## Cross-Step Acceptance

After each step:

- update the current-state audit
- add focused tests for the new seam
- verify ordinary Telegram campaign turns still work

Before calling the series operational:

- the runtime should own one canonical campaign spec and one pinned active revision
- derived discovery, strategy, and account-plan views should regenerate from the same revision source
- mixed campaign intake should work with files, links, and seed dumps
- conversion targets should be visible in runtime state
- qualification should be campaign-specific
- campaigns should be able to continue until paused, blocked, or resource-starved
- autonomous operational changes should notify the operator clearly without forcing approval checkpoints for every live tuning change
