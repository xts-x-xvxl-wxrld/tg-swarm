# Next Session Prompt: Remove Operator Message Review

Use this prompt at the start of the next coding session.

---

You are continuing work in `C:\Users\ravil\OneDrive\Desktop\tg-swarm`.

Read first:

1. `AGENTS.md`
2. `wiki/index.md`
3. `wiki/code-index/index.md`
4. `wiki/code-index/engagement-brain.md`
5. `wiki/code-index/live-execution.md`
6. `wiki/plan/engagement-machine-readiness/autonomous-send-approval-alignment.md`
7. `wiki/plan/engagement-machine-readiness/telegram-live-ops-surface.md`

## Mission

Remove all operator message-review requirements from the live engagement runtime.

The desired behavior is:

- if the system produces a grounded message proposal
- and that proposal is approved by the runtime's own bounded authorization rules
- and normal execution-time policy allows it
- then the message should be allowed to send everywhere that the current live engagement runtime supports

This means the system should no longer create or depend on operator review for individual message sends.

## Important Product Direction

Treat the current `review_required` / `pending_autonomous_review_id` / review-needed message-send path as a transitional implementation that now needs to be removed.

The new desired posture is:

- no operator review for message sends
- no manual-only campaign posture for supported message send families
- system-approved messages should flow directly into the normal live execution path
- campaign context, conversation context, and execution-time safety policy must still remain strict

Do not weaken:

- DM inbound-first policy
- paused / blocked / escalated conversation stops
- account cooldown / flagged / banned checks
- community risk pauses
- MTProto explicit approved-send requirements

The simplification is about removing human approval for message sends, not about removing safety or grounding.

## Concrete Implementation Goals

Implement the following:

1. Remove operator review as a runtime requirement for supported message sends.
2. Remove or bypass `REVIEW_REQUIRED` for `send_group_reply` and `send_dm_reply`.
3. Make the autonomous-send seam return explicit approved-send context for supported grounded sends by default.
4. Ensure all system-approved supported messages can pass through queue admission and dispatch without requiring any operator review state.
5. Remove stale review-needed conversation linkage and message-level review records when they are no longer part of the runtime path.
6. Tighten MTProto send approval so it relies on structured approved-send context rather than a vague boolean, but still accepts the system-approved autonomous path.

## Scope To Change

Expect to touch at least:

- `telegram_app/autonomous_send/`
- `telegram_app/engagement_brain/coordinator.py`
- `telegram_app/engagement_brain/models.py`
- `telegram_app/external_conversations/models.py`
- `telegram_app/external_conversations/manager.py`
- `telegram_app/capabilities/mtproto/impl_messaging.py`
- `telegram_app/live_execution/service.py`
- `server.py`
- focused tests under `tests/`

## Required Structural Outcome

After this change, the runtime decision order for supported message sends should be:

1. engagement brain proposes a message
2. autonomous-send authorization verifies it is grounded and supported
3. authorization stamps explicit approved autonomous send context
4. live-execution policy decides whether it may execute now
5. MTProto capability performs the send only when the structured approval context is present

There should be no operator review branch in the middle for normal supported sends.

## What To Remove Or Collapse

Remove or collapse these concepts for supported message sends:

- `manual_only` posture as a gating mechanism for reply-path sends
- `review_required` run disposition for reply-path sends
- `pending_autonomous_review_id` as a required operator workflow for message sends
- durable review-needed records for normal supported sends
- any Telegram live-ops dependency on approving individual message drafts

If a message is unsupported or ungrounded, it may still be blocked.

If a message is grounded and supported, it should not wait for a human.

## Docs To Update

Update the docs to match the new direction:

- `wiki/plan/engagement-machine-readiness/autonomous-send-approval-alignment.md`
- `wiki/plan/engagement-machine-readiness/telegram-live-ops-surface.md`
- any relevant code-index notes
- `wiki/log.md`

The docs should clearly say:

- operator review for individual message sends is no longer part of the target runtime
- live ops should focus on pause/resume, status, and inspection, not per-message approval

## Validation

Add or update focused tests that prove:

- grounded DM replies send without operator review
- grounded group replies send without operator review
- execution-time policy still blocks paused / invalid / consent-violating sends
- MTProto still requires explicit structured approved-send context
- no stale operator-review state is required for supported autonomous message sends

Run the smallest relevant test set and report what passed.

## Final Delivery Expectations

When done:

- summarize the code changes
- summarize the behavior changes
- call out any remaining deferred work
- be explicit about whether any old operator-review code paths still remain in the runtime

---

Use the repo's existing seams. Prefer simplifying the current implementation over layering a second approval model on top of it.
