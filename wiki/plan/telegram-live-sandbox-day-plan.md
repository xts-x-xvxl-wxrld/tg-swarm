# Telegram Live Sandbox Day Plan

## Purpose

Run the strongest practical same-day live test for the Telegram-native runtime without touching real customer groups or production accounts.

This plan is intentionally optimized for one working day. It does not try to prove every long-horizon behavior. It tries to prove that the active runtime can:

- operate against real Telegram instead of stubs
- onboard and use managed accounts
- read, plan, approve, and execute inside a private sandbox
- survive common operator and worker-control scenarios
- surface enough evidence to decide whether a narrow beta is justified

For a repeatable human-evaluation pass, pair this runbook with [Testing Group Mock Campaign Scenario](testing-group-mock-campaign.md). That packet adds a realistic offer, tester roles, business-logic checks, and a writing-quality rubric on top of the transport and worker checks in this document.

## One-Day Outcome

By the end of the day we should have evidence for all of these:

1. The operator bot can run a normal campaign session over real Telegram transport.
2. Telethon-backed account onboarding works through `/addaccount`.
3. Discovery and planning can use live Telegram reads.
4. Managed-account workers can ingest inbound events and queue live actions.
5. Reply and approval paths work in a private sandbox group and DM.
6. Pause/resume, review approval, and blocked-state inspection work from chat.
7. Runtime logs and monitoring artifacts are sufficient to debug failures.

## Ground Rules

- Use a separate sandbox bot token and separate sandbox user accounts only.
- Use private groups, private DMs, and optional private channels that we control.
- Do not touch real customer groups or production operator sessions.
- Do not intentionally provoke Telegram anti-abuse systems by spamming joins or sends.
- Start the day with reply posture in manual mode and only expand autonomy after the manual path passes.
- Treat one-day testing as a launch gate, not as a warmup account growth strategy.

## Sandbox Topology

Prepare this sandbox before launch testing starts:

- 1 operator Telegram account
- 1 sandbox bot for the operator control surface
- 3 managed sandbox user accounts onboarded through `/addaccount`
- 2 private groups that we control
- 1 optional private channel for read-only discovery/profile checks
- 2 human testers or secondary accounts that can act as inbound participants

Recommended role split:

- `account_a`: default read account and first reply account
- `account_b`: second managed account for joins and alternate replies
- `account_c`: spare account used only if one account hits a cooldown or onboarding problem

## Runtime Shape To Launch

Run these processes against the same sandbox state root:

1. polling app
2. engagement listener
3. scheduler
4. live executor
5. conversation reviewer
6. optional FastAPI server for monitoring endpoints only

The repo now includes a helper launcher for this at `bin/live-sandbox.ps1`.

## Required Environment

Set these before starting any role:

- `ANTHROPIC_API_KEY`
- `DEFAULT_MODEL`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_API_ID`
- `TELEGRAM_API_HASH`

Recommended:

- `SUMMARY_MODEL`
- `TG_SWARM_MONITORING_API_KEY`

The launcher sets these automatically for the sandbox:

- `TELEGRAM_CAPABILITY_BACKEND=telethon`
- `TELEGRAM_RUNTIME_STATE_DIR`
- `TG_SWARM_DATA_DIR`
- `TG_SWARM_MONITORING_DIR`

## Quick Start Commands

Open five terminals in the repo root and run:

```powershell
powershell -ExecutionPolicy Bypass -File .\bin\live-sandbox.ps1 -Role poll
powershell -ExecutionPolicy Bypass -File .\bin\live-sandbox.ps1 -Role listener
powershell -ExecutionPolicy Bypass -File .\bin\live-sandbox.ps1 -Role scheduler
powershell -ExecutionPolicy Bypass -File .\bin\live-sandbox.ps1 -Role executor
powershell -ExecutionPolicy Bypass -File .\bin\live-sandbox.ps1 -Role reviewer
```

Optional sixth terminal for monitoring endpoints:

```powershell
powershell -ExecutionPolicy Bypass -File .\bin\live-sandbox.ps1 -Role api -Port 8080
```

If you want a separate state root for a specific run:

```powershell
powershell -ExecutionPolicy Bypass -File .\bin\live-sandbox.ps1 -Role poll -SandboxName june1-dryrun
```

## Day Schedule

### Phase 0: Environment Bring-Up (45 minutes)

Objective:

- all roles start cleanly
- sandbox directories are isolated
- operator bot responds
- at least one managed account can be onboarded

Checklist:

- Start the polling app.
- Send `/start`.
- Send `/accounts` and confirm the empty-or-current account inventory makes sense.
- Run `/addaccount` and onboard `account_a`.
- Repeat for `account_b`.
- Start listener, scheduler, executor, and reviewer.
- Start the optional API server if you want `/ops/monitoring/*`.

Pass criteria:

- no startup crash loops
- `/addaccount` succeeds for at least two sandbox accounts
- `/accounts` shows real account ids and health

### Phase 1: Live Read And Planning Smoke (60 minutes)

Objective:

- prove the control brain works over real Telegram reads before we test writes

Operator flow:

1. Send `/new` with a sandbox campaign goal.
2. Ask for community discovery against the private sandbox groups or optional read-only channel.
3. Ask follow-up questions that require recent-message reads and profile checks.
4. Ask for a cautious engagement plan grounded only in the sandbox spaces.

Suggested starter prompt:

```text
/new Goal: Test our Telegram campaign runtime safely in a private sandbox. Use our private sandbox groups as targets, profile the communities, and prepare a cautious engagement plan.
```

If you want this phase to test commercial judgment and reply quality instead of pure infrastructure, use the more detailed `BriefBridge` starter prompt from [Testing Group Mock Campaign Scenario](testing-group-mock-campaign.md).

Pass criteria:

- discovery uses live community evidence, not stub-only fallback
- strategy output stays grounded in the sandbox communities
- no session continuity breaks between turns

### Phase 2: Lock Down Reply Posture (15 minutes)

Objective:

- keep the first write tests manual and observable

Send these operator messages after the campaign exists:

```text
Set DM replies to manual.
Set group replies to manual.
Pause campaign.
Show live status.
```

Why:

- DM and group reply posture starts conservative
- the campaign remains paused until we are ready to test execution deliberately

Pass criteria:

- live status reflects the campaign and shows reply posture/control state coherently

### Phase 3: Controlled Write Path (90 minutes)

Objective:

- prove the deterministic write path works with real Telegram accounts

Tests:

1. Resume the campaign.
2. Execute one low-risk sandbox join with `account_b`.
3. Trigger one sandbox group reply candidate by having a tester post in the private group.
4. Trigger one sandbox DM reply candidate by having a tester message a managed account.
5. Inspect pending reviews from the operator chat.
6. Approve one review and dismiss one review.

Suggested operator prompts:

```text
Resume campaign.
Show pending autonomous reviews.
Approve that review review-...
Dismiss that review review-...
What is blocked right now?
```

Pass criteria:

- inbound events reach the conversation state
- pending reviews appear when posture is manual-only
- approved review becomes a queued or executed live action
- dismissed review clears cleanly

### Phase 4: Live Ops Controls And Recovery (60 minutes)

Objective:

- prove the operator can regain control quickly when something looks off

Tests:

1. Pause one conversation and verify no further action executes there.
2. Resume that conversation.
3. Pause one account and verify the system stops using it.
4. Resume the account.
5. Pause the whole campaign and verify execution stops.
6. Resume the campaign.

Suggested prompts:

```text
Pause conversation conv-...
Resume conversation conv-...
Pause account account_...
Resume account account_...
Pause campaign.
Resume campaign.
Show me what needs attention.
Why is this blocked?
```

Pass criteria:

- pause and resume commands take effect predictably
- blocked reasons are explainable from chat
- no duplicate send behavior appears after resume

### Phase 5: Worker Restart Drill (30 minutes)

Objective:

- prove the day-one stack is operationally survivable

Procedure:

1. Stop the executor process while there is either no work or one known pending action.
2. Restart the executor.
3. Stop the reviewer.
4. Restart the reviewer.
5. Confirm the app continues processing without duplicate visible sends.

Pass criteria:

- restarting one worker does not corrupt campaign state
- pending items remain visible or resume correctly
- no duplicate visible Telegram messages are produced

## What We Intentionally Do Not Test In One Day

- high-volume outreach
- real-customer communities
- aggressive join-rate experiments
- intentional Telegram rate-limit or ban provocation
- long-horizon schedule behavior over multiple days

Those should wait until this private sandbox passes cleanly.

## Stop-Ship Conditions

Do not move toward a beta if any of these remain unresolved:

- managed accounts cannot onboard reliably
- discovery still behaves mostly like stub mode
- visible sends can happen without structured approval or review
- pause and resume controls are inconsistent
- worker restarts produce duplicate sends
- account health or cooldown state becomes confusing to the operator

## Evidence To Capture

Save these artifacts from the sandbox root after the run:

- `state/`
- `data/campaigns/`
- `monitoring/`

If the optional API server is running, also capture:

- `/ops/monitoring/status`
- `/ops/monitoring/summary`
- `/ops/monitoring/alerts`

## Exit Decision

At the end of the day, make one of these calls:

1. `Ready for narrow beta`
   The full read -> review -> controlled write loop worked in the sandbox and failures were understandable.

2. `Needs one more sandbox pass`
   Core behavior mostly worked, but one or two operational seams need fixes before exposure to real groups.

3. `Not launchable`
   Account onboarding, control integrity, or execution safety failed in a way that makes real-world testing too risky.
