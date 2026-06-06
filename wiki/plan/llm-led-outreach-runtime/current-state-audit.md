# Current State Audit

## Goal

Record what the repo already supports, what is partially there, and what still blocks the target LLM-led outreach architecture.

## What Is Already Landed

### Inbound Event Capture

The runtime already has a dedicated inbound managed-account seam:

- [telegram_app/engagement/listener.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/engagement/listener.py)
- [telegram_app/engagement/storage.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/engagement/storage.py)
- [telegram_app/engagement/models.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/engagement/models.py)

This means inbound events are already normalized, deduped, persisted, and available for later reasoning.

### Campaign-Linked Conversation Projection

The runtime already projects inbound events into durable conversation records:

- [telegram_app/external_conversations/projector.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/external_conversations/projector.py)
- [telegram_app/external_conversations/manager.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/external_conversations/manager.py)
- [telegram_app/external_conversations/models.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/external_conversations/models.py)

This means conversation identity, consent posture, next action, qualification summary, and follow-up timing already have a real persistence seam.

### Review Dispatch And Live Execution Bridge

The runtime already has:

- a background review dispatcher in [telegram_app/engagement_brain/review_dispatcher.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/engagement_brain/review_dispatcher.py)
- a coordinator bridge in [telegram_app/engagement_brain/coordinator.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/engagement_brain/coordinator.py)
- autonomous authorization in [telegram_app/autonomous_send/service.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/autonomous_send/service.py)
- deterministic execution policy and queueing in [telegram_app/live_execution/](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/live_execution)

This means the repo already has the right top-level control flow shape for a promoted-thread reasoning machine.

### Separate Model Routing Seam

The repo already supports separate model roles in [telegram_app/llm/model_selection.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/llm/model_selection.py).

That seam already includes a cheaper `summary` role, so the low-cost inbound tier does not need a new model-selection mechanism.

### Evidence Continuity

The evidence-foundation slice is now largely landed:

- outbound reply-matching records persist message text plus lightweight asset refs
- engagement-brain context rebuilding can resolve recent outbound continuity
- queued live actions preserve enough context to keep later review grounded

The main remaining gap is not blank outbound continuity anymore. It is whether the evidence surface is rich enough for broader proactive outreach and campaign-level learning loops.

### Two-Stage Review And Belief State

The runtime now has the core two-stage review shape:

- cheap first-pass triage in [telegram_app/engagement_triage/](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/engagement_triage)
- promoted-thread commercial reasoning in [telegram_app/engagement_brain/service.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/engagement_brain/service.py)
- durable `triage_state` and `belief_state` persistence in [telegram_app/external_conversations/models.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/external_conversations/models.py)

This means the older "cheap triage is still missing" and "belief state is still missing" conclusions are no longer accurate.

### Commercial Momentum Visibility

The runtime now persists opportunity and yield signals and surfaces compact traction summaries through:

- [telegram_app/campaign_signals/](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/campaign_signals)
- [telegram_app/continuous_ops/](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/continuous_ops)
- [telegram_app/live_ops/](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/live_ops)

That means the repo now has first-class answers for conversion-ready pressure, unresolved high-opportunity threads, and high-yield accounts or communities, even if those summaries are still compact.

## Out Of Scope For This Series

This outreach-runtime series now focuses on behavior and reasoning quality.

Broader control-plane concerns such as:

- phrase-gated operator control
- fixed work-family ontology
- marker-first runtime contracts
- open-ended typed intent compilation
- schedule and work extensibility as a general runtime principle

no longer belong here as primary design scope.

Those concerns should now be read through:

- [Freeform-To-Structured Compilation](../../spec/freeform-to-structured-compilation.md)

## Main Blocking Truth

The repo already has most of the major deterministic seams and most of the LLM-led review stack that this plan originally called for.

The next blockers for this series are now mostly behavior blockers:

1. preserving richer campaign and thread evidence
2. keeping cheap review and deeper commercial reasoning aligned
3. deepening belief-state continuity over time
4. expanding commercial momentum visibility and prioritization quality
