# Discovery Search Map

## Purpose

This map covers the live Telegram community search path used during discovery shortlist generation and enrichment.

Use it when working on query generation, harvested candidate pooling, verification labels, MTProto search behavior, or prompt-safe shortlist shaping.

## Read First

- [agents/discovery/agent.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/agents/discovery/agent.py)
- [telegram_app/discovery.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/discovery.py)
- [telegram_app/capabilities/communities.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/capabilities/communities.py)
- [telegram_app/capabilities/mtproto/impl_communities.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/capabilities/mtproto/impl_communities.py)
- [prompts/discovery.md](C:/Users/ravil/OneDrive/Desktop/tg-swarm/prompts/discovery.md)
- [tests/test_telegram_runtime_state.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/tests/test_telegram_runtime_state.py)
- [wiki/plan/target-search-refinement.md](C:/Users/ravil/OneDrive/Desktop/tg-swarm/wiki/plan/target-search-refinement.md)

## Runtime Path

1. [telegram_app/intake.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/intake.py) persists the campaign brief that discovery search expands from.
2. [agents/discovery/agent.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/agents/discovery/agent.py) builds deterministic query specs in `_build_search_query_specs()`.
3. The same module runs bounded live searches in `_run_brief_searches()`, producing:
   - a prompt-safe `community_search_summary`
   - persisted `search_diagnostics`
   - an in-memory harvested candidate pool used during enrichment
4. [telegram_app/capabilities/communities.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/capabilities/communities.py) defines the `CommunityCapability.search(query, mode, limit)` contract.
5. [telegram_app/capabilities/mtproto/impl_communities.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/capabilities/mtproto/impl_communities.py) implements that contract with Telethon search/profile reads.
6. Back in [agents/discovery/agent.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/agents/discovery/agent.py), `_enrich_shortlist()` and `_find_live_match()` reuse harvested candidates before exact re-queries, then preserve `lookup_ref`, `match_kind`, and `verification_state`.
7. [telegram_app/discovery.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/discovery.py) persists the shortlist artifact while keeping bulky diagnostics out of workflow-snapshot state.
   The persisted shortlist now carries compact `coverage_summary` and per-community `evidence_summary` fields for downstream use without leaking raw search traces.
8. [agents/strategy/agent.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/agents/strategy/agent.py) and [agents/account_manager/agent.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/agents/account_manager/agent.py) consume prompt-safe shortlist data downstream and should not inherit raw `search_diagnostics`.

## Key Boundaries

### Query Generation

- Discovery query expansion belongs in [agents/discovery/agent.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/agents/discovery/agent.py), not in prompts.
- Query breadth should stay deterministic and budgeted for a given campaign brief.

### Prompt-Safe Versus Persisted Data

- `community_search_summary` is the compact, prompt-safe view.
- `search_diagnostics` belongs on the persisted shortlist artifact for debugging and later analysis.
- `coverage_summary` and per-community `evidence_summary` are the compact downstream-facing bridge between those two layers.
- `workflow_snapshot.data` should stay small and stage-oriented.

### Harvesting Versus Validation

- `harvest` mode is the broad candidate-pool builder.
- `exact` mode is the narrower confirmation path for targeted requeries.
- Validation still happens through live matching, profile lookup, and optional recent-message sampling before a candidate is treated as strongly confirmed.
- Persisted diagnostics now expose explicit `harvest` and `validation` sections so those stages can be reasoned about separately.

### Public Versus Internal Evidence

- Public downstream compatibility currently depends on stable `verification_state` values:
  - `live_confirmed`
  - `search_confirmed`
  - `training_knowledge_fallback`
- Internal ranking and diagnostics can use richer fields such as `lookup_ref`, `lookup_ref_type`, `search_source`, `search_mode`, `matched_query`, `match_kind`, and `validation_path`.
- Downstream prompt-safe shortlist payloads should rely on `verification_state`, `coverage_summary`, and compact `evidence_summary` rather than raw diagnostics.

## Related Tests

- [tests/test_telegram_runtime_state.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/tests/test_telegram_runtime_state.py) covers:
  - diagnostics persistence
  - prompt-safe artifact shaping
  - deterministic query expansion
  - harvested-pool reuse before exact re-queries
  - lookup reference preservation

## Common Edit Zones

- Query-family tuning: [agents/discovery/agent.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/agents/discovery/agent.py)
- Artifact persistence shape: [telegram_app/discovery.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/discovery.py)
- Telethon search/profile semantics: [telegram_app/capabilities/mtproto/impl_communities.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/telegram_app/capabilities/mtproto/impl_communities.py)
- Downstream prompt-size hygiene: [agents/strategy/agent.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/agents/strategy/agent.py), [agents/account_manager/agent.py](C:/Users/ravil/OneDrive/Desktop/tg-swarm/agents/account_manager/agent.py), and [prompts/discovery.md](C:/Users/ravil/OneDrive/Desktop/tg-swarm/prompts/discovery.md)
