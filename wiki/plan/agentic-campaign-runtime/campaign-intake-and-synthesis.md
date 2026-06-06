# Campaign Intake And Synthesis

## Goal

Define how mixed operator input becomes a durable campaign intent package.

## Core Problem

The current intake path still leans on labeled-field extraction and campaign-brief compatibility state.

That is useful as a fallback, but it is too narrow for the target operator behavior:

- "here are the client files"
- "here are some groups"
- "send qualified leads to this destination"

## Desired Direction

The orchestrator should interpret a campaign corpus, not just a text form.

That corpus may include:

- freeform text
- Telegram links and handles
- uploaded docs
- images and screenshots
- long unstructured seed dumps
- explicit conversion destinations

## MVP Contract

Step 1 should lock the smallest durable `campaign intent package` that lets the runtime move beyond a form-shaped brief without prematurely solving later slices.

The first cut should persist at least:

- `business_context`
- `offer_summary`
- `target_audience`
- `geography_hints`
- `language_hints`
- `seed_inputs`
- `asset_refs`
- `qualification_posture`
- `conversion_target_signal`
- `autonomy_posture`
- `campaign_constraints`
- `ambiguities`
- `source_message_refs`

The intent package should favor compact structured fields with short natural-language summaries inside them where needed.

Example shape for the first cut:

```json
{
  "business_context": "Short summary of the client, business, or campaign context.",
  "offer_summary": "Short summary of what is being promoted or offered.",
  "target_audience": "Short summary of the intended audience.",
  "geography_hints": ["Budapest", "Hungary"],
  "language_hints": ["English", "Hungarian"],
  "seed_inputs": {
    "raw_entries": ["t.me/example", "@examplegroup", "crypto founders groups"],
    "normalized_candidates": ["t.me/example", "@examplegroup"],
    "unresolved_mentions": ["crypto founders groups"]
  },
  "asset_refs": ["asset-123", "asset-456"],
  "qualification_posture": "High-level notes about who counts as qualified.",
  "conversion_target_signal": {
    "raw_value": "send qualified leads to t.me/johndoe",
    "kind_hint": "telegram_dm",
    "needs_clarification": false
  },
  "autonomy_posture": {
    "operator_stated": "keep running until paused",
    "bounded_mode": "default"
  },
  "campaign_constraints": ["Do not message in Russian."],
  "ambiguities": ["Whether the campaign is limited to private groups."],
  "source_message_refs": ["message-1", "message-2"]
}
```

## Persistence And Compatibility Direction

Step 1 should introduce the campaign intent package as the new source of truth for mixed-input interpretation.

Compatibility should remain explicit:

- `campaign_brief` remains a compatibility artifact for older planning-era consumers.
- `campaign_setup_state` remains the deterministic readiness and operator-guidance seam.
- the new intent package should be campaign-owned and durable, not an ephemeral prompt-only summary
- compatibility views may be derived from the intent package during the transition, rather than continuing to treat the brief as the only real state

This avoids a flag-day rewrite while making it clear which object newer slices should build on.

## Synchronous Versus Deferred Interpretation

The first cut should do only the minimum interpretation needed during the operator turn.

Synchronous in Step 1:

- collect the operator message, links, and stored attachment refs into one campaign corpus update
- synthesize or refresh the campaign intent package
- produce one operator-facing interpretation summary
- surface material ambiguities that block confident understanding

Deferred to later work or background enrichment:

- deep asset-role inference beyond lightweight asset awareness
- strong normalization of conversion destinations into a full runtime contract
- specialist-grade qualification modeling
- deep investigation of extracted seed communities

## Step Boundaries And Non-Goals

Step 1 should intentionally stop short of later slices.

It should include:

- mixed-input intake across text, links, and stored campaign assets
- extraction or preservation of candidate seed communities from messy operator input
- preservation of conversion-target intent as a first-class signal, even if later normalization is still pending
- a campaign-owned interpreted state object that can be updated over time

It should not include:

- final multi-role asset inference and confidence modeling
- full conversion target normalization and handoff semantics
- campaign-specific qualification execution
- continuous autonomous looping behavior
- operator notification or recovery surfaces beyond immediate intake clarification

## First Questions Now Locked

- the durable fields above are sufficient for the first cut
- interpretation in the operator turn should stay bounded to corpus synthesis, summary generation, and ambiguity surfacing
- `campaign_brief` and `campaign_setup_state` remain compatibility and readiness seams during the transition
- the orchestrator should explain its interpretation through one compact summary plus one explicit ambiguity list

## Operator-Facing Interpretation Summary

The first cut should standardize one simple operator-facing summary shape.

It should usually communicate:

- what the runtime believes the campaign is about
- who it believes the audience is
- what seed communities or links it recognized
- what assets it noticed
- what it believes the conversion destination is, if any
- what is still ambiguous or missing

The summary should be concise and operational, not a long reflective explanation.

## Expected Deliverables

- one normalized campaign intent package
- one operator-facing interpretation summary
- one clear list of ambiguities that still need intervention

## Acceptance For This Slice

This slice is ready to call landed when:

- an operator can send mixed text, links, and files without having to pre-label every item
- the runtime persists one campaign-owned intent package for that input
- the runtime can preserve both normalized seed candidates and unresolved seed mentions
- the runtime can preserve a first-class conversion-target signal without waiting for the later full contract
- the orchestrator can show a compact interpretation summary and ambiguity list back to the operator
- older consumers that still expect `campaign_brief` or `campaign_setup_state` continue working through explicit compatibility handling

## File-Level Direction

Expected touchpoints will likely include:

- `telegram_app/intake.py`
- `telegram_app/campaign_setup.py`
- `telegram_app/orchestrator/orchestrator.py`
- `telegram_app/orchestrator/context_builder.py`
- `telegram_app/campaign_memory/`
- new supporting runtime models for interpreted campaign intent
- compatibility mapping from the new intent package into existing brief-shaped surfaces where needed
