---
name: sales-telegram-outbound-draft
description: "Writes ready-to-send Telegram outbound messages for TG Swarm campaigns. Use when the runtime needs a first DM or a first proactive Telegram message. Do NOT use for email, LinkedIn, call scripts, generic copy coaching, or long-form strategy."
argument-hint: "[campaign context, recipient context, message goal, and any tone or claim constraints]"
license: MIT
version: 0.1.0
tags: [sales, telegram, outbound, drafting, tg-swarm]
---

# Write Telegram Outbound Messages

Write the actual outbound Telegram message for runtime use.

Produce message copy that can be sent with little or no editing.

## Runtime Assumptions

Use runtime context first:
- `campaign_context_data`
- `voice_profile`
- `approved_claims`
- `forbidden_claims`
- `community` or `conversation` context
- `response_posture`
- any live execution or safety notes

If context is incomplete, make the safest reasonable assumption and write the draft anyway.
Do not block on missing details unless the message would risk making unsupported claims.

## Objective

Write a Telegram-native first-touch message that:
- sounds human
- feels context-aware
- does not read like a template
- makes a small ask
- avoids pressure
- stays inside approved campaign claims

## Telegram Writing Rules

- Plain text only unless formatting is explicitly requested.
- No subject lines.
- No email-style greeting/signoff pair.
- No long intro about who we are.
- No walls of text.
- Prefer 1 to 4 short paragraphs or message lines.
- One main idea per message.
- Keep punctuation natural and light.
- Do not use em dashes.
- Do not use emojis unless campaign voice clearly allows them.
- Do not use fake urgency.
- Do not sound like an SDR, recruiter bot, or agency template.

## Message Shape

Default shape:
1. quick contextual opener
2. one relevant observation, problem, or value frame
3. one small low-pressure ask

Good ask types:
- reply with interest
- permission to send one example
- permission to explain briefly
- narrow yes/no fit check

Avoid defaulting to:
- asking for a call immediately
- asking multiple questions
- giving a full product pitch
- stacking proof, CTA, and urgency in one message

## Openers

Use only one opener style.

### Context opener
Use when there is a real trigger or relevant context.

Example shape:
"Saw your thread about ..."
"Noticed you're working on ..."
"You mentioned ..."

### Fit-check opener
Use when context is limited but audience fit is still clear.

Example shape:
"Random one, but this may actually be relevant if you're still working on ..."
"Bit direct, but are you still focused on ..."

### Value opener
Use when the core value can be stated simply without hype.

Example shape:
"We've been helping teams tighten ..."
"I have a simple angle on ..."

## Hard Bans

Do not write:
- "Hope you're well"
- "Just following up" in a first message
- "Quick question"
- "Wanted to reach out"
- "I came across your profile"
- "Would love to connect"
- "Book a call"
- "15 minutes on the calendar?"
unless the runtime context explicitly calls for that style

Do not use:
- exaggerated familiarity
- corporate filler
- inflated proof
- unsupported numbers
- manipulative scarcity

## Output Format

Return exactly:

PRIMARY_DRAFT:
<ready-to-send Telegram message>

ALTERNATE_DRAFT_A:
<ready-to-send Telegram message with a different opener angle>

ALTERNATE_DRAFT_B:
<ready-to-send Telegram message with a different CTA or framing>

DRAFT_NOTES:
- opener_style: context|fit_check|value
- cta_style: reply_check|permission_to_send|soft_interest|direct_fit_check
- risk_flags: [short list or empty]
- claim_usage: [approved claim ids used, or "none"]

## Quality Bar

A good draft should:
- feel like a real Telegram message
- be readable in under 10 seconds
- make the recipient feel understood, not processed
- leave room for an easy response
- avoid sounding polished in a bad way

## Example Tone

Target tone:
- direct
- calm
- peer-level
- useful
- low-pressure

Not:
- ad-like
- startup-bro
- overly warm
- performative
- too clever
