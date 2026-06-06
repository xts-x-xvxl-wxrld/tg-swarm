# LLM-Led Outreach Runtime

## Purpose

Define the desired operating shape for the live outreach machine when the product goal is not a rigid workflow engine, but an LLM-driven operator-facing campaign system.

This spec clarifies where the app should be adaptive, where it should stay deterministic, and which current weak points materially reduce outreach effectiveness.

## Relationship To Freeform Compilation

This spec is the behavioral source of truth for the outreach machine.

It should define:

- what the system should be good at commercially
- what kinds of judgment the LLM should own
- what kinds of discipline the runtime should preserve
- what outcomes count as better outreach behavior

It should not be the main place where the repo defines:

- how freeform agent reasoning gets compiled into runtime intents
- how broadly extensible the control plane should be
- how marker-based contracts should be replaced over time
- how structured runtime proposals should flow into authorization and execution

Those boundary and control-plane concerns now belong to:

- [Freeform-To-Structured Compilation](C:/Users/ravil/OneDrive/Desktop/tg-swarm/wiki/spec/freeform-to-structured-compilation.md)

## Design Goal

The runtime should behave like a commercially aware outreach operator with durable memory and bounded autonomy.

It should not feel like:

- a form-driven workflow runner with a thin reply generator attached
- a brittle trigger tree that only reacts to predetermined engagement states
- a safety shell that is strong at blocking mistakes but weak at recognizing opportunity

The target is an LLM-led outreach machine where reasoning creates the edge and deterministic seams keep that reasoning safe, inspectable, and restart-safe.

## Core Principle

The LLM stack should own judgment.

The runtime should own discipline.

Not every judgment call needs the same model.

A cheaper model tier should handle bulk inbound reading, lightweight interest and momentum signals, and review prioritization.

A more capable model tier should handle deeper conversation interpretation, belief-state updates, commercial next-move reasoning, and outbound-related decisions once a thread is worth closer review.

Judgment includes:

- interpreting mixed campaign input
- interpreting operator steering such as "do not start yet", "pause this path", or "lean more technical" from normal language rather than rigid commands
- reading live conversation context
- deciding what kind of reply, follow-up, or escalation best fits the moment
- deciding when proactive group outreach is worth attempting, which angle to test, and which threads should be nurtured toward DM or direct conversion
- inferring why a conversation is advancing or stalling
- synthesizing campaign learnings into better future behavior
- choosing what deserves attention now

Discipline includes:

- event capture and normalization
- durable state persistence
- queueing, claims, retries, and idempotency
- hard safety and consent enforcement
- account and community health posture
- pause and resume controls
- backend and worker readiness for inbound listening, review, and execution
- operator-visible audit trails

## Desired Behavioral Shape

The live machine should behave less like `deterministic gate -> LLM draft -> deterministic send` and more like a commercially aware system that:

- observes richer evidence before deciding what it means
- uses a cheap bounded review layer for broad coverage
- uses a deeper reasoning layer for commercially meaningful moments
- treats proactive group outreach as a first-class way to create attention
- adapts from accumulated context and learned campaign memory rather than brittle trigger trees

## Final Agent-System Shape

The final runtime should not treat a small fixed specialist ladder as the architecture.

The long-lived architecture should be:

- one operator-facing control brain that interprets freeform operator steering and campaign state
- several bounded reasoning surfaces that each own one kind of judgment
- one shared proposal boundary where reasoning becomes typed runtime intent
- one deterministic policy and execution boundary that remains late in the flow

In practical terms, that means the runtime should look more like:

- **Operator Control Brain** for freeform operator intent, campaign steering, pauses, safeguards, tone changes, and work selection
- **Campaign Planning Brain** for campaign interpretation, discovery, strategy, account planning, and future planning work families such as objection analysis or outreach-angle experiments
- **Cheap Inbound Triage Brain** for broad, low-cost reading of newly eligible inbound message flow
- **Promoted-Thread Reasoning Brain** for deeper commercial interpretation, belief-state updates, next-move selection, and compact campaign learnings
- **Observation / Opportunity Brain** for campaign-level prioritization, refresh pressure, and opportunity detection across live signals
- **Deterministic Applicators And Execution Policy** for persistence, authorization, consent, readiness, queueing, retries, and external writes

This is intentionally different from a permanent `discovery -> strategy -> account_planning` top-level architecture.

Those planning families may remain useful, but they should survive as bounded work families inside a broader proposal-driven runtime rather than as the only first-class agent ontology.

The goal is:

- fewer fixed top-level specialists
- richer bounded reasoning surfaces
- more extensible work-family selection
- one reusable typed proposal path
- late deterministic execution gates

## What The LLM Should Own

### 1. Bulk Inbound Interpretation And Triage

The cheaper review layer should infer:

- whether fresh inbound likely reflects interest, objection, urgency, confusion, or low-signal chatter
- whether the thread probably deserves deeper review by the more capable commercial reasoning layer
- whether new evidence changes review priority, follow-up pressure, or campaign-signal pressure

This layer should optimize for coverage, bounded structure, and cost efficiency.

It should not be responsible for final outbound strategy.

### 2. Conversation Interpretation

The higher-capability LLM should infer:

- whether a message shows curiosity, fit, objection, urgency, skepticism, or buying intent
- whether the last outbound message helped or hurt momentum
- whether the thread should stay public, move to DM, hold, or escalate
- whether the current moment is best served by answering, probing, reframing, qualifying, or routing

This should not be reduced to keyword classification over only the latest inbound message.

### 3. Campaign-Level Outreach Reasoning

The LLM should infer:

- which communities are producing high-quality conversations
- which message angles are generating replies versus dead ends
- which offer facts create traction
- which objections are recurring
- which accounts or communities are productive but fragile

This is the main source of edge over deterministic workflow tools.

### 4. Proactive Group Outreach

The higher-capability runtime should be allowed to initiate outbound group posts without waiting for an inbound message first when campaign posture allows it.

The LLM should decide:

- when a group is worth posting into proactively to generate real user interest
- which angle or claim set best fits the community and current campaign posture
- when a public conversation should stay in-group, move to DM, or route directly to the campaign conversion target
- when a group opportunity is commercially weak enough to skip rather than forcing activity

This proactive outreach path should be treated as a core operating mode, not as a side effect of a rigid prewritten schedule.

### 5. Prioritization

The LLM should help decide:

- which conversations deserve follow-up first
- which stalled threads are still worth pursuing
- which signals indicate a plan refresh
- which operator escalations are commercially important rather than merely operationally noisy
- which planning or outreach work family is most worth running next

### 6. Qualification And Routing

Qualification should stay campaign-specific and evidence-aware.

The LLM should determine:

- whether a lead is early, promising, objection-heavy, or conversion-ready
- what missing information still matters
- whether a conversion step should happen now or after one more clarifying turn

Deterministic code should persist the resulting structured state, not replace the reasoning path.

## What Deterministic Code Should Own

### 1. Hard Constraints

The runtime must continue to deterministically enforce:

- inbound-first DM rules
- proactive group outreach posture and reply posture once the current campaign settings are resolved
- account pause, cooldown, and flagged/banned posture
- community risk pauses
- malformed or mismatched approval context
- campaign, conversation, and account pause state

### 2. Evidence Integrity

The runtime must preserve:

- inbound events
- outbound content and metadata
- thread lineage
- review triggers
- execution outcomes
- qualification and handoff history

The LLM can only be good if the evidence surface is rich and stable.

### 3. Operational Discipline

The runtime should remain deterministic in the parts that keep autonomy safe and restartable, such as:

- queue operations
- trigger claiming
- retries
- dedupe rules
- write-protecting state transitions
- readiness checks that confirm required workers and backends are actually available

## Current Weak Points Through This Lens

### 1. The System Compresses Live Meaning Too Early

Current engagement ingestion recognizes only a narrow set of events and often decides too early whether something matters.

This weakens an LLM-led machine because the LLM receives too little evidence.

The runtime should capture more raw but normalized interaction evidence before deciding what it means.

### 2. Conversation Context Is Too Thin

Recent thread reconstruction does not preserve enough outbound content and interaction texture.

That makes the LLM reason over partial context, which collapses continuity and hurts reply quality.

The runtime should treat outbound text, media refs, timing, and prior decision summaries as first-class thread evidence.

### 3. Positive Engagement State Is Under-Modeled

Today the runtime is much better at recording friction than momentum.

It knows about:

- rate limits
- policy blocks
- write friction
- pauses

It is weaker at persistently modeling:

- genuine interest
- repeated re-engagement
- objection resolution
- CTA acceptance
- account-level or community-level yield quality

An outreach machine needs both downside signals and upside signals.

### 4. Qualification Is Too Narrowly Reduced

Qualification and handoff depend too directly on the current bounded classifier output.

The runtime needs a richer conversation-state model so the LLM can accumulate evidence across turns rather than re-judging from scratch each time.

### 5. Continuous Ops Tracks Operational Motion More Than Commercial Motion

The campaign-level summary is currently better at answering:

- is the loop blocked
- are there unresolved signals
- is work queued

than:

- are we getting traction
- which paths convert
- where are we losing interested people
- which accounts and communities are worth more effort

That is an effectiveness gap, not only a reporting gap.

### 6. Operational Readiness Is Too Implicit

The system can appear campaign-ready while the live autonomy loop is not actually running.

That is a major gap because the outreach machine depends on real backend availability for:

- managed-account inbound listening
- cheap triage and promoted-thread review
- queued live execution

Readiness should include backend and worker health, not only campaign data completeness or control completeness.

## Required Design Shifts

### Shift 1: Preserve A Richer Outreach Evidence Layer

The runtime should store enough evidence for the LLM to reason well later.

Minimum additions:

- outbound message text and asset refs
- more inbound event types and metadata
- thread-level decision summaries
- response timing facts
- campaign/account/community linkage evidence for DM continuation

### Shift 2: Add A Durable Conversation Belief State

Each external conversation should carry a compact, updateable belief state, not just status and next action.

It should summarize:

- current intent posture
- known objections
- known fit signals
- unanswered questions
- commercial stage
- last meaningful shift
- suggested next move

This belief state should be LLM-authored and deterministically persisted.

### Shift 3: Add Positive-Signal And Yield Modeling

The campaign signal layer should record opportunity, not only danger.

Examples:

- repeated inbound from same user before reply
- public-to-DM transition
- clarified need
- pricing interest
- CTA acceptance
- handoff completion
- account-level high-yield thread creation
- community-level high-yield conversation density

These can still be derived deterministically from durable evidence after the fact, but they must exist as first-class runtime facts.

### Shift 4: Add A Cheap First-Pass Inbound Review Layer

Most inbound message flow should be read first by a cheaper bounded model before the runtime spends a higher-capability model on deep review.

Its job should be to:

- classify lightweight interest, objection, urgency, and momentum signals
- detect low-signal chatter versus commercially meaningful inbound
- emit compact structured facts that downstream review and prioritization can trust
- decide whether a conversation should be promoted into deeper commercial reasoning

This layer should reduce token spend without blinding the runtime to real buying intent, re-engagement, or objection patterns.

### Shift 5: Make The Higher-Capability Review Layer More Central

The deeper conversation-review worker should become the core live reasoning loop for promoted threads, not just a bounded helper around triggers.

Its job should expand toward:

- interpreting fresh evidence
- updating conversation belief state
- deciding whether to queue a send, defer, ask, escalate, or mark a thread as low-value
- emitting compact learning notes for campaign memory

### Shift 6: Make Proactive Group Outreach A First-Class Autonomous Path

The runtime should support campaign-owned autonomous group outreach directly, not only as a deterministic prepared-wave artifact.

That means:

- LLM reasoning should be able to choose when to post proactively in groups in order to create real attention
- proactive group posts should feed the same evidence, belief-state, qualification, and conversion paths as reactive replies
- public engagement should be optimized to generate legitimate inbound replies and DM continuation opportunities without violating DM consent posture

### Shift 7: Add Explicit Runtime Readiness And Worker Health

The live outreach machine should not present itself as operationally ready unless the required backend and background workers are actually available.

Minimum readiness should include:

- managed-account capability backend is real, not a stub
- inbound listener is running
- conversation-review worker is running
- live-execution worker is running

This readiness state should be visible to the operator from inside Telegram.

### Shift 8: Introduce Commercial Effectiveness Summaries

Continuous ops should add campaign health facts such as:

- new active conversations
- reply rate by account and community
- objection-heavy thread count
- conversion-ready thread count
- handoff delivered count
- unresolved high-opportunity threads
- stale but previously promising threads

These should inform both operator summaries and LLM prioritization.

## Desired Runtime Flow

1. Capture inbound and outbound evidence durably.
2. Let operator steering shape campaign posture, work selection, and autonomy boundaries without forcing the machine back into a rigid workflow.
3. Run a cheap bounded inbound-read layer over newly eligible message flow.
4. Persist lightweight signals, review-priority updates, and promotion-worthy thread facts.
5. Project or refresh the campaign-linked conversation record.
6. For promoted conversations, rebuild a bounded but rich context packet.
7. Ask the higher-capability LLM to:
   - interpret the moment
   - update conversation belief state
   - choose the best next move
   - emit any learning-worthy campaign notes
8. Persist the structured result.
9. When campaign posture allows it, let the runtime also originate proactive group outreach to create new conversation surface.
10. Run deterministic authorization, consent, readiness, and policy checks.
11. Execute allowed actions through the queue.
12. Feed outcomes back into conversation, campaign, account, and community state.

Planning-oriented work should follow the same general shape:

1. The operator control brain or runtime pressure selects a bounded planning work family.
2. The relevant reasoning surface produces operator-facing prose, optional durable artifacts, and typed proposals.
3. The runtime persists and evaluates those proposals deterministically.
4. Follow-on planning, memory, and live posture changes are chosen from typed proposals rather than a fixed next-step ladder.

## Non-Goals

This direction does not mean:

- removing deterministic safety rails
- running every inbound message through the most capable model
- letting the LLM send without policy and posture checks
- allowing outbound DMs before the external user has messaged first
- replacing durable state with freeform summaries only
- turning the runtime into an unconstrained autonomous improviser

The goal is stronger reasoning on top of stronger evidence, not weaker operational discipline.

## Success Criteria

This design is correct when:

1. The runtime preserves enough evidence that the LLM can reason over real thread continuity.
2. Cheap inbound reads reduce token spend without hiding real interest, objections, urgency, or re-engagement from the system.
3. Positive outreach momentum is modeled as explicitly as risk and friction.
4. Conversation progression reflects accumulated belief state, not only latest-message heuristics.
5. Deterministic code protects safety and replayability without becoming the main engagement strategy engine.
6. Proactive group outreach is a first-class autonomous behavior for creating attention and generating real inbound conversation surface.
7. Operators can understand both operational health and commercial traction from inside Telegram, including whether the live autonomy workers are actually running.
8. The system gets better at choosing who to engage, how to respond, and when to route without becoming brittle.
