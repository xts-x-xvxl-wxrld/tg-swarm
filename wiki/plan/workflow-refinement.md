# Workflow Refinement Plan

## Goal

Refine the operator workflow so planning and execution decisions are grounded in real runtime state instead of prompt-only assumptions.

## Focus Area

The current workflow relies on lightweight account metadata and prompt guidance that can overstate what the runtime actually knows about each Telegram account.

This refinement pass should make workflow decisions more legible, safer, and more tightly connected to persisted operational signals.

## Tiering Direction

Keep tiers, and derive them from real signals like account age, successful joins/sends, rate limits, and flags.

The refined tier system should stop behaving like a purely narrative planning hint and instead become a runtime-supported risk label that the operator can trust.

## Investigation Findings

### Discovery Enrichment Findings (2026-05-11)

The live-shortlist weakness observed during runtime monitoring breaks into two separate issues:

1. The discovery prompt explicitly allows training-knowledge communities when live capability context is absent or unsuccessful, so speculative handles are currently expected behavior rather than a pure runtime bug.
2. The enrichment implementation has a concrete profile-lookup bug after successful live search matches.

#### Verified Runtime Bug

- In discovery enrichment, a successful live match stores `community_id` and then prefers that numeric string for profile lookup.
- The MTProto community capability calls `client.get_entity(community_id)` with that bare numeric string.
- In the latest live run, this produced failures such as `Cannot find any entity corresponding to "2258115941"` even though the earlier live search match had already succeeded for the same community.
- Message sampling still succeeded in those same cases because the history path prefers the handle first, which is resolvable.

This means the current enrichment flow can end up in an inconsistent state:

- live search match succeeds
- profile read fails
- message sampling succeeds

So the shortlist looks half-verified even when the runtime already has enough information to do better.

#### Workflow-Quality Gap

- The discovery prompt permits fallback to training knowledge and only requires honesty in `source_notes`.
- The current enrichment pass annotates failed live lookups but does not strongly downrank, filter, or clearly separate unverified candidates from live-confirmed candidates.
- As a result, shortlist entries with failed username lookups can still rank highly and look more trustworthy than they should.

#### Secondary Design Drift

- The strategy agent performs fresh profile reads using `handle` or `name` instead of reusing the discovery artifact's verified match/profile data.
- That makes downstream behavior depend on another round of lookups instead of the strongest data already gathered during discovery.

#### Test Coverage Gap

- Existing runtime tests use fake community/profile capabilities that happily return profiles for arbitrary lookup strings.
- That means the current test suite does not catch the Telethon lookup mismatch between successful search results and failed profile reads.

### Prompt And Stage-Contract Findings (2026-05-11)

These findings overlap with the discovery/evidence issues above and explain why the runtime can still behave unexpectedly even when the underlying capability data is mostly correct.

#### Confirmed Overlap With Current Findings

- The account-planning stage currently trusts prompt output too much. A malformed or oversized account-plan response can fall back to `raw_output` persistence while still creating a pending approval, which makes approval state look valid even when the structured artifact is not.
- The strategy-to-account-planning transition lacks an explicit operator checkpoint. After strategy output, a vague follow-up like "what's next?" can be interpreted as consent to generate a full account plan rather than a request for a concise next-step summary.
- Prompt contracts currently encourage overproduction. The account-manager prompt asks for assignments, schedules, and draft copy across the full shortlist, including communities that are unverified or operationally blocked.
- Prompt delivery is inconsistent across specialists. Discovery receives runtime context as a dedicated prompt block, but strategy and account planning rely on narrower ad hoc user content, which increases drift between prompt expectations and runtime state.
- A legacy research/handoff pattern still exists in old prompt assets and historical behavior. That makes it easier for unsupported "research agent" behavior to reappear even though the live runtime path is now orchestrator -> discovery -> strategy -> account manager.

#### Operator-Experience Failure Mode

- Discovery can return a mixed shortlist that includes live-confirmed, search-confirmed, and speculative communities.
- Strategy can then produce a coherent narrative across the whole shortlist without forcing a clean review step.
- Account planning can then attempt to produce a giant "complete" plan across mostly blocked or unverified items.
- The operator ends up approving or revising a plan that is much less executable than it appears from the top summary.

### Local File Integrity Findings (2026-05-11)

- `telegram_app/orchestrator/orchestrator.py` in the working tree is currently corrupted with null bytes and fails local Python compilation.
- Git still retains a readable source version of that file at `HEAD`, which means the corruption is local to the working tree rather than a committed code change.
- `wiki/log.md` shows the same null-byte corruption pattern in the working tree while `HEAD` still contains readable markdown.
- Because both files were readable in git but corrupted on disk, the most likely causes are failed editor save, external overwrite, or sync-layer corruption rather than intentional application logic edits.

## Intended Outcomes

1. Account-tier decisions are based on persisted evidence rather than default labels alone.
2. Operator-facing planning language matches what the runtime can actually enforce.
3. Approval workflows do not advance on malformed or incomplete plan artifacts.
4. Execution plans shown to the operator are reviewable in Telegram before approval.
5. Verification state survives across discovery, strategy, and account planning instead of being rediscovered opportunistically.
6. Account plans clearly distinguish executable work from blocked work and operator follow-ups.
7. Prompt contracts and workflow stages align tightly enough that vague operator follow-ups do not trigger heavyweight downstream plans accidentally.
8. Critical runtime files have a small documented recovery path and integrity check so local file corruption does not masquerade as workflow logic regressions.

## Prioritized Adjustments

### High ROI

1. Block approvals when specialist artifacts are malformed, empty, or missing required machine-readable fields.
2. Fix discovery profile lookup so successful live matches prefer a resolvable identifier, especially matched usernames/handles instead of bare numeric IDs when Telethon round-tripping is unreliable.
3. Carry discovery verification state forward into downstream stages instead of forcing strategy or account planning to rediscover the same context.
4. Make verification state explicit in persisted artifacts and Telegram-facing summaries so the operator can quickly see which candidates are live-confirmed, search-confirmed only, or training-knowledge fallback.
5. Add regression coverage for the exact live failure mode observed in the 2026-05-11 run snapshot.
6. Add an explicit post-strategy review checkpoint so the operator must clearly approve strategy generation of an account plan before the runtime enters account planning.
7. Restore specialist prompt contracts so they only ask for work the runtime can persist, validate, and explain honestly.

### Medium ROI

1. Separate executable assignments from blocked assignments and required operator actions inside the account assignment artifact.
2. Add a structured repair path when specialist JSON is malformed, such as a single repair pass before any artifact or approval is persisted.
3. Tighten prompt wording so fallback communities remain allowed when necessary but are presented as clearly lower-confidence than live-confirmed candidates.
4. Standardize runtime-context delivery across discovery, strategy, and account-planning calls so prompt behavior stays anchored to the same state model.
5. Remove or clearly quarantine stale prompt assets and unsupported handoff language that refer to the old research-agent path.

## Refinement Themes

### Account Trust Signals

- Define the real signals that contribute to account trust classification.
- Start with observable signals already present or derivable in the runtime:
  - account age or onboarding age
  - successful joins
  - successful sends
  - recent rate limits
  - flagged or banned health transitions
- Decide which signals are hard blockers versus soft scoring inputs.

### Operator Transparency

- Explain account suitability in concrete operational terms instead of vague tier language alone.
- Show why an account is considered safe, medium-risk, warming up, or restricted.
- Avoid telling the operator that a senior account is required unless the runtime can justify that claim from stored signals or explicit policy.

### Approval Safety

- Prevent account-plan approvals from being created when the machine-readable plan payload is missing or invalid.
- Validate required artifact structure before persisting approvals, including non-empty assignment lists for executable account plans.
- Add a repair-or-retry path for malformed specialist JSON before the runtime falls back to raw text persistence.
- Ensure the operator sees the actual plan summary or assignment detail that they are being asked to approve.
- Keep workflow stage transitions aligned with valid persisted artifacts.

### Evidence Continuity

- Persist verification labels that downstream stages can trust without re-querying the same community opportunistically.
- Reuse discovery-stage live match, profile, and sampling evidence in strategy and account planning whenever it is already available.
- Avoid treating search-only or training-knowledge candidates as equivalent to live-confirmed communities during downstream planning.

### Execution Readiness

- Separate "plan generated" from "plan executable".
- Distinguish executable assignments from blocked assignments and operator actions required to unblock them.
- Make blocked assignments explicit when required account trust signals are missing.
- Preserve room for manual operator overrides where appropriate.

### Prompt Contracts

- Make each specialist prompt responsible only for outputs the runtime can validate structurally.
- Treat prompt wording as part of the runtime contract, not just tone or UX copy.
- Avoid prompts that ask for "complete" downstream plans when the runtime state still contains unresolved verification, account availability, or approval gaps.
- End each major stage with a clear operator choice when the next stage is materially more expensive, riskier, or more operational than the current one.

### File Integrity And Recovery

- Treat local null-byte corruption as a runtime-operational issue with a small recovery runbook, not as ordinary code drift.
- Keep at least one low-cost integrity check for critical entrypoint files such as `telegram_app/orchestrator/orchestrator.py`.
- Prefer restoring corrupted working-tree files from git or local version history before debugging application behavior built on top of them.

### Verification Visibility

- Render verification confidence directly in shortlist and plan summaries rather than burying it only in `source_notes`.
- Show blocked versus executable work clearly in Telegram so approval decisions are legible on mobile.
- Keep fallback communities visible when useful, but never visually equivalent to live-confirmed candidates.

## Prompt Rework Plan

### Discovery Prompt Rework

- Keep fallback communities allowed, but split the output into two semantic groups:
  - primary candidates: live-confirmed or search-confirmed communities that are reasonable to carry forward
  - reserve candidates: lower-confidence or training-knowledge communities kept for optional follow-up
- Require explicit verification labeling per community, not just freeform `source_notes`.
- Tighten ranking guidance so unverified handles cannot sit beside live-confirmed communities without a visible confidence penalty.
- Keep the operator-facing summary short and mobile-readable, but make the machine-readable block strict enough that downstream stages can tell what is executable versus speculative.

### Strategy Prompt Rework

- End the strategy response with an explicit next-step checkpoint:
  - approve strategy and generate account plan
  - request strategy revisions
  - stop after strategy
- Instruct the strategy stage to acknowledge verification confidence from discovery instead of flattening the shortlist into one equally reliable set.
- Prevent the strategy prompt from implying execution readiness when most communities are still blocked or unverified.

### Account-Manager Prompt Rework

- Replace the single flat `assignments` list with a structure that distinguishes:
  - `executable_assignments`
  - `blocked_assignments`
  - `required_operator_actions`
- Generate concrete schedules and draft copy only for executable assignments.
- For blocked items, require reason codes and unblock steps instead of pseudo-complete plans.
- Explicitly instruct the model not to create an approval-ready plan when there are zero executable assignments.
- Prefer a concise operator summary when roster limitations or verification gaps dominate the result.

### Shared Prompt Cleanup

- Remove or quarantine legacy prompt language that refers to unsupported research-agent handoffs.
- Standardize prompt assumptions about the live roster and runtime path.
- Keep role descriptions accurate, but treat schema compliance and stage discipline as the primary prompt responsibility.

## `orchestrator.py` Recovery Instructions

1. Confirm corruption instead of guessing:
   - `python -m py_compile telegram_app/orchestrator/orchestrator.py`
   - if this fails with `null bytes`, treat the working-tree file as corrupted
2. Compare the working tree with git:
   - `git show HEAD:telegram_app/orchestrator/orchestrator.py`
   - if `HEAD` is readable, prefer recovering from git or local editor/version history rather than hand-retyping the file
3. Recover the file from the safest available source:
   - first choice: local editor history or OneDrive version history if uncommitted work mattered
   - second choice: restore the file content from `HEAD`
4. Re-run a cheap integrity gate immediately after recovery:
   - `python -m py_compile telegram_app/orchestrator/orchestrator.py`
   - `python -m pytest tests/test_telegram_runtime_state.py`
5. If multiple files show the same null-byte pattern, widen the investigation to sync/editor tooling before trusting any local runtime behavior reproduced from the corrupted workspace.

## Suggested Implementation Sequence

1. Recover `telegram_app/orchestrator/orchestrator.py` from a trustworthy source and verify it compiles before using runtime behavior as evidence.
2. Tighten approval gating around valid structured artifacts so malformed or empty specialist outputs cannot create pending approvals or advance workflow state.
3. Add a structured repair pass for malformed discovery, strategy, and account-planning JSON before falling back to raw text persistence.
4. Fix discovery enrichment so successful live matches use a resolvable profile lookup reference, preferably the matched username or another identifier form guaranteed to round-trip through Telethon.
5. Persist and render explicit verification labels so live-confirmed, search-confirmed, and training-knowledge candidates are clearly differentiated for the operator.
6. Reuse persisted discovery verification data downstream instead of forcing strategy to rediscover the same profile context opportunistically.
7. Add an explicit post-strategy operator checkpoint before entering account planning.
8. Split account assignment artifacts into executable assignments, blocked assignments, and operator actions required to unblock execution.
9. Rework discovery, strategy, and account-planning prompts so they align with the validated artifact schemas and stage boundaries.
10. Standardize runtime-context delivery across specialist calls and remove stale research-agent prompt drift from the active path.
11. Define the account-tier model and scoring inputs in runtime terms.
12. Add persisted signal fields or derived computations needed to support that model.
13. Add focused tests for artifact validation, JSON repair, discovery enrichment round-trips, evidence reuse, approval safety, prompt-stage transitions, and operator-visible workflow behavior.

## Validation

- Focused pytest coverage for artifact validation, JSON repair behavior, account registry signal handling, and approval gating.
- Focused pytest coverage for discovery enrichment when live search succeeds but profile lookup must round-trip through the chosen identifier format.
- Focused pytest coverage for downstream reuse of persisted discovery verification data and executable-versus-blocked account plan rendering.
- Focused pytest coverage for the post-strategy checkpoint so vague operator replies do not auto-trigger account planning.
- A compile check for `telegram_app/orchestrator/orchestrator.py` after any recovery or refactor touching the orchestrator entrypoint.
- A live Telegram session smoke test that exercises discovery, strategy, account planning, and approval messaging with a real stored account roster.
