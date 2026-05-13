# Approval And Guardrails

## Purpose

Define how the Telegram-native app should think about approvals, policy boundaries, and staged safety controls.

This document is not the final enforcement design. It is the architectural and product-level framing for where human review and guardrails belong.

## Design Goal

The platform should support broad agent autonomy while still preserving clear intervention points for risky, ambiguous, or sensitive actions.

The first implementation phase should:

- identify approval surfaces
- document guardrail categories
- keep policy boundaries explicit
- defer heavy enforcement where appropriate

## Core Position

The system should not pretend that prompts alone are enough forever.

Prompts and role definitions are useful first-layer controls, but the architecture should reserve clear places for stronger approval and enforcement mechanisms.

## Approval Philosophy

Approvals should be used where they materially reduce risk or ambiguity, not as a blanket requirement for every action.

The goal is to preserve operator control over consequential decisions while keeping the app usable.

## Approval Surface Categories

### 1. Community Entry Approvals

Examples:

- approving a shortlist of communities
- approving joins into higher-risk communities
- approving entry into communities with unclear moderation posture

Why it matters:

- community selection is one of the earliest points where campaign risk compounds

### 2. Strategy Approvals

Examples:

- approving message angles
- approving community-specific playbooks
- approving stronger CTA or positioning choices

Why it matters:

- messaging quality and tone directly affect reputation and moderation risk

### 3. Account Assignment Approvals

Examples:

- approving which accounts enter which communities
- approving warm-up exceptions
- approving higher-risk pacing or reuse decisions

Why it matters:

- account health is a long-lived asset and should not be spent casually

### 4. Write Action Approvals

Examples:

- sending messages
- joining communities
- executing sensitive account actions

Why it matters:

- writes are where analysis becomes observable external behavior

## Guardrail Categories

### Behavioral Guardrails

Intended concerns:

- deceptive behavior
- manipulative coordination
- context-insensitive posting
- spammy interaction patterns

### Account Safety Guardrails

Intended concerns:

- high-frequency joins or writes
- poor pacing
- risky account reuse
- ignoring account health signals

### Community Respect Guardrails

Intended concerns:

- posting in communities that ban promotion
- ignoring visible community norms
- entering communities without sufficient profiling

### Approval Guardrails

Intended concerns:

- high-risk actions taken without operator review
- missing escalation when ambiguity is high

## Guardrail Maturity Model

The intended maturity path is:

1. Document guardrails in specs and prompts.
2. Mark workflows with approval-sensitive steps.
3. Introduce structured risk annotations and approval state.
4. Add selective enforcement in execution paths.
5. Expand policy enforcement only where clearly justified.

This supports staged product development without losing architectural discipline.

## Control Ownership

### Prompts Own First-Layer Behavior Shaping

- shared instructions
- role prompts
- workflow-specific guidance

### Orchestrator Owns Escalation And Review Coordination

- determines when operator review is needed
- frames the decision clearly
- resumes work after conversational operator input
- manages campaign-level scheduling without letting scheduled work bypass approval boundaries

### App Runtime Owns Approval State Plumbing

- should reserve hard approval state for irreversible or external write actions
- should avoid blocking normal planning turns behind persisted approval checkpoints
- should avoid blocking normal scheduled memory-maintenance or review work behind heavy approval gates
- should avoid deciding in code whether an operator reply is approval, clarification, or a changed instruction

### Capability Layer Owns Execution Hooks

- exposes opportunities for approval checks
- returns risk metadata where useful
- preserves audit visibility

### State Layer Owns Approval Memory

- pending approvals
- resolved decisions
- rationale and audit trail

## MVP Recommendation

For MVP, hard approvals should likely be strongest around:

- joins into Telegram communities
- sending messages or other external write actions
- account-affecting actions that materially change health or pacing risk

Planning artifacts, campaign-memory updates, recurring discovery refreshes, and strategy reviews should prefer conversational review checkpoints over runtime-enforced gates.

Automatic high-volume engagement should remain out of scope.

## Non-Goals

This document does not yet define:

- final policy engine logic
- exact risk scoring algorithms
- exact enforcement code paths
- full compliance framework

## Design Principles

- Guardrails should be visible before they are fully automated.
- Hard approvals should protect consequential external actions, not suffocate normal workflows.
- The app should prefer explicit pending decisions over hidden uncertainty.
- Safety architecture should be layered rather than all-or-nothing.

## Success Criteria

This design is successful when:

1. The team knows where human review belongs before implementation hardens.
2. The orchestrator can pause and resume around meaningful decisions.
3. Future enforcement can be added without redesigning the whole workflow model.
4. The platform can support broad agent capability without pretending risk does not exist.

## Open Questions

- Which write actions should always require approval in MVP?
- Should approval rules be global, workflow-specific, or account-tier-specific?
- What minimum evidence should accompany an approval request?
- How should the system behave when the operator does not respond to a pending approval?
