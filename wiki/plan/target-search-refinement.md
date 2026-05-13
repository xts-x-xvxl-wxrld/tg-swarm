# Target Search Refinement Plan

## Goal

Increase the number and quality of live Telegram communities surfaced during discovery without weakening verification honesty or bloating downstream prompt context.

## Status

This plan replaces the earlier exploratory draft with a build-oriented implementation plan aligned to the current runtime as of 2026-05-12.

## Delivery Snapshot

This plan now serves two purposes:

- record what has already landed in the live discovery runtime
- define the remaining implementation track needed to finish the refinement cleanly

### Shipped So Far (2026-05-12)

- Phase 1 is complete: shortlist artifacts now persist `search_diagnostics` with compact per-query coverage metrics.
- Phase 2 is complete: discovery prompts now receive `community_search_summary` instead of raw per-query search dumps.
- Phase 3 is complete for the first deterministic breadth pass: query generation now expands across related phrases and city hubs within a bounded budget.
- Phase 4 is complete: discovery now runs brief searches in `harvest` mode first, reuses the harvested candidate pool during enrichment, and persisted diagnostics now split harvesting from validation so the staged search path is explicit.
- Phase 5 is complete: discovery now runs one bounded refinement pass only when first-pass live coverage is sparse, and persisted diagnostics record whether refinement triggered and what it added.
- Phase 6 is complete: the MTProto community capability now uses `messages.searchGlobal` as a lower-precision fallback when `harvest` mode gets sparse `contacts.search` results, and result provenance is preserved back into discovery.
- Phase 7 is complete: shortlist enrichment now preserves `lookup_ref`, `lookup_ref_type`, `search_source`, `search_mode`, `matched_query`, and `match_kind`, and downstream prompt-safe shortlist payloads now keep compact evidence summaries without inheriting bulky diagnostics.
- Phase 8 is complete: re-ranking now breaks ties in favor of exact live validation over broader harvest matches, and operator/downstream summaries explicitly explain sparse coverage, broader-match reliance, and fallback fill.

### Remaining Work

- code-side target-search refinement is complete for the current build
- remaining follow-up is operational: run live Telegram smoke checks and tune heuristics only if real-world results disagree with the persisted diagnostics

## Why This Work Exists

The discovery stage now does three useful things that did not exist earlier:

- it persists shortlist `verification_state`
- it prefers matched usernames for profile lookup when live search succeeds
- it reuses shortlist verification data downstream in strategy and account planning

Those changes improved evidence continuity, but they did not solve the main search-coverage problem.

The earlier live-search path had several important limits that this build set out to close:

- brief search generation needed broader, budgeted deterministic query families
- discovery prompt context needed a compact `community_search_summary` instead of raw per-query dumps
- `CommunityCapability.search()` needed explicit search semantics plus a broader MTProto fallback path when harvest coverage stayed sparse
- shortlist enrichment needed to reuse harvested candidates, preserve stronger identity evidence, and explain weaker coverage honestly downstream

Those gaps previously made it easy to end up with a shortlist that was honest but still too dependent on `training_knowledge_fallback`.

## Current Baseline

### Already Working

- Discovery persists `live_confirmed`, `search_confirmed`, and `training_knowledge_fallback`.
- Discovery attaches live profile metadata and recent-message sampling when lookups succeed.
- Discovery prefers matched usernames for profile reads instead of blindly round-tripping numeric IDs.
- Strategy and account planning already consume shortlist verification data rather than flattening confidence completely.

### Historical Gaps Closed By This Build

1. Query coverage was too shallow.
   - The runtime now expands deterministic first-pass families across audience, geography, city hubs, and related terminology.
   - One bounded refinement pass can run when productive first-pass families still produce sparse live coverage.
2. The MTProto search surface was too narrow.
   - `harvest` mode now uses a sparse-results fallback to `messages.searchGlobal` while preserving provenance and bounded behavior.
   - `exact` mode remains the narrower confirmation path for validation-focused re-queries.
3. Harvested live evidence needed stronger downstream standardization.
   - Enrichment now preserves `lookup_ref`, `search_mode`, `match_kind`, `validation_path`, and related evidence fields.
   - Later consumers receive compact `coverage_summary` and `evidence_summary` fields instead of bulky raw diagnostics.
4. Search diagnostics needed to be operationalized.
   - Persisted diagnostics now record refinement triggers, harvest-versus-validation summaries, and fallback-query usage.
   - The runtime uses those diagnostics to explain whether broader search materially helped.
5. Ranking honesty needed one more summary pass.
   - Exact live confirmations now outrank broader harvest matches and fallback-only entries.
   - Operator-facing coverage notes now distinguish sparse live coverage, broader harvest reliance, and fallback fill explicitly.

## Constraints

### Accuracy Constraints

- Do not loosen approximate matching just to raise recall.
- Do not rank broad discovery results as equal to exact live confirmations without stronger validation.
- Keep the public `verification_state` values stable for this build.
- Preserve rejection reasons so sparse coverage remains explainable.

### Token Constraints

- Do not keep expanding search breadth while continuing to inject raw query-by-query payloads into discovery prompts.
- Do not store bulky diagnostics in `workflow_snapshot.data` or approval context.
- Keep the shortlist artifact compact enough for reuse by strategy and account planning.
- Keep any refinement loop deterministic and code-driven rather than LLM-driven.

## Target End State

The refined discovery flow should work like this:

1. Build a deterministic first-pass query set from the campaign brief.
2. Harvest a live candidate pool in code.
3. Persist compact diagnostics about what was tried and what worked.
4. Run one bounded refinement pass only if first-pass coverage is sparse.
5. Validate and enrich the strongest harvested candidates.
6. Produce a shortlist that clearly distinguishes exact live confirmation from weaker evidence.
7. Keep downstream prompt payloads compact by passing summary-level evidence, not raw search traces.

## Implementation Plan

### Phase 1: Instrument The Existing Search Path

Status: complete on 2026-05-12.

Goal: make current behavior measurable before broadening it.

Files:

- [agents/discovery/agent.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/agents/discovery/agent.py)
- [telegram_app/discovery.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/discovery.py)
- [tests/test_telegram_runtime_state.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/tests/test_telegram_runtime_state.py)

Changes:

- Record per-query diagnostics for the current brief search path:
  - query text
  - query family
  - search source
  - result limit
  - raw result count
  - accepted candidate count
  - rejected candidate count
- Persist diagnostics on the shortlist artifact, not on workflow snapshot data.
- Add a compact per-run summary for operator/debug use.

Acceptance criteria:

- A persisted shortlist artifact contains structured search diagnostics.
- Later prompt context does not automatically inherit the full diagnostics payload.
- Tests cover diagnostics persistence and artifact shape.

### Phase 2: Replace Raw Prompt Search Dumps With A Compact Harvest Summary

Status: complete on 2026-05-12.

Goal: move search breadth into runtime code without exploding prompt size.

Files:

- [agents/discovery/agent.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/agents/discovery/agent.py)
- [prompts/discovery.md](C:/Users/ravil/OneDrive/Desktop/tg-swarm/prompts/discovery.md)

Changes:

- Stop passing raw per-query `community_searches` payloads into the discovery prompt once query breadth expands.
- Introduce a compact summary layer that gives the model only:
  - the strongest harvested candidates
  - high-level coverage notes
  - succinct verification hints
- Keep raw diagnostics in persisted artifact data for debugging only.

Acceptance criteria:

- Discovery prompt context remains compact even when the runtime executes more queries.
- The model still has enough context to rank communities meaningfully.
- Tests verify that prompt-safe shortlist data stays smaller than persisted diagnostics.

### Phase 3: Expand Deterministic Query Families

Status: first-pass deterministic breadth is complete on 2026-05-12.

Goal: increase recall through better search inputs, not looser matching.

Files:

- [agents/discovery/agent.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/agents/discovery/agent.py)
- [tests/test_telegram_runtime_state.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/tests/test_telegram_runtime_state.py)

Changes:

- Replace the current four-query cap with deterministic query families derived from:
  - target audience
  - objective focus
  - geography
  - city hubs
  - adjacent founder/startup/builder terminology
- Deduplicate queries across families.
- Add execution budgeting so search breadth is broader but still bounded.

Recommended families:

- audience exact
- audience plus geography
- geography hub variants
- founder/startup/builder adjacent variants
- ecosystem-anchor variants when the brief implies them

Acceptance criteria:

- `AI founders` plus `Europe` produces more than the current literal two-query baseline.
- Query generation remains deterministic for the same brief.
- Tests cover breadth, deduplication, and execution-budget behavior.

### Phase 4: Split Harvesting From Validation

Status: complete on 2026-05-12.

Goal: stop using live search mainly as post-hoc candidate validation.

Files:

- [agents/discovery/agent.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/agents/discovery/agent.py)
- [telegram_app/capabilities/communities.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/capabilities/communities.py)
- [telegram_app/capabilities/mtproto/impl_communities.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/capabilities/mtproto/impl_communities.py)

Changes:

- Introduce an explicit live candidate harvesting phase before shortlist validation.
- Expand the capability contract so search can express search mode and limit, or add a second search entrypoint that makes those choices explicit.
- Keep `contacts.search` as the exact-match-oriented first pass.
- Raise or adapt the first-pass result budget beyond the current hardcoded depth where useful.
- Keep the harvested-candidate pool lifecycle explicit enough that later refinement and ranking work can reuse it without recreating prompt-size bloat.
- Persist explicit harvest and validation summaries so broader search behavior is easier to reason about in diagnostics and tests.

Acceptance criteria:

- Discovery can build a shared live candidate pool before candidate-by-candidate enrichment.
- The capability contract clearly separates exact-oriented search from broader harvesting behavior.
- Tests cover sparse-result and multi-query harvest scenarios.

### Phase 5: Add One Bounded Refinement Pass

Status: complete on 2026-05-12.

Goal: improve recall without creating an open-ended autonomous search loop.

Files:

- [agents/discovery/agent.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/agents/discovery/agent.py)
- [tests/test_telegram_runtime_state.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/tests/test_telegram_runtime_state.py)

Changes:

- After deterministic first-pass queries finish, score which query families produced useful live candidates.
- If coverage is still sparse, run one second pass derived only from successful first-pass families.
- Keep the expansion templated and deterministic.

Guardrails:

- exactly one refinement round
- expand only from productive families
- do not relax match thresholds
- persist diagnostics showing whether refinement helped

Acceptance criteria:

- Sparse first-pass cases can trigger one extra pass.
- The second pass is explainable from stored diagnostics.
- The runtime never enters an unbounded search loop.

### Phase 6: Broaden The MTProto Search Surface

Status: complete on 2026-05-12.

Goal: support broader discovery only after the compact-summary path is in place.

Files:

- [telegram_app/capabilities/communities.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/capabilities/communities.py)
- [telegram_app/capabilities/mtproto/impl_communities.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/capabilities/mtproto/impl_communities.py)
- [agents/discovery/agent.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/agents/discovery/agent.py)

Changes:

- Add a broader second-pass harvesting path using `messages.searchGlobal` behind a sparse-results trigger.
- Treat this as a lower-precision source than exact title/handle search.
- Feed results through stricter validation before shortlist promotion.

Acceptance criteria:

- Broader harvesting is optional and only used when first-pass coverage is weak.
- Search-source provenance is preserved on candidates and diagnostics.
- Broad discovery results do not bypass validation.

### Phase 7: Preserve Stronger Identity References And Internal Match Semantics

Status: complete on 2026-05-12.

Goal: keep strong live evidence attached all the way through enrichment and reuse.

Files:

- [agents/discovery/agent.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/agents/discovery/agent.py)
- [telegram_app/capabilities/mtproto/impl_communities.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/capabilities/mtproto/impl_communities.py)
- [telegram_app/discovery.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/discovery.py)

Changes:

- Add internal evidence fields such as:
  - `lookup_ref`
  - `lookup_ref_type`
  - `search_source`
  - `search_mode`
  - `matched_query`
  - `match_kind`
- Keep current downstream lookup fields temporarily for compatibility.
- Preserve public `verification_state` while using richer internal semantics for ranking and diagnostics.
- Finish downstream consumers and summaries so the richer internal evidence remains available for ranking/debugging without leaking bulky payloads into later prompt context.
- Pass compact per-community evidence summaries and coverage notes into downstream prompt-safe shortlist payloads instead of raw diagnostics.

Acceptance criteria:

- Enrichment can reuse the strongest lookup reference from the first successful live hit.
- Candidate diagnostics can distinguish exact handle match from broader discovery.
- Downstream consumers still work without prompt/schema churn.

### Phase 8: Re-Rank And Summarize With Honest Confidence

Status: complete on 2026-05-12.

Goal: improve shortlist quality without hiding weak live coverage.

Files:

- [agents/discovery/agent.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/agents/discovery/agent.py)
- [prompts/discovery.md](C:/Users/ravil/OneDrive/Desktop/tg-swarm/prompts/discovery.md)
- [prompts/strategy.md](C:/Users/ravil/OneDrive/Desktop/tg-swarm/prompts/strategy.md)
- [prompts/account_manager.md](C:/Users/ravil/OneDrive/Desktop/tg-swarm/prompts/account_manager.md)

Changes:

- Re-rank exact live confirmations above broad live discovery and training-knowledge fallback.
- Keep operator-facing summaries short but explicit about sparse coverage causes.
- Ensure downstream prompts continue to rely on stable public verification labels while ignoring bulky diagnostics.
- Add compact evidence summaries so strategy and account-planning can reason about exact versus broader live evidence without raw search traces.

Acceptance criteria:

- Top-ranked shortlist entries skew more strongly toward exact live confirmations.
- Operator-facing summaries explain whether weak coverage came from sparse Telegram results, narrow match quality, or fallback fill.
- Strategy and account-planning prompt payloads remain compact.

## Non-Goals For This Build

- Do not redesign the overall discovery prompt schema.
- Do not change public `verification_state` labels.
- Do not store full raw message excerpts as persistent evidence.
- Do not introduce an open-ended self-directed search loop.
- Do not expand this work into approval or account-tier redesign; those belong to [workflow-refinement.md](C:/Users/ravil/OneDrive/Desktop/tg-swarm/wiki/plan/workflow-refinement.md).

## Success Metrics

- Higher unique live candidates per representative brief.
- Higher count of exact live-confirmed communities.
- Lower proportion of `training_knowledge_fallback` entries in the top-ranked shortlist.
- Better operator explanations for sparse-result cases.
- No material increase in downstream prompt size for strategy and account planning.

## Validation

- Focused pytest coverage for:
  - query-family generation and deduplication
  - diagnostics persistence
  - staged harvesting behavior
  - bounded refinement triggering
  - exact versus broad match semantics
  - shortlist compatibility for downstream stages
- Live Telegram smoke checks for briefs such as:
  - `AI founders` in `Europe`
  - `AI startup builders` in `Berlin`
  - `startup founders` in `London`
- Prompt-context inspection to confirm search broadening does not recreate the token-bloat pattern.

## Recommended Delivery Order

1. Run live Telegram smoke checks against representative briefs and compare the observed quality against persisted diagnostics.
2. Tune deterministic query breadth or ranking heuristics only if live checks show clear gaps.
