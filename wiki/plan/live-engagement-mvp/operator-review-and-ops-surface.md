# Operator Review And Ops Surface

## Goal

Provide the smallest operator-facing controls needed to supervise and intervene in a live engagement system from Telegram.

## North-Star Link

This workstream primarily supports this operating principle from [Campaign North Star](campaign-north-star.md):

- **Human Escalation At The Right Moments**

It also protects the campaign's ability to keep moving from engagement into real conversion work without losing control.

## Why This Exists

Even an autonomous MVP still needs operator visibility. Without minimal ops controls, the system may act correctly in theory but become impossible to trust in practice.

## Scope

- queue and conversation inspection
- pause or resume controls
- escalation review
- account-health inspection
- basic live-engagement summaries

## Deliverables

- operator commands or conversational surfaces for live engagement status
- views for active conversations, paused conversations, and escalations
- per-account health and recent action summaries
- campaign-level pause and account-level pause controls

## Minimum Useful Operator Actions

- inspect active live conversations for a campaign
- inspect current account health and recent rate-limit events
- pause or resume live engagement for a campaign
- pause or resume one managed account
- approve or reject higher-risk live actions when policy requires it
- mark a conversation as operator-owned or closed

## Acceptance Criteria

- the operator can pause live engagement without editing runtime files
- the operator can see why a conversation was escalated or blocked
- the operator can inspect recent live outcomes per account
- campaign-level live engagement can be stopped cleanly during incidents

## Dependencies

- execution runtime
- observation and adaptation
- account registry and audit data
