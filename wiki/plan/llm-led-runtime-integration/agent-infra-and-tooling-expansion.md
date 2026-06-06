# Agent Infra And Tooling Expansion

## Goal

Expand the runtime-side agent infrastructure so reasoning surfaces can see more of the real campaign state, use richer bounded tools, and inspect proposal outcomes without weakening the compiled-intent mutation boundary.

This slice is about making agents better informed and better equipped, not about giving them broad direct write access.

## Why This Needs Its Own Slice

The repo is already moving toward the right control-plane shape:

- reasoning is increasingly separated from deterministic mutation
- compiled intents provide an inspectable mutation boundary
- live outreach reasoning already uses richer proposal contracts than the old planning ladder

But the current reasoning surfaces are still narrower than the final architecture wants.

Today the main limitations are:

- planning specialists do not consistently see active work, active schedules, proposal outcomes, or runtime readiness facts in prompt context
- capability access is still narrow and uneven across reasoning surfaces
- durable artifacts still carry too much of the machine-readable meaning for planning runs
- the runtime can persist proposal lifecycle state, but that state is not yet broadly visible back to the agents that need to reason about it

The result is a runtime that is safer than it is informed.

That is acceptable during migration, but it is not the intended end state.

## Design Principles

### Read Broadly, Write Narrowly

Agents should have wider bounded read access to campaign state, runtime health, and proposal outcomes.

Agents should still request state changes through typed proposals or compiled intents rather than direct ad hoc writes.

### Tooling Should Be Bounded And Auditable

Richer tooling should not mean open-ended runtime reach-through.

Tool access should stay:

- bounded by narrow interfaces
- role-appropriate
- replayable or inspectable where practical
- explicit about unavailable data and backend gaps

### Prompt Context Should Be Richer But Not Noisy

The answer to under-informed reasoning is not dumping the whole database into prompts.

The runtime should expose:

- compact summaries by default
- targeted read helpers for deeper inspection
- stable prompt-safe shapes for high-value state

### Proposal Feedback Must Be Visible

If the runtime accepts, rejects, blocks, or defers proposals, that outcome should become readable state for future reasoning.

Otherwise the agents cannot learn from the system's own deterministic decisions.

## Primary Expansion Areas

### 1. Richer Runtime-State Context For Reasoning Surfaces

Current limitation:

- `build_runtime_context(...)` can include active work items and schedules, but many specialist runs do not pass them through
- proposal lifecycle and blocked reasons are not surfaced consistently back into prompt context

Expansion direction:

- include active work items and active schedules by default for planning-oriented specialist runs
- expose a compact recent proposal summary showing accepted, rejected, blocked, and applied outcomes where relevant
- expose campaign readiness and worker-health summaries to the orchestrator and observation-style reasoning surfaces
- expose compact traction and live-pressure summaries so planning does not reason in a vacuum

Candidate surfaces:

- `telegram_app/orchestrator/context_builder.py`
- `agents/discovery/agent.py`
- `agents/strategy/agent.py`
- `agents/account_manager/agent.py`
- `agents/observation/agent.py`

### 2. A Bounded Agent-Tooling Broker For Read Access

Current limitation:

- capability protocols exist, but they are unevenly consumed and too narrow to act as a general reasoning substrate
- planning surfaces mostly receive pre-baked summaries rather than being able to ask for the next bounded read

Expansion direction:

- add one explicit runtime-owned agent-tooling seam for read-side access
- keep it narrow and role-aware
- make it the standard way for reasoning surfaces to request deeper bounded reads without inventing bespoke glue each time

Recommended responsibilities for this seam:

- campaign-state lookups
- work-item and schedule lookups
- compiled-intent and proposal lifecycle summaries
- conversation and traction summaries
- readiness and worker-health summaries
- bounded capability passthroughs for community, account, and messaging reads

Recommended shape:

- one new `telegram_app/agent_runtime/` or similarly named package
- one small broker object that aggregates runtime managers and capability facades
- prompt-safe helper methods plus narrow direct read methods for targeted use

This seam should not own:

- queue mutation
- direct execution authorization
- freeform writes into campaign state

### 3. Proposal-Lifecycle Inspection As First-Class Context

Current limitation:

- the runtime stores compiled intents and their lifecycle, but future reasoning surfaces do not broadly see what the runtime accepted, rejected, or blocked

Expansion direction:

- provide compact summaries of recent proposal outcomes per campaign, per work family, and per conversation when relevant
- preserve reason codes or application-result summaries for blocked or rejected proposals
- let observation and planning reasoning use those outcomes to adjust future decisions

Examples of useful inspection facts:

- repeated `schedule.create` rejection because the payload was incomplete
- `engagement.next_move` proposals repeatedly blocked by readiness or consent posture
- work refresh proposals accepted but deprioritized because a fresher work item already exists

Candidate surfaces:

- `telegram_app/compiled_intents/store.py`
- `telegram_app/compiled_intents/models.py`
- `telegram_app/orchestrator/context_builder.py`
- `telegram_app/engagement_brain/coordinator.py`

### 4. Expand Read-Only Capability Coverage Before Expanding Write Power

Current limitation:

- planning surfaces can search communities and inspect some profiles
- account planning can list roster state
- live reasoning has better access to conversation evidence
- there is still no unified read-side story for "show me what the runtime already knows"

Expansion direction:

- prefer adding read-only capability and state-inspection methods before adding any new mutation kinds
- only add new mutation kinds when the proposal boundary has a clear deterministic applicator

High-value read additions:

- bounded recent compiled-intent history
- bounded open-work and due-schedule views
- bounded worker-readiness and backend-readiness view
- bounded conversation hotspot and traction view
- bounded account posture and account-risk summary view
- bounded community-activity samples or linked-chat notes where capability data allows it

### 5. Let Planning Surfaces Emit More Than One Kind Of Meaning

Current limitation:

- planning specialists still tend to emit one durable artifact as the main machine-readable output

Expansion direction:

- keep operator-review artifacts where they are useful
- let planning-oriented surfaces also emit typed proposal lists in the same run
- make artifact creation and proposal emission parallel outputs rather than mutually exclusive modes

Examples:

- discovery can save a shortlist artifact and propose a review posture update plus a follow-up validation work item
- strategy can save a playbook artifact and propose a memory note plus a refresh of live-reply tone contract
- account planning can save an assignment artifact and propose readiness notes, schedule changes, or execution-preparation work

## Recommended Transition Strategy

### Step 1: Context Enrichment Without New Mutation Power

First expand what the agents can see.

Start by:

- passing active work items and schedules into planning-specialist runtime context
- adding compact readiness, traction, and unresolved-proposal summaries to prompt-safe context
- proving token cost remains bounded

This is the safest first step because it does not widen mutation authority.

### Step 2: Introduce A Shared Read-Side Agent Runtime Seam

Once the highest-value context facts are known:

- add one runtime-owned broker or service for bounded agent reads
- route existing bespoke specialist lookups through that seam where practical
- avoid widening direct capability dependencies across many agent classes

This keeps coupling lower than continuing to bolt one custom helper onto each agent.

### Step 3: Add Proposal-Lifecycle Visibility

After the broker exists:

- expose compact recent compiled-intent outcomes
- include blocked and rejected summaries where those outcomes should inform future reasoning
- allow observation, planning refresh, and live-review surfaces to reason over proposal history instead of only over artifacts

### Step 4: Upgrade Planning Outputs To Artifact Plus Proposal Lists

Once richer reads are available:

- move planning specialists toward emitting durable artifacts plus typed proposals in the same run
- avoid forcing all machine-readable meaning back into one artifact schema

### Step 5: Narrow Remaining Bespoke Read Glue

After the shared agent-runtime seam is proven:

- remove duplicated specialist-specific runtime lookups that exist only because the shared seam did not exist yet
- keep truly unique surface logic only where it reflects domain differences rather than infrastructural gaps

## Non-Goals

This slice does not mean:

- giving planning agents raw write access to managers
- letting prompts mutate runtime state without compilation
- exposing unbounded message history or giant raw state dumps to every prompt
- bypassing consent, readiness, or execution policy
- replacing deterministic application with agent-authored side effects

## Acceptance Criteria

This slice is complete when:

- planning and observation reasoning surfaces can see active work, schedules, and compact runtime-pressure state without bespoke prompt hacks
- at least one shared read-side agent-runtime seam exists for bounded runtime and capability inspection
- recent proposal outcomes are inspectable by future reasoning surfaces in compact prompt-safe form
- planning-oriented surfaces can emit durable artifacts and typed proposals together
- richer read access does not weaken the compiled-intent mutation boundary
- direct state mutation still happens only through deterministic applicators or other deliberate runtime-owned write seams
