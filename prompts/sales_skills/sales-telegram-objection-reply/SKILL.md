---
name: sales-telegram-objection-reply
description: "Writes ready-to-send Telegram replies to common sales objections in TG Swarm conversations. Use when a prospect pushes back with not interested, bad timing, already using something, too expensive, or similar resistance. Do NOT use for aggressive rebuttals, closing pressure, or unsupported persuasion."
argument-hint: "[exact objection, conversation goal, offer context, and any claim or tone constraints]"
license: MIT
version: 0.1.0
tags: [sales, telegram, objections, replies, tg-swarm]
---

# Write Telegram Objection Replies

Write the actual Telegram reply to an objection.

Produce the next sendable message.

## Runtime Assumptions

Use:
- the exact objection text if available
- the conversation history
- campaign voice and response posture
- approved claims only
- any live safety or escalation rule

If the objection is explicit and firm, respect it.
Do not force the thread forward when the clean move is to back off.

## Objective

Respond in a way that:
- acknowledges the pushback
- lowers pressure
- keeps dignity on both sides
- preserves the thread if appropriate
- exits cleanly if needed

## Core Principles

- Acknowledge before reframing.
- Keep replies shorter than the objection unless context demands more.
- Avoid sounding trained or formulaic.
- Do not argue.
- Do not "overcome" every objection.
- Treat many objections as routing signals, not persuasion opportunities.

## Supported Objection Types

### not_interested
Goal:
- test whether to soften, clarify once, or exit

### bad_timing
Goal:
- respect timing and reduce pressure

### already_using_something
Goal:
- avoid displacement talk unless invited

### too_expensive
Goal:
- do not defend price too early
- shift to fit or relevance if appropriate

### send_info
Goal:
- avoid dumping generic info
- offer one short useful piece instead

### vague_pushback
Goal:
- clarify once, lightly, if thread warmth justifies it

## Reply Patterns

### Soft clarify
Use when the objection may reflect low context rather than true rejection.

### Light reframe
Use when one cleaner framing could help.

### Graceful retreat
Use when the objection is clear and pushing further would degrade the conversation.

## Hard Bans

Do not write:
- "I completely understand, but..."
- "The reason you feel that way is..."
- "Most people say that at first"
- "Can I ask why?"
- "What if I told you..."
- "This won't take much of your time"

Do not:
- pile on proof
- rebut point by point
- defend features the recipient did not challenge
- create urgency to rescue the thread
- sneak a calendar ask into a rejection reply

## Decision Rule

If the objection is strong and specific:
- prefer graceful retreat or one low-pressure clarification

If the objection is soft and the thread is warm:
- one short clarify or reframe is acceptable

If the objection mentions timing:
- reduce the ask and leave the door open

If the objection mentions current solution:
- acknowledge and avoid competitive pressure unless invited

## Output Format

Return exactly:

PRIMARY_DRAFT:
<ready-to-send Telegram objection reply>

ALTERNATE_DRAFT_A:
<sendable softer version>

ALTERNATE_DRAFT_B:
<sendable version that preserves optional next step>

DRAFT_NOTES:
- objection_type: not_interested|bad_timing|already_using_something|too_expensive|send_info|vague_pushback
- tactic: soft_clarify|light_reframe|graceful_retreat
- pressure_level: low|very_low
- risk_flags: [short list or empty]

## Quality Bar

A good objection reply should:
- sound calm
- sound unbothered
- not feel like a script
- leave the recipient feeling respected
- avoid damaging the thread for later
