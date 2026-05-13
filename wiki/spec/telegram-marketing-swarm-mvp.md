# Telegram Marketing Operating Mode MVP

## Purpose

Define the first operating mode that runs on top of the Telegram core platform.

This operating mode should help:

1. Discover relevant Telegram communities.
2. Decide what message and campaign angle fits each community.
3. Manage which accounts join which communities and under what pacing/risk limits.

This is not the whole product. It is the first campaign operating package built on the broader Telegram-native agent platform.

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

It should also align with [Campaign Operations Model](C:/Users/ravil/OneDrive/Desktop/tg-swarm/wiki/spec/campaign-operations-model.md), which defines the manager-versus-worker operating shape, campaign memory, work items, and scheduling model.

## MVP Scope

### In Scope

- Telegram community discovery and qualification
- Campaign strategy and message planning
- Account inventory, assignment, warm-up, pacing, and safety controls
- Campaign memory updates and durable planning continuity
- Scheduled re-review of discovery, strategy, and readiness
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
- Refresh stale discovery coverage over time and surface new opportunities

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
- Revisit positioning when new evidence changes the campaign context

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
- Maintain execution readiness and blocked-versus-ready action visibility

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

They should also operate as tactically autonomous workers under orchestrator-level strategic direction:

- the orchestrator decides what work should happen and why
- specialists decide how to execute domain work within scope
- specialists maintain tactical working memory and update shared campaign memory when findings become durable

## Planned Guardrails

The following guardrails should be part of the operating model but are not yet planned as enforced controls:

- no deceptive personas posing as unrelated third parties
- no coordinated account-to-account conversation intended to manufacture false social proof
- no posting before a community is profiled for norms and moderation risk
- no campaign activity in communities that explicitly ban promotion
- no automatic high-volume joins or writes without later-defined safety controls
- escalate ambiguous, sensitive, or high-risk communities to a human

## Operating Shape

The MVP should no longer be treated only as a one-pass linear workflow.

It should support two interacting modes:

### Setup Path

The initial setup path may still feel sequential:

1. Operator provides campaign brief.
2. The system builds the initial campaign frame.
3. Discovery establishes an initial community picture.
4. Strategy establishes an initial positioning and participation posture.
5. Account planning establishes initial readiness and constraints.

### Ongoing Operations

After setup, the campaign should operate continuously through:

- recurring discovery refresh
- strategy review and refinement
- account-readiness review
- work-item delegation across specialists
- campaign-memory updates
- operator review of significant changes

Discovery, strategy, and account planning should therefore be understood as recurring work families rather than one-time pipeline steps.

## Minimal Data Model

The MVP should persist at least these entities or their conceptual equivalents.

This should not be read as a mandate for a rigid normalized database-first implementation. File-backed campaign memory and lightweight structured metadata are acceptable as long as these concepts remain durable and retrievable.

The campaign should be the durable root object for downstream work items, schedules, approvals, assignments, and later execution records.

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
- canonical memory references

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

### `work_items`

- id
- campaign_id
- owner_role
- goal
- constraints
- priority
- status
- due_at
- related_memory_refs
- result_summary

### `schedules`

- id
- campaign_id
- schedule_type
- cadence
- owner_role
- next_run_at
- status

## MVP Success Criteria

The MVP is successful when it can:

1. Produce a ranked list of relevant Telegram communities for a campaign.
2. Produce a usable campaign/message plan for those communities.
3. Produce a safe account assignment and join plan.
4. Keep enough durable campaign state and memory that later engagement automation is possible.
5. Revisit discovery, strategy, and planning over time without restarting the campaign from scratch.

## Design Principles

- Keep the marketing mode layered on top of the Telegram core instead of baking Telegram logic directly into every workflow.
- Favor role-based autonomy over hard capability partitioning.
- Store durable campaign outputs so later operator sessions and scheduled work can reuse them.
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
