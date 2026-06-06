# Engagement Brain And Reply Policy

## Goal

Define the smallest reasoning layer that helps managed accounts choose the right next conversational move in groups and inbound-first DMs.

## North-Star Link

This workstream primarily supports:

- **Engagement**
- **Qualification**
- **Conversion Progression**

from [Campaign North Star](campaign-north-star.md).

## Why This Exists

The current specialists are built for discovery, strategy, and account planning. A live engagement MVP also needs a live conversation brain that can:

- notice when a conversation deserves a reply
- choose the simplest useful next move
- stay grounded in approved campaign context
- stop early when risk or uncertainty rises

Without this layer, the runtime can listen, store, and dispatch, but it still lacks the small amount of judgment needed to move from raw conversation events into useful campaign behavior.

At the end of the day, that useful behavior should serve one commercial objective:

- create qualified interest in groups
- progress qualified DM conversations toward buying or the next real conversion step

## Core Boundary

This workstream should stay narrow.

The intended boundary is:

- the brain proposes the next conversational move
- the safety policy allows, defers, adjusts, or blocks that proposal
- the live execution runtime dispatches allowed actions through Telegram

The brain should **not** re-decide:

- DM consent posture
- cooldown windows
- paused, blocked, or closed status
- account health
- retry or queue mechanics

That keeps this workstream focused on conversational judgment instead of turning it into a second policy or execution layer.

## Scope

- define the live-engagement reasoning contract
- define the smallest useful set of next-move decisions
- define grounding rules for business facts and uncertainty handling
- define simple behavior rules for group replies and inbound-first DMs
- define lightweight qualification, ambiguity-resolution, and escalation behavior

## Out Of Scope

- queueing, retries, or claim/dispatch mechanics
- hard policy enforcement for consent, pauses, cooldowns, or account health
- rich timing or humanization logic
- a broad lead-scoring or CRM taxonomy
- full transcript memory or analytics design

## Lean Brain Contract

The MVP brain should stay intentionally small.

Its job is:

1. look at one conversation moment
2. choose the best next conversational move
3. draft bounded text when a reply is worth making
4. resolve ambiguity smoothly when possible
5. stop or escalate only when the context is truly high-risk or high-stakes

The brain should be allowed to return:

- `reply`
- `ask_clarifying_question`
- `wait`
- `ignore`
- `escalate`

This is important because the system should not behave like every inbound event demands a reply.

Conversation success should not be defined as "being helpful" in the abstract.

For this workstream, success means:

- creating attention and interest where relevant
- progressing qualified conversations toward a commercial outcome
- doing so without damaging account health or community trust

## Input Contract

The brain should use a compact bounded context assembled from:

- campaign brief
- approved offer facts or offer artifacts
- strategy and positioning notes
- community notes
- conversation summary
- bounded recent message window

It should not depend on:

- full raw transcripts by default
- broad campaign workspace scans
- account health logic that belongs to policy
- queue state that belongs to execution

## Grounding Rule

- Keep the model grounded in approved business facts. It should answer from campaign memory and curated offer materials, not improvise policy or pricing.
- If the required fact is not present in approved materials, the brain should either:
  - ask one bounded clarifying question
  - give a limited safe response that does not invent facts
  - redirect toward a useful narrower next step
  - escalate only when the missing fact is too important to handle conversationally
- It should not bluff pricing, guarantees, legal claims, product details, or delivery promises.

## Ambiguity Handling Posture

The default MVP posture should not be blunt refusal.

When the brain hits uncertainty, it should usually try to keep the conversation moving by:

- answering the part it can answer safely
- using bounded generalities that stay consistent with approved campaign context
- asking a narrowing question
- suggesting the next useful step
- deferring specifics without sounding helpless or dismissive

The brain should avoid flat responses like:

- "no"
- "I don't know"
- "I can't help with that"

unless policy or safety truly requires a hard stop.

This is not permission to invent facts. The intended behavior is confident ambiguity handling, not fabricated certainty.

## Reasoning Modes

The brain should treat public group replies and DMs as different modes.

## Commercial Posture And Voice

The brain should not sound like a generic polite assistant.

It should sound more like a natural commercial actor with taste:

- confident
- socially aware
- selective
- persuasive without sounding needy
- commercially minded without sounding corny

The intended posture is not:

- over-helpful
- clingy
- over-explanatory
- eager-to-please
- obviously AI-assistant-like

The intended posture is closer to:

- a sharp participant in group conversations who knows how to catch attention naturally
- a commercially competent DM closer who can move a conversation toward real intent

Tone should vary by task and context. Depending on the campaign and moment, the voice may feel more like:

- a cool peer with market awareness
- a professional business marketer
- a natural salesperson with social fluency

The common rule across all three is:

- natural and cool
- never cringe
- never corny
- never desperate
- never robotic

### Group Mode

Group behavior should be:

- relevance-first
- useful before promotional
- concise
- context-aware to the community thread
- attention-aware without becoming spammy
- willing to leave the conversation alone when a reply would add little value

The goal in groups is usually:

- catch attention
- create interest
- earn a reply or DM
- create a natural path toward deeper interest

In group mode, the brain may use light expressive tactics when they fit the community and campaign:

- occasional emojis
- Telegram-native formatting
- sharper hooks or punchier one-liners
- image attachment suggestions when visual proof or style would help the post land

These tactics should be used intentionally, not constantly.

The goal is to stand out naturally, not to look loud, gimmicky, or engagement-bait driven.

### DM Mode

DM behavior should be:

- narrower
- more direct
- still grounded in approved facts
- more qualification-aware
- more conversion-aware when genuine fit appears

The goal in DMs is usually:

- answer the question clearly
- identify whether the person is a real fit
- move the conversation one useful step forward
- progress toward a buying decision or a concrete conversion step
- resolve ambiguity conversationally when possible
- escalate when the ask becomes truly high-stakes or commercially important

The brain may reason in DM mode only when the surrounding runtime already proves the inbound-first posture. That proof belongs to policy and conversation state, not to the brain itself.

## Lightweight Qualification Model

The MVP does not need a large qualification taxonomy.

The brain only needs to recognize a few practical states:

- `curious`
- `potential_fit`
- `objection_or_unclear`
- `conversion_ready`

These states are useful because they help the brain choose between:

- answering simply
- asking a clarifying question
- giving a bounded next step
- resolving ambiguity smoothly
- escalating at the right moment

## Suggested Output Shape

The brain should return a structured proposal rather than plain text alone.

Recommended fields:

- `decision`
- `action_type` when a send is proposed
- `draft_text` when a send is proposed
- `presentation_hints` for things like emoji usage, Telegram formatting, or optional media
- `goal`
- `qualification_state`
- `facts_used`
- `missing_facts`
- `risk_level`
- `resolution_strategy` when ambiguity exists
- `escalation_reason` when relevant

Optional later field:

- `timing_hint`

The output should stay at the level of a proposed conversational move, not queue or transport details.

## Integration With Neighboring Workstreams

The intended runtime flow is:

1. inbound events and conversation state identify a live conversation moment
2. the brain proposes the best next conversational move
3. policy decides whether that move is allowed now
4. live execution sends the allowed action and records the outcome

This workstream should remain compatible with the surrounding seams:

- [External Conversation State](external-conversation-state.md) owns durable thread posture and summaries
- [Safety Policy And Guardrails](safety-policy-and-guardrails.md) owns allow, defer, adjust, and block decisions
- [Live Execution Runtime](live-execution-runtime.md) owns queueing, dispatch, retries, and visible Telegram writes
- [Observation And Adaptation](observation-and-adaptation.md) owns durable write-affecting posture after outcomes

## Deliverables

- a dedicated live-engagement prompt or equivalent reasoning module
- a compact input context contract for live conversation decisions
- a structured proposal schema for next conversational moves
- optional presentation hints for Telegram-native expression and media suggestions
- clear grounding, ambiguity-resolution, and escalation rules for public replies and inbound-first DMs

## Recommended Build Order

Build this workstream in three lean slices.

### Slice 1: Decision Contract

- lock the brain boundary against policy and execution
- define the small decision set
- define the structured proposal output

### Slice 2: Grounded Reply Generation

- wire the brain to bounded campaign and conversation context
- add group and DM reasoning modes
- enforce explicit missing-fact handling

### Slice 3: Qualification And Escalation

- add the lightweight qualification states
- add ambiguity-resolution behavior for uncertain moments
- add escalation triggers for sensitive asks, high-stakes ambiguity, and conversion moments
- keep the result simple enough for operator review and testing

## Design Notes

- Keep this workstream focused on north-star performance, not reasoning complexity.
- Prefer fewer clear decisions over richer but harder-to-control taxonomies.
- Let the brain say "do nothing" when that is the best move.
- Keep business grounding stronger than stylistic creativity.
- Prefer smooth ambiguity resolution over blunt refusal by default.
- Optimize for commercial progress, not generic helpfulness.
- Keep group usefulness ahead of promotion.
- Let groups feel interesting and eye-catching without becoming loud or needy.
- Keep DM handling narrow and inbound-first.
- Reserve true operator escalation for narrower high-stakes cases.

## Acceptance Criteria

- the runtime can propose a bounded group reply from approved campaign context
- the runtime can propose a group reply that is commercially interesting, not merely helpful
- the runtime can propose a DM reply only within an inbound-first conversation path
- the runtime can suggest Telegram-native expression choices such as light emoji use, formatting, or optional media when they improve the post
- the runtime can choose `wait`, `ignore`, or `escalate` instead of forcing a reply
- fact-missing questions can trigger clarifying or narrowing behavior without inventing concrete business facts
- the brain avoids flat "no" or "I don't know" style replies when a safe conversational recovery is possible
- truly sensitive or high-stakes questions still trigger escalation instead of fabricated certainty
- the proposal output is structured enough for policy checks and execution routing
- qualification state is simple but useful for moving conversations toward real fit or human handoff

## Dependencies

- campaign memory and approved offer artifacts
- conversation state
- safety policy
- live execution runtime
