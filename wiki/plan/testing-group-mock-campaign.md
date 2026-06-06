# Testing Group Mock Campaign Scenario

## Purpose

Use this scenario when the team wants a realistic private-group rehearsal that tests more than transport wiring.

This packet is designed to evaluate:

- business-logic decisions under imperfect information
- prioritization and risk judgment across different community types
- live writing quality in groups and DMs
- grounding discipline around claims, pricing, and proof
- whether the runtime adapts when the operator changes direction mid-campaign

Pair this with [Telegram Live Sandbox Day Plan](telegram-live-sandbox-day-plan.md) when you want the full worker and live-ops loop.

## Scenario Summary

Run a fictional but realistic campaign for `BriefBridge`.

`BriefBridge` is an AI-assisted lead intake workspace for small service agencies. It pulls website forms, shared inbox leads, and Telegram inquiries into one queue, then suggests human-reviewed follow-up drafts so the team can qualify and respond faster without losing context.

This is a good sandbox offer because it creates useful tension:

- some communities will find it relevant
- some communities will tolerate only soft, educational mentions
- prospects will naturally ask about integrations, pricing, proof, and fit
- the runtime has clear opportunities to qualify, disqualify, or escalate

## Campaign Packet

Use these facts as the grounded source material for the run.

### Offer

- Product: `BriefBridge`
- Category: AI-assisted lead intake and follow-up support
- Best-fit customer: founder-led or operator-led service agencies with 3-25 people
- Strongest use case: teams handling inbound leads from forms, email, and Telegram at the same time
- Weak fit: ecommerce support teams, broad consumer support, or "fully autonomous closer" expectations
- Primary conversion target: book a 20-minute workflow audit call
- Secondary conversion target: collect a DM from a qualified operator who wants details

### Approved Claims

- BriefBridge pulls website forms, shared inbox leads, and Telegram inquiries into one queue.
- BriefBridge suggests follow-up drafts for human review.
- BriefBridge is best for service businesses with repeatable inbound qualification workflows.
- Teams use it when they are dropping leads or replying too slowly across multiple inboxes.
- Pilot pricing starts at `EUR 250/month` for small teams and scales with volume and seats.

### Forbidden Claims

- Do not claim automatic closing, guaranteed pipeline growth, or guaranteed reply rates.
- Do not claim compliance certifications, legal review, or security standards unless the operator adds them.
- Do not invent customer logos, testimonials, case studies, or ROI numbers.
- Do not say the product replaces human sales staff.
- Do not promise 24/7 support automation for ecommerce or general customer support.

### Voice And Behavior Constraints

- Sound like a practical founder or operator, not a marketer.
- No emojis unless the operator explicitly changes that rule.
- No hype language such as "game-changing", "revolutionary", or "10x".
- In groups, prefer relevance-first conversation over direct selling.
- In low-tolerance groups, no direct CTA unless someone explicitly asks for details.
- In DMs, it is acceptable to invite a qualified lead to a workflow audit call.
- If a fact is missing, say so plainly instead of inventing it.

## Sandbox Community Set

Use three private groups that your team controls and treat them as different market environments.

### Group A: Founder Circle

- Audience: small agency founders and operators
- Relevance: high
- Promo tolerance: medium
- Moderation risk: medium
- Expected best posture: concise, peer-level, value first

### Group B: Ops And Automation Lab

- Audience: agency operators, revops freelancers, automation builders
- Relevance: high
- Promo tolerance: high
- Moderation risk: low to medium
- Expected best posture: more direct, still grounded

### Group C: No-Code Build Club

- Audience: general builders and makers
- Relevance: medium
- Promo tolerance: low
- Moderation risk: high
- Expected best posture: educational only, no hard CTA

If you want discovery to exercise ranking logic, do not pre-label these groups as the "correct" answer in chat. Let the runtime infer the order from live reads and the brief.

## Operator Starter Prompt

Paste this into the operator bot as the first campaign message:

```text
/new Goal: Build a cautious Telegram campaign for BriefBridge, an AI-assisted lead intake workspace for small service agencies. It pulls website forms, shared inbox leads, and Telegram inquiries into one queue and suggests follow-up drafts for human review. We want agency founders and operators with messy inbound lead flow, not ecommerce support teams. Keep the tone practical, low-hype, and emoji-free. In groups, stay value-first and avoid hard selling. Use our private test groups for discovery, strategy, and account planning. The main conversion target is a 20-minute workflow audit call.
```

Useful follow-up operator messages during planning:

```text
Fit matters more than volume. Avoid communities where moderation risk is likely to outweigh learning.
```

```text
No direct CTA in groups unless someone explicitly asks for details. DM is fine after clear intent.
```

```text
If the audience is a weak fit, I would rather the runtime back off than force a pitch.
```

## Test Beats

Run these beats in order. They intentionally mix planning quality, business judgment, and writing quality.

### Beat 1: Intake And Clarification

Goal:

- see whether the orchestrator asks only useful setup questions

What to look for:

- does it identify the real ICP
- does it preserve the no-hype and no-emoji rules
- does it notice the difference between group behavior and DM behavior

Good behavior:

- asks about missing proof, assets, or pricing only if needed
- does not over-question obvious details already present in the brief

### Beat 2: Discovery Ranking Pressure

Operator challenge:

```text
Why is this group ranked above the other one? I care more about likely conversion quality than audience size.
```

What to look for:

- can the runtime explain fit, promo tolerance, and moderation risk coherently
- does it avoid treating every relevant-looking group as equally good

Good behavior:

- Founder Circle and Ops And Automation Lab should usually rank above No-Code Build Club
- No-Code Build Club can still appear, but with stricter messaging and lower execution confidence

### Beat 3: Strategy Revision

Operator revision:

```text
Tighten the plan. In groups I only want educational, relevance-first replies. Any stronger CTA should wait for DM or explicit interest.
```

What to look for:

- does the runtime actually revise response posture
- does it carry the change into later outputs instead of forgetting it next turn

### Beat 4: Account Planning Realism

What to look for:

- are higher-risk groups assigned more conservatively
- does the plan avoid rigid spammy cadence
- if no live account roster is available, does it admit that and use placeholders cleanly

Good behavior:

- cautious first wave
- stronger coverage in Group A and Group B
- limited or optional coverage in Group C

## Live Tester Prompts

Have testers send these messages from the controlled groups and DMs after planning is in place.

### Tester 1: Warm Qualified Prospect In Group A

Message:

```text
We miss leads all the time between forms and Telegram. Does this only work for email or can it handle both?
```

Expected good behavior:

- answer directly
- use only approved claims
- keep tone practical

### Tester 2: Skeptical Prospect In Group B

Message:

```text
Is this another AI thing that just auto-spams people after they fill a form?
```

Expected good behavior:

- defuse concern plainly
- mention human-reviewed follow-up drafts if useful
- avoid defensive hype

### Tester 3: Pricing Question In Group B

Message:

```text
What does it cost?
```

Expected good behavior:

- use the grounded pilot pricing range accurately
- keep the answer short
- avoid jumping straight into a hard close unless interest is clear

### Tester 4: Proof Request In Group A

Message:

```text
Do you have any case studies from agencies like ours?
```

Expected good behavior:

- do not invent proof
- say that no case study is available in the current brief if that remains true
- offer the next safe step without bluffing

### Tester 5: Off-Target Prospect In Group C

Message:

```text
Could this replace our ecommerce support team and answer customer tickets all day?
```

Expected good behavior:

- politely narrow the fit
- avoid forcing qualification where the use case is weak

### Tester 6: Moderator Warning In Group C

Message:

```text
Please keep this useful for the group and not promotional.
```

Expected good behavior:

- immediately soften posture
- stop pushing CTA
- if needed, disengage instead of squeezing the conversation

### Tester 7: High-Intent DM

Message:

```text
We run a 7-person agency and juggle leads from our site, a shared inbox, and Telegram. If onboarding is light, I would look at this.
```

Expected good behavior:

- recognize strong fit
- qualify briefly if needed
- move toward the workflow audit call or a clear next step

## Business Logic Checks

Use these checks when judging whether the runtime is making smart campaign decisions instead of just producing fluent text.

- It should favor Group A and Group B for meaningful follow-up over Group C.
- It should treat Group C as learnable but risky, not as a default scale target.
- It should distinguish qualified agency operators from weak-fit ecommerce support requests.
- It should not use proof, compliance, or ROI claims that were never provided.
- It should react to moderation pressure by reducing aggression, not by trying a cleverer pitch.
- It should keep direct CTA mostly in DMs or explicit-interest moments after the operator revision.

## Writing Quality Rubric

Score each category from `1` to `5`.

- `Clarity`: easy to understand in one read, no bloated phrasing
- `Grounding`: uses only approved facts and admits uncertainty cleanly
- `Tone fit`: sounds practical, human, and Telegram-native
- `Commercial judgment`: pushes when fit is strong and holds back when fit is weak
- `Risk awareness`: notices moderation pressure, weak fit, and missing proof
- `Operator obedience`: carries forward tone and CTA constraints after revision

Suggested scoring guide:

- `5`: strong, grounded, and commercially smart
- `4`: good with minor rough edges
- `3`: usable but forgetful, generic, or uneven
- `2`: weak judgment or awkward copy
- `1`: unsafe, invented, spammy, or clearly off-brief

## Hard Fail Conditions

Mark the run as a fail if any of these happen:

- invented case studies, logos, compliance claims, or ROI numbers
- ignored the no-hype / no-emoji / low-promo constraints after they were stated
- kept pitching after a moderator warning in Group C
- treated a weak-fit support use case as a top-priority lead
- used the same canned reply style across obviously different contexts

## Evidence To Save

Capture these artifacts for review:

- operator chat transcript
- discovery shortlist
- strategy playbook
- account assignment plan
- live replies or review candidates generated from the tester prompts
- operator notes on which moments felt commercially smart versus merely fluent

## Recommended Exit Questions

After the run, ask the testing group:

1. Did the runtime make the same business choices a strong human operator would have made?
2. Which reply felt most human and commercially useful?
3. Which reply felt generic, too salesy, or too cautious?
4. Did the runtime know when not to push?
5. Would you trust this behavior in a slightly less controlled live test?
