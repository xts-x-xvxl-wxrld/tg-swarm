# Operator Takeover And Closure

## Goal

Define the Telegram-native flow for marking a live conversation operator-owned, closing it cleanly, and optionally returning it to bounded automation later.

## Why This Is Separate

The runtime already has pause semantics and escalation-like signals, but takeover is a richer workflow than simple pause or blocked-send handling.

It changes who owns the next move in a conversation and therefore needs its own explicit runtime contract.

## Current Baseline

Already present in code:

- conversation-scoped pause behavior exists in the live execution layer
- conversation state, timing state, and recent activity already persist durably
- operator-facing live ops work will already exist if the earlier readiness steps land first

Missing today:

- one explicit operator-owned conversation state
- one clean closure model
- one safe hand-back flow from operator ownership into bounded automation

## Implementation Track

### Takeover

- mark a conversation as operator-owned through Telegram-native runtime flows
- stop autonomous review or execution from continuing silently after takeover
- preserve the reason and time of takeover for later audit

### Closure

- define what "closed" means for a conversation in campaign terms
- distinguish resolved, disqualified, do-not-contact, and manually parked outcomes if the first slice needs them
- make closure durable and visible in later inspection

### Return To Automation

- define the conditions under which an operator-owned conversation can be handed back safely
- reset or preserve timing and review state deliberately
- require an explicit operator action for the first cut

## Acceptance Criteria

- an operator can take ownership of a conversation without ambiguous mixed control
- closure state is durable and visible
- a safe first-cut return-to-automation path exists
- focused validation proves autonomous workers respect takeover and closure state
