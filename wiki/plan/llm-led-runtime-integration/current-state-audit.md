# Current State Audit

## Goal

Record what the current runtime already has in place for the combined LLM-led behavior plus compiled-intent direction, and identify the remaining blockers that still keep the control plane more rigid than the specs now intend.

## What Is Already Landed

### The Runtime Already Has Valuable Structured Seams

The repo already persists several campaign-native structures that make a gradual compiler migration realistic:

- campaign intent synthesis in `telegram_app/campaign_intent.py`
- campaign context promotion in `telegram_app/campaign_context.py`
- durable work items in `telegram_app/work_items/manager.py`
- durable schedules in `telegram_app/scheduling/manager.py`
- durable live conversation state in `telegram_app/external_conversations/`
- durable live outreach triage and belief state in `telegram_app/external_conversations/models.py`

This means the repo does not need to invent typed persistence from scratch before it can adopt a compiled-intent layer.

### Work And Schedule Persistence Are More Flexible Than The Current Routing Layer

`WorkItemManager` and `ScheduleManager` both persist string-valued `work_type` data rather than a deeply closed enum-only ontology.

That is an important enabling fact because it means the storage layer is not the main source of rigidity.

The bigger bottlenecks are:

- hardcoded follow-on assumptions in the orchestrator
- marker-first prompt contracts
- narrow validation helpers
- phrase and regex control interpretation paths

### The Outreach Runtime Already Has Most Of The Behavioral Seams

The repo already has the major live outreach reasoning seams that the narrower outreach plan describes:

- richer live evidence and outbound continuity
- cheap first-pass inbound triage
- durable conversation belief state
- promoted-thread commercial reasoning
- commercial opportunity and yield visibility

That means the remaining integration work is not primarily about inventing a new outreach machine from zero.

It is about making the control plane capable of carrying that machine cleanly.

## Where The Remaining Rigidity Still Lives

### Marker-First Prompt Contracts

Several active surfaces still rely on prompt-authored markers plus fenced JSON blocks as the main control interface:

- `prompts/orchestrator.md`
- `prompts/discovery.md`
- `prompts/live_engagement_review.md`
- `telegram_app/workflow_validation.py`

Those contracts are still useful as transition tools, but they are too narrow to serve as the long-term main control plane.

### Phrase-Gated Operator Interpretation

The runtime still interprets important operator intent through explicit phrase matching and regex heuristics in places such as:

- `telegram_app/live_ops/service.py`
- `telegram_app/campaign_context.py`
- `telegram_app/campaign_intent.py`
- approval and revision parsing inside `telegram_app/orchestrator/orchestrator.py`

Those heuristics are legible, but they keep freeform operator control narrower than the specs now want.

### Fixed Follow-On Ladder Assumptions

The orchestrator still contains stage and follow-on assumptions such as:

- `WORK_TYPE_TO_STAGE`
- `FOLLOW_ON_WORK_TYPE`
- artifact-kind mapping helpers
- direct review acceptance paths that imply the next planning family

Those assumptions are the clearest remaining expression of the old `discovery -> strategy -> account_planning` ladder.

### Validation Still Targets Narrow Output Shapes

`telegram_app/workflow_validation.py` still validates several outputs against narrow point contracts.

That is useful for safety, but today those validators are attached to the old surface:

- parse one marked block
- validate that single schema
- apply that one meaning

The combined spec direction needs a broader reusable pattern:

- compile zero or more intents
- validate each intent by kind
- let deterministic code decide what is accepted, rejected, advisory only, or applied

## Practical Implication

The first implementation target should not be a giant rewrite of storage or execution.

The repo should instead start by introducing:

- one reusable compiled-intent envelope
- one persistence seam for those compiled intents
- one transition path for operator control and work proposals

That gives the runtime a new middle layer without disturbing deterministic execution too early.

## Main Blocking Truth

The runtime is already much closer to the desired end state than the old mixed docs made it seem.

The main remaining blockers are not missing LLM behavior seams.

They are:

1. the lack of a first-class compiled-intent envelope
2. the lack of a reusable compiler-and-applicator path
3. the continued dependence on marker-first and phrase-first interpretation at key control points
4. the continued dependence on fixed follow-on planning assumptions in the orchestrator
