---
name: sales-telegram-followup-draft
description: "Writes ready-to-send Telegram follow-up messages for stalled or unanswered outreach in TG Swarm. Use when an earlier Telegram message got no reply or the thread cooled off. Do NOT use for first-touch outbound, non-Telegram channels, or hard objection handling after a clear rejection."
argument-hint: "[prior message context, elapsed time, current thread state, and desired next step]"
license: MIT
version: 0.1.0
tags: [sales, telegram, followup, drafting, tg-swarm]
---

# Write Telegram Follow-Ups

Write the next Telegram follow-up message for runtime use.

Produce the next sendable message.

## Runtime Assumptions

Read and respect:
- prior outbound or reply text
- thread history
- campaign voice constraints
- approved claims
- any community or conversation sensitivity
- conversation timing signals

If the previous message already made a strong ask, reduce pressure in the follow-up.
If engagement is low, make the next step smaller, not bigger.

## Objective

Write a follow-up that earns its place in the thread by adding something new.

A follow-up must introduce at least one of:
- a new framing
- a new example
- a clearer fit-check
- a smaller ask
- a simpler explanation
- a graceful close-the-loop move

## Telegram Follow-Up Rules

- Shorter is usually better.
- Sound like one person nudging another, not a sequence engine.
- Do not repeat the prior message with minor wording changes.
- Do not guilt the recipient for not replying.
- Do not create fake urgency.
- Do not push for a call unless the thread is already warm.
- Keep line count tight.

## Follow-Up Types

### Reframe follow-up
Use when the first message may have framed the value poorly.

### Example follow-up
Use when one concrete example can make the offer easier to understand.

### Smaller-ask follow-up
Use when the first CTA was too heavy.

### Close-the-loop follow-up
Use when the thread is cold and continued pursuit would feel noisy.

## Hard Bans

Do not write:
- "just bumping this"
- "just following up"
- "checking in on this"
- "wanted to circle back"
unless the sentence immediately adds a real new angle

Do not write follow-ups that:
- repeat the same value prop
- ask multiple new questions
- become longer than the first message without a good reason
- escalate pressure after silence

## Output Logic

Choose one follow-up type based on the thread:
- no reply and weak context -> smaller ask
- no reply and strong context -> reframe or example
- partial interest but no action -> clarify or simplify
- repeated silence -> close the loop

## Output Format

Return exactly:

PRIMARY_DRAFT:
<ready-to-send Telegram follow-up>

ALTERNATE_DRAFT_A:
<sendable follow-up using a different angle>

ALTERNATE_DRAFT_B:
<sendable close-the-loop or lighter-pressure version>

DRAFT_NOTES:
- followup_type: reframe|example|smaller_ask|close_loop
- what_is_new: <short phrase>
- cta_style: reply_check|permission_to_send|light_clarifier|close_loop
- risk_flags: [short list or empty]

## Quality Bar

A good follow-up should:
- feel earned
- feel lighter than a typical sales follow-up
- give the recipient an easy way to respond
- preserve future thread quality even if they say no
