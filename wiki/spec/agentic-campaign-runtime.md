# Agentic Campaign Runtime

## Purpose

Define the next highest-priority product direction for the Telegram-native runtime.

This spec describes how the system should behave when an operator provides a mixed bundle of campaign input such as freeform text, Telegram links, seed-group dumps, images, brochures, checklists, and conversion destinations.

It should be read as the source of truth for the shift from a planning-first Telegram campaign tool into an operator-facing agent harness for continuous campaign execution.

## Priority Position

This spec is the current highest-priority scope direction for the active product.

When narrower planning-era assumptions conflict with this document, this document should win.

In particular, the runtime should no longer assume that:

- campaign setup is mainly a labeled-field intake flow
- uploaded files are primarily passive context unless the operator labels them
- the operator must deterministically specify which assets are outbound marketing materials
- conversion is an implied future concern rather than a first-class campaign target
- live operations are mainly deterministic operator controls instead of an ongoing agentic loop with escalation

## Design Goal

The product should behave less like a form-driven workflow runner and more like a durable operator-facing campaign harness.

The operator should be able to say things like:

- "Here are the client files. Read them."
- "Here are some seed groups. Investigate them."
- "Leads should end up in `t.me/johndoe`."
- "Keep running until paused, broken, or out of accounts."

The system should interpret that bundle, explain its understanding, and then operate continuously with bounded autonomy.

## Core Operating Shift

The runtime should be organized around campaign interpretation and execution, not just campaign planning.

The core loop should become:

1. interpret operator input corpus
2. synthesize a campaign model
3. validate and expand discovery inputs
4. infer content, outreach, and qualification paths
5. execute and observe continuously
6. improve or escalate over time

Discovery, strategy, and account planning remain important, but they should become supporting work families inside a broader campaign runtime.

## Operator Mental Model

The operator should not need to pre-classify every input.

The operator should be able to provide mixed campaign input in natural form:

- plain text
- long unstructured notes
- Telegram usernames, invites, groups, channels, and bots
- external links
- screenshots, images, and brochures
- checklists, docs, and PDFs
- desired conversion destinations
- campaign corrections and mid-flight changes

The runtime should interpret this bundle agentically, surface its current understanding, and only ask for clarification when the ambiguity is material.

## Campaign Intent Package

The runtime should converge mixed operator input into one durable campaign intent package.

That package should include at least:

- business context
- offer summary
- target audience
- geography and language hints
- seed communities
- inferred media/material inventory
- qualification posture
- conversion target
- autonomy and escalation posture
- campaign constraints

The intent package should be durable and updateable over time as the campaign learns.

## Asset Interpretation Model

Uploaded files and images should not be treated as passive attachments by default.

The system should infer what each asset is useful for.

An asset may be useful for one or more roles:

- `campaign_context`
- `outbound_media`
- `qualification_material`
- `conversion_support`
- `proof_or_trust_signal`

The operator should still be able to override this later, but the MVP default should be orchestrator-led inference rather than operator-led deterministic labeling.

## Multi-Use Asset Principle

The same asset may be useful for more than one purpose.

For example:

- a brochure image may inform positioning and also be posted in a group
- a checklist may help the system qualify leads and also be sent in DMs
- an offer document may define both campaign context and conversion messaging

The runtime should therefore support multi-role asset availability rather than forcing one exclusive classification.

## Seed Interpretation Model

Seed communities should be accepted as mixed natural-language input rather than requiring a deterministic import format.

The operator should be able to send:

- handles
- `t.me` links
- invite links
- long pasted lists with counts and notes
- partial names
- commentary about why a group matters

The runtime should extract candidate seed communities from that corpus, normalize what it can, preserve what it cannot fully normalize yet, and then investigate them through discovery.

## Conversion Target Model

Conversion is the primary business target and must become a first-class campaign concept.

A campaign should be able to declare a conversion destination such as:

- a Telegram user DM
- a Telegram bot
- a Telegram group
- a Telegram channel
- an external website or landing page

The runtime should persist both the raw operator-provided destination and the normalized interpreted target.

## Conversion Destination Requirements

The runtime should preserve enough structure to answer:

- what successful lead routing means for this campaign
- where qualified leads should be sent
- whether the destination is internal to Telegram or external
- what action types are allowed or preferred for that destination
- what proof of conversion or handoff should be recorded

Conversion should not remain hidden inside strategy prose or operator notes only.

## Agentic Qualification Model

Lead qualification should not be a fixed global schema only.

The runtime should infer a campaign-specific qualification frame from:

- uploaded client assets
- the offer itself
- the conversion destination
- later campaign observations

That means qualification should be treated as an agentic reasoning task grounded in campaign artifacts, not just a static checklist engine.

The runtime may still persist structured qualification outputs, but the reasoning path that creates them should remain campaign-aware and adaptable.

## Continuous Autonomous Operations

The target operating mode is a continued campaign process rather than a one-pass planning session.

Once the operator confirms the campaign direction, the runtime should be able to continue until:

- the operator pauses it
- a hard blocker appears
- the campaign runs out of usable accounts or execution capacity
- a safety or policy boundary requires intervention

The runtime should keep observing, acting, qualifying, routing, and revising with bounded autonomy.

## Self-Improvement Direction

The campaign should become self-improving in a bounded operational sense.

This means the runtime should:

- learn which communities are productive
- learn which media and message angles travel best
- learn which qualification signals correlate with conversion
- detect blocked or degraded execution paths
- refresh plans and priorities over time

This does not mean unconstrained autonomous rewriting of the whole campaign after every event.

## Operator Escalation Model

The operator should be notified when the runtime needs help, not required to drive every micro-step.

Typical escalation categories should include:

- ambiguous campaign interpretation
- risky or policy-sensitive execution
- blocked conversion routing
- exhausted or unhealthy account inventory
- repeated low-yield loops
- destination failures or link breakage
- campaign contradictions discovered from new evidence

The runtime should frame these as actionable operator interventions rather than raw internal errors.

## Deterministic Versus Agentic Boundary

The system should remain agentic in interpretation and adaptive planning, but deterministic in persistence and control.

Agentic responsibilities should include:

- campaign interpretation
- asset-role inference
- qualification reasoning
- conversion-path reasoning
- next-step prioritization

Deterministic runtime responsibilities should include:

- state persistence
- queueing and execution control
- account health state
- leases, claims, retries, and dedupe
- pause and resume controls
- audit trails and operator-visible escalations

This split is important. The product should not become either:

- a rigid form system with weak reasoning, or
- a freeform agent with weak operational discipline

## Relationship To Existing Specs

This spec refines and extends:

- [Campaign Operations Model](C:/Users/ravil/OneDrive/Desktop/tg-swarm/wiki/spec/campaign-operations-model.md)
- [App Runtime Architecture](C:/Users/ravil/OneDrive/Desktop/tg-swarm/wiki/spec/app-runtime-architecture.md)
- [Telegram Marketing Operating Mode MVP](C:/Users/ravil/OneDrive/Desktop/tg-swarm/wiki/spec/telegram-marketing-swarm-mvp.md)

Those documents remain useful, but this spec clarifies the next product target:

- operator-facing mixed-input campaign intake
- orchestrator-led campaign interpretation
- first-class conversion destinations
- campaign-specific qualification
- continuous autonomous operation with operator escalation

## Success Criteria

This direction is correct when:

1. An operator can create a campaign by sending natural mixed input instead of filling a rigid structure.
2. The runtime can infer which uploaded assets are useful for context, outbound use, qualification, or conversion support.
3. Seed communities can be extracted from messy pasted input and turned into investigation targets.
4. Conversion destinations are first-class runtime objects, not just narrative notes.
5. Qualification can adapt to the actual offer and campaign evidence instead of staying globally generic.
6. The campaign can continue operating until paused, blocked, or starved of execution capacity.
7. The operator is notified when intervention is needed, rather than manually driving every step.

## Open Questions

- What is the smallest durable campaign intent package that still supports this behavior well?
- Which asset types should gain richer structural parsing first after DOCX and simple images?
- How explicit should campaign-level autonomy posture be in the first implementation cut?
- What is the first useful operator-visible summary of conversion progress for a live campaign?
