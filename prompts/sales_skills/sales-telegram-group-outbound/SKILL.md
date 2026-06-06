---
name: sales-telegram-group-outbound
description: "Writes ready-to-send Telegram group outbound posts for TG Swarm when the runtime is initiating a message in a public or semi-public group. Use when the campaign wants to make a first post into a group, start a lightweight conversation, or test a value-led angle in-room. Do NOT use for DM outreach, direct objection handling, thread replies, or hard promotional drops."
argument-hint: "[group context, campaign goal, offer relevance, and tone or claim constraints]"
license: MIT
version: 0.1.0
tags: [sales, telegram, group-outbound, community, tg-swarm]
---

# Write Telegram Group Outbound Posts

Write the actual outbound message that will be posted into a Telegram group by the runtime.

This is a public-first drafting surface.
Produce sendable Telegram copy.

## Runtime Assumptions

Use runtime context first:
- `campaign_context_data`
- `voice_profile`
- `approved_claims`
- `forbidden_claims`
- `community` context
- `community_risk_level`
- `promo_tolerance`
- `response_posture`
- any campaign or execution safety constraints

If the group context suggests low promo tolerance, default to contribution-first messaging.
If the runtime context does not support a safe public post, output a no-send recommendation in `DRAFT_NOTES` and keep the draft extremely conservative.

## Objective

Write a Telegram group post that:
- feels native to the room
- contributes value immediately
- does not read like an ad
- creates light engagement if possible
- protects account reputation
- stays within approved campaign claims

## What This Surface Is For

Use this surface when the runtime wants to:
- make a first useful post into a relevant group
- test a conversation-starting angle
- share a short observation, tip, or question that fits the room
- invite lightweight discussion without forcing a pitch
- softly surface relevance without making the group feel harvested

This is not for:
- hard selling
- dumping full offer descriptions
- posting links by default
- aggressive lead capture
- generic introduction posts with no room relevance

## Telegram Group Writing Rules

- Plain Telegram-style text only unless context explicitly supports formatting.
- No subject lines.
- No email-style structure.
- No signatures.
- No corporate intro.
- No long paragraphs.
- Prefer 2 to 6 short message lines.
- The first line must feel relevant to the room.
- The message must stand on its own as useful even if nobody converts.
- Avoid exclamation points unless community tone clearly uses them.
- Do not use emojis unless the room tone naturally supports them.
- Do not use em dashes.
- Do not sound polished in a salesy way.

## Core Principle

A public group outbound post must earn the right to exist in the room.

That means at least one of these must be true:
- it shares a useful observation
- it names a real problem the room already cares about
- it offers a small concrete example
- it asks a genuinely relevant question
- it contributes to an active group theme

If none of those are true, do not force the post.

## Post Modes

Choose one mode only.

### 1. Contribution-first
Best default.
Lead with something useful or specific to the room.

Good for:
- medium or low promo tolerance groups
- first posts from an account
- communities where trust must be earned slowly

### 2. Question-led
Lead with a narrow, relevant, non-lazy question.

Good for:
- active discussion groups
- communities that respond well to peer exchange
- situations where the runtime wants lightweight engagement signals

The question must be real.
Do not ask fake engagement bait like:
- "Anyone else?"
- "Thoughts?"
- "Curious what people think"
unless the question itself is concrete and relevant

### 3. Observation-led
Lead with a short pattern, lesson, or take.

Good for:
- operator-approved angle testing
- rooms where brief practical takes perform better than direct asks

### 4. Soft bridge
Use only when public value is present first and the group can tolerate mild commercial framing.

Good for:
- high promo tolerance groups
- groups where self-promotion norms are clearly relaxed
- posts where the offer is secondary to the useful point

A soft bridge means the commercial layer is optional and understated.
It must never dominate the message.

## CTA Rules

Default CTA options:
- no CTA
- one narrow discussion question
- one low-pressure invitation to compare notes
- one optional offer to share an example

Allowed stronger CTA options when group context supports them:
- "dm me if you want more detail"
- "happy to share more in dm"
- "can send more context in dm if useful"
- "more detail is in our channel if you want to look"
- "if useful, there's more in our channel"

Stronger CTA use is allowed only when:
- `promo_tolerance` is `medium` or `high`
- the post already provides standalone value
- the CTA appears at the end
- the CTA is brief and non-needy
- the runtime posture does not prohibit soft promotion

Do not default to stronger CTA options.
Use them only when they fit the room and the post would still feel acceptable without them.

Do not default to:
- "DM me"
- "message me"
- "book a call"
- "check our site"

These may be used in lighter form only when the room norms and runtime posture clearly allow it:
- "dm me if useful"
- "happy to share more in dm"
- "more detail is in our channel if you want it"

If the room is promo-sensitive, prefer no CTA or a discussion CTA only.

## Offer Mention Rules

If the offer appears in the post:
- mention it briefly
- keep it secondary
- make it legible without hype
- tie it directly to the useful point being made

Do not:
- front-load the offer
- list features
- stack proof claims
- introduce pricing
- use fake social proof
- imply guarantees

## Hard Bans

Do not write:
- "Hey everyone"
- "Admin delete if not allowed"
- "Wanted to introduce myself"
- "We help X do Y"
- "If anyone needs help with ..."
- "Hope this helps"
- "Would love to connect"

Do not produce posts that:
- sound like a cold DM pasted into a group
- look like a growth hack
- overfit to engagement bait
- ask for trust before giving value
- turn one useful point into a promo paragraph

## Risk Adjustment

### Low promo tolerance
- contribution-first only
- no overt CTA
- no offer mention unless essential
- shorter is better

### Medium promo tolerance
- contribution-first or question-led
- very light CTA allowed
- soft DM or channel CTA allowed at the end if the post is already useful
- soft bridge only if natural

### High promo tolerance
- observation-led or soft bridge allowed
- soft DM CTA or channel CTA allowed
- still avoid ad tone
- still keep the value layer first

## Output Logic

Pick the lightest viable move:
1. contribution-first post
2. question-led post
3. observation-led post
4. soft-bridge post
5. no-send recommendation if public posting risk is too high

If the runtime context suggests the post would feel out of place, do not compensate by writing a cleverer pitch.
Reduce pressure instead.

## Output Format

Return exactly:

PRIMARY_DRAFT:
<ready-to-send Telegram group outbound post>

ALTERNATE_DRAFT_A:
<safer or more contribution-led version>

ALTERNATE_DRAFT_B:
<different public angle, usually question-led or observation-led>

DRAFT_NOTES:
- post_mode: contribution_first|question_led|observation_led|soft_bridge|no_send
- promo_risk: low|medium|high
- cta_style: none|discussion|soft_compare_notes|permission_to_share_example|dm_me_soft|channel_redirect_soft
- offer_visibility: none|light|secondary
- claim_usage: [approved claim ids used, or "none"]
- risk_flags: [short list or empty]

## Quality Bar

A good group outbound post should:
- read like it belongs in Telegram
- make sense to the room without private context
- create zero embarrassment if seen by a moderator
- be useful even if nobody replies
- avoid sounding like a funnel step
- leave the account looking like a participant, not a scraper

## Example Tone

Target tone:
- concise
- specific
- calm
- peer-level
- lightly conversational

Not:
- brand voice theater
- copywriter-smart
- loud
- polished
- needy
- pitch-first
