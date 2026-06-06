# Operator Notifications And Recovery

## Goal

Define how the runtime reports problems and requests intervention once campaigns are operating continuously.

## Core Problem

The target product asks the operator to intervene when:

- something breaks
- something becomes ambiguous
- a critical resource runs out

That requires a clearer operator notification and recovery model than the repo currently exposes.

## Important Notification Families

- campaign interpretation ambiguity
- repeated low-yield loops
- account exhaustion or rate limiting
- blocked conversion routing
- destination failures
- policy-sensitive moments
- stale or conflicting campaign assets

## First Questions To Lock

- which failures should interrupt immediately versus batch into status summaries
- how much context a Telegram alert should include
- how recovery actions are acknowledged and resumed
- how repeated alerts are deduped or throttled

## Expected Deliverables

- one small taxonomy of operator intervention events
- compact operator-facing alert copy
- recovery-state persistence so the runtime knows what has already been surfaced
- later compatibility with live-ops inspection and pause/resume controls
