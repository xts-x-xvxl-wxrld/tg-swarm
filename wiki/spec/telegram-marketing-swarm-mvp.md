# Telegram Marketing Operating Mode MVP

## Purpose

Define the first operating mode that runs on top of the Telegram core platform.

This operating mode should help:

1. Discover relevant Telegram communities.
2. Decide what message and campaign angle fits each community.
3. Manage which accounts join which communities and under what pacing/risk limits.

This is not the whole product. It is the first workflow package built on the broader Telegram-native agent platform.

## Product Framing

This operating mode is a community operations layer.

It should optimize for:

- relevance
- account health
- community fit
- repeatable campaign execution

It should avoid:

- deceptive identity use
- fake grassroots behavior
- manufactured consensus between accounts
- posting in communities that clearly disallow promotion
- high-frequency account actions that look automated

## Relationship To The Platform

The broader platform provides:

- Telegram bot operator UI
- orchestrator/session handling
- shared Telegram capability access
- shared agent constitution

This MVP provides the first role emphasis on top of that foundation.

## MVP Scope

### In Scope

- Telegram community discovery and qualification
- Campaign strategy and message planning
- Account inventory, assignment, warm-up, pacing, and safety controls
- Community research summaries
- Community-specific campaign playbooks
- Planned approval points and safety checkpoints
- Role-based autonomy for the three primary agents

### Out of Scope

- Universal Telegram workflows outside marketing/community operations
- Final guardrail enforcement logic
- Advanced conversion attribution
- CRM synchronization
- Large-scale analytics dashboards
- Rich operator UI

## Primary Users

- Founder/operator running Telegram community marketing campaigns
- Internal marketer managing messaging experiments
- Human reviewer steering sensitive or high-risk decisions

## Core Questions

The MVP must answer these three questions well:

1. Where should we go?
2. What should we say there?
3. Which account should enter, and how carefully?

## Primary Role Emphasis

### 1. Discovery Agent

#### Responsibilities

- Find Telegram groups/channels relevant to a campaign
- Classify communities by topic, language, geography, audience type, and activity
- Score each community for relevance, accessibility, and promotional risk
- Produce a short research brief for each recommended community

#### Inputs

- campaign objective
- target audience
- niche keywords
- language/region constraints

#### Outputs

- ranked community list
- community profile records
- risk flags

### 2. Strategy Agent

#### Responsibilities

- Turn campaign goals into message angles and community-specific approaches
- Define audience segments and matching talking points
- Recommend value-first entry tactics and CTA strength
- Produce a playbook for each approved community segment

#### Inputs

- campaign brief
- discovery results
- community summaries
- brand constraints

#### Outputs

- campaign strategy brief
- message variants
- community-specific playbooks
- approval-required items

### 3. Account Manager Agent

#### Responsibilities

- Track account inventory and health
- Decide which account should join which community
- Plan warm-up rules, cooldowns, join pacing, and action limits
- Record membership state and risk events

#### Inputs

- account roster
- community approvals
- campaign priorities
- historical account activity

#### Outputs

- account-to-community assignment plan
- join queue
- safety decisions
- account health summaries

## Autonomy Model

Agents in this operating mode are not meant to be hard-boxed into narrow task capabilities.

Instead:

- they should have broad access to the Telegram platform capabilities
- they should be guided by role-specific prompts
- they should inherit shared system behavior from the platform constitution

This means the three roles define emphasis and decision-making style more than strict capability walls.

## Planned Guardrails

The following guardrails should be part of the operating model but are not yet planned as enforced controls:

- no deceptive personas posing as unrelated third parties
- no coordinated account-to-account conversation intended to manufacture false social proof
- no posting before a community is profiled for norms and moderation risk
- no campaign activity in communities that explicitly ban promotion
- no automatic high-volume joins or writes without later-defined safety controls
- escalate ambiguous, sensitive, or high-risk communities to a human

## End-to-End MVP Workflow

### Workflow A: Discovery

1. Operator provides campaign brief.
2. Discovery Agent finds candidate communities.
3. Discovery Agent scores and summarizes each one.
4. Human or orchestrator approves a shortlist, if approvals are required by the eventual guardrail layer.

### Workflow B: Strategy

1. Strategy Agent reads the campaign brief and community shortlist.
2. Strategy Agent groups communities into segments.
3. Strategy Agent writes message angles and community-specific participation guidance.
4. Human reviews the initial playbook when appropriate.

### Workflow C: Account Planning

1. Account Manager reads the approved shortlist and strategy guidance.
2. Account Manager selects appropriate accounts for each community.
3. Account Manager creates a join/warm-up plan with timing constraints.
4. System records assignments and monitors account safety.

## Minimal Data Model

The MVP should persist at least these entities or their conceptual equivalents:

### `campaigns`

- id
- name
- objective
- target audience
- offer
- geography
- language
- constraints
- success criteria
- status

### `communities`

- id
- telegram handle or invite link
- type (`group` or `channel`)
- topic
- language
- geography
- audience description
- member count if available
- activity score
- promo tolerance
- moderation risk
- notes

### `community_profiles`

- id
- community_id
- summary
- norms
- common topics
- likely acceptable angles
- likely unacceptable angles
- evidence/source notes
- last_reviewed_at

### `accounts`

- id
- display name
- phone/session reference
- account age bucket
- trust status
- warm_up_status
- last_action_at
- risk_score
- notes

### `account_community_assignments`

- id
- account_id
- community_id
- campaign_id
- assignment_status
- join_status
- first_observed_at
- joined_at
- first_post_planned_at
- cooldown_until

### `strategy_playbooks`

- id
- campaign_id
- community_id or segment_id
- positioning
- allowed talking points
- banned talking points
- CTA style
- approval_status

## MVP Success Criteria

The MVP is successful when it can:

1. Produce a ranked list of relevant Telegram communities for a campaign.
2. Produce a usable campaign/message plan for those communities.
3. Produce a safe account assignment and join plan.
4. Keep enough structured state that later engagement automation is possible.

## Design Principles

- Keep the marketing mode layered on top of the Telegram core instead of baking Telegram logic directly into every workflow.
- Favor role-based autonomy over hard capability partitioning.
- Store structured outputs so later operator sessions and workflows can reuse them.
- Treat guardrails as planned controls even before they are enforced.

- Keep agent roles narrow and legible.
- Separate read-heavy workflows from write-heavy workflows.
- Require structured outputs, not just chat responses.
- Favor human review at community entry and first-message stages.
- Optimize for account longevity over short-term reach.

## Open Questions

- What exact Telegram interface will power execution: browser automation, Telegram client library, or both?
- How many accounts should the MVP assume?
- Will communities be discovered only from Telegram, or also from web search and directory sources?
- What is the primary conversion outcome: clicks, leads, signups, or direct conversations?
