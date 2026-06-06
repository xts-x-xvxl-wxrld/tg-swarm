# Campaign Asset Intake

## Goal

Add attachment-aware campaign intake so documents and images become durable campaign assets with compact campaign-facing summaries.

## Why This Is Separate From Setup

Setup decides what the campaign is. Asset intake decides how non-text inputs become durable campaign context. They should integrate, but they do not need to land in the same code slice.

## Current Runtime Alignment

This slice should extend the runtime seams that already exist rather than invent a second intake path:

- `telegram_app/transport/telegram_updates.py` currently normalizes text and raw payloads only
- `telegram_app/app_service.py` already resolves the session, ensures campaign attachment, and calls intake before orchestration
- `telegram_app/intake.py` already owns text-first campaign brief updates
- `telegram_app/campaign_setup.py` already has `asset_refs` in `campaign_setup_state`
- `telegram_app/campaign_memory/manager.py` already bootstraps an `assets/` directory under each campaign workspace
- `telegram_app/orchestrator/context_builder.py` already injects setup state, workflow data, and campaign memory into prompts

The implementation should keep those responsibilities recognizable:

- transport normalizes attachment metadata
- app service coordinates one asset-ingest pass for the turn
- a dedicated asset seam owns storage, manifests, and analysis
- structured intake consumes resulting asset refs instead of owning file download logic itself

## Scope

- extend normalized operator updates to include attachments
- support `document` and `image` attachment kinds in v1
- persist raw assets under the campaign workspace
- maintain an asset manifest with campaign-owned metadata
- extract compact analysis summaries that can feed setup, memory, and later specialist context
- track whether an asset is operator-approved for future outbound use

## Design Principles

- campaign-owned, not session-owned: raw files and manifest records live under the campaign workspace and survive later sessions
- ref-first, not blob-first: session state and prompt context should carry asset refs and summaries, not raw bytes or giant extracted text blocks
- analyze once, reuse many times: expensive extraction or visual analysis should happen at ingest time and be reused later through stored summaries
- deterministic runtime first: the runtime decides capture, storage, ids, and default safety posture; LLM analysis only enriches already-durable assets
- graceful degradation: failed extraction should not fail the whole operator turn if the raw asset was stored successfully

## Non-Goals

- outbound media sending
- voice notes, video, audio, stickers, or generic album handling beyond simple image support
- a broad digital asset management system
- perfect OCR or full-fidelity document parsing for every file type
- autonomous decisions that mark assets safe for outbound use

## Recommended Runtime Shape

Add a narrow `telegram_app/campaign_assets/` seam instead of widening unrelated modules.

Recommended responsibilities:

- `telegram_app/transport/telegram_updates.py`
  Normalize `document` and `photo` payloads into a small attachment list on `TelegramUpdate`.
- `telegram_app/campaign_assets/manager.py`
  Own workspace paths, manifest persistence, record lookup, and idempotent asset creation.
- `telegram_app/campaign_assets/analyzers.py`
  Own best-effort text extraction and lightweight visual/document summaries.
- `telegram_app/campaign_assets/intake.py`
  Turn one operator update into persisted assets plus compact refs returned to the app service.
- `telegram_app/app_service.py`
  Call asset intake after session/campaign resolution and before text intake/orchestrator routing.
- `telegram_app/intake.py`
  Merge returned asset refs into `campaign_setup_state` and any compact workflow snapshot fields, without owning file download or analysis.
- `telegram_app/orchestrator/context_builder.py`
  Expose only compact asset refs and summaries in prompt context.

This keeps the existing thin-runtime rule intact: app service coordinates, but campaign-asset logic lives in a dedicated seam.

## Attachment Shape

Recommended normalized `TelegramAttachment` fields:

- `attachment_id`
- `kind`
- `telegram_message_id`
- `telegram_file_id`
- `telegram_file_unique_id`
- `file_name`
- `mime_type`
- `caption`
- `size_bytes`
- `width`
- `height`

Notes:

- `attachment_id` should be deterministic within the message, such as `message_id + slot`, not a random uuid
- `telegram_file_unique_id` should be preserved when Telegram provides it because it is useful for dedupe
- image normalization should choose one canonical photo variant, preferably the largest available size, instead of storing every Telegram thumbnail size

## Asset Record Shape

Recommended `CampaignAssetRecord` fields for the manifest:

- `asset_id`
- `campaign_id`
- `source_session_id`
- `source_operator_id`
- `source_message_id`
- `source_attachment_id`
- `kind`
- `stored_path`
- `derived_text_path`
- `analysis_path`
- `original_file_name`
- `mime_type`
- `caption`
- `size_bytes`
- `analysis_summary`
- `tags`
- `sendable`
- `operator_labeled_sendable`
- `ingest_status`
- `ingest_error`
- `created_at`
- `updated_at`

Notes:

- `sendable` is the effective current eligibility flag
- `operator_labeled_sendable` captures the operator's explicit decision separately from future policy-derived restrictions
- `ingest_status` should distinguish at least `stored`, `analyzed`, and `analysis_failed`
- `analysis_path` allows a richer structured sidecar without bloating the manifest entry itself

## Workspace Shape

Recommended campaign workspace layout:

```text
data/campaigns/<campaign-id>/
  assets/
    manifest.json
    raw/
      <asset-id>--<safe-file-name>
    derived/
      <asset-id>.txt
    analysis/
      <asset-id>.json
```

Recommended storage rules:

- raw files are the source of truth for the original inbound asset
- `manifest.json` is the index the runtime reads first on later turns
- extracted text and richer analysis should live in sidecar files so later prompts do not need to reopen the raw asset
- file names should be sanitized, but the stored name should still preserve enough of the original name to help operators inspect the workspace manually

## Intake Lifecycle

For one operator turn with attachments:

1. Normalize the Telegram update into text plus a compact attachment list.
2. Resolve or create the campaign workspace as usual.
3. Dedupe attachments against existing campaign assets using stable source identifiers.
4. Download the raw Telegram file once and persist it under `assets/raw/`.
5. Run best-effort extraction or visual analysis.
6. Persist or update the asset record in `assets/manifest.json`.
7. Return compact asset refs to the runtime so setup state and prompt context can reference them.
8. Continue normal text intake and orchestration without requiring the operator to re-send the file.

This means an attachment-only turn is still meaningful even if the operator sends no text.

## V1 Behavior

- documents: download, store, extract text where possible, produce a compact summary
- images: download, store, produce a lightweight visual summary and tags
- assets remain reference-first by default
- sendable stays false by default for all assets
- images may later become outbound-eligible only after an explicit operator label
- documents should remain non-sendable in v1 even if stored successfully, because outbound document sending is outside this slice

Keep outbound media dispatch out of this slice. This work only prepares campaign memory and metadata for later use.

Recommended document behavior:

- support best-effort extraction first for common text-bearing formats such as `.txt`, `.md`, `.pdf`, and `.docx`
- if text extraction fails, still keep the raw file and persist an `analysis_failed` or `stored` status with a useful error note
- summaries should be compact, campaign-facing, and written for reuse in setup or strategy context rather than as generic file descriptions

Recommended image behavior:

- store the canonical image file selected during normalization
- produce a short visual summary plus a small tag list
- keep the analysis lightweight enough to inject into prompt context later without bloating the runtime context block

## Integration With Setup And Workflow State

- `campaign_setup_state.asset_refs` should become the canonical setup-time pointer list for ingested campaign assets
- `StructuredIntakeCoordinator` should merge asset refs into setup state even when the text message itself carries little or no campaign detail
- `workflow_snapshot.data` may carry small convenience fields such as `asset_ref_count` or recent asset refs, but should not store full summaries or extracted text
- `campaign_brief` should stay focused on campaign intent, constraints, and audience; it should not become the raw asset manifest

This keeps setup conversational while still making attachments immediately reusable.

## Prompt And Memory Direction

- `orchestrator/context_builder.py` should expose a compact asset summary block derived from the manifest
- prompt context should include only a bounded number of recent or operator-relevant assets, not the entire manifest
- each prompt-facing asset entry should include the `asset_id`, `kind`, a short summary, and a few tags
- long extracted text should stay on disk and only be loaded deliberately when a later slice truly needs document-deep reasoning
- campaign memory markdown may later mirror the most important assets, but the manifest remains the authoritative asset index

One practical option for v1 is to inject a context fragment like:

- `campaign_assets_present: true`
- `campaign_asset_refs: [...]`
- `campaign_asset_summaries: [...]`

That is enough for setup and later specialists to know the assets exist and what they roughly contain.

## Operator Labeling Direction

The plan should keep outbound eligibility explicit and deterministic.

Recommended v1 rules:

- newly ingested assets always start with `sendable=false` and `operator_labeled_sendable=false`
- no summary, tag, or analyzer output may flip those flags automatically
- the future labeling path should be narrow and auditable, such as an explicit operator command or a deterministic runtime-recognized phrase tied to a specific asset ref
- if the operator later revokes eligibility, keep the raw asset and analysis but flip the effective sendable posture back to false

The first code slice does not need full outbound-use UX, but it should leave room for a later explicit label update path.

## Failure And Idempotency Rules

- Telegram retries or duplicate webhook deliveries should not create duplicate asset records
- the raw file store and manifest update should be idempotent for the same source attachment
- if download fails, record a useful ingest failure without corrupting the rest of the turn
- if storage succeeds but analysis fails, keep the stored asset and let the turn proceed with a degraded summary
- unsupported document types should be stored with a clear note rather than silently discarded
- prompt context should never pretend an asset was summarized successfully when only storage succeeded

Recommended dedupe keys:

- `telegram_message_id + attachment_id`
- `telegram_file_unique_id` when present

## Delivery Sequence Inside This Slice

This plan is easier to implement safely as four small steps:

### Step 1: Transport And Update Normalization

- extend `TelegramUpdate` to carry normalized attachments
- keep text-only behavior unchanged
- add focused tests for document and photo payload normalization

### Step 2: Campaign Asset Persistence

- add the campaign-asset manager and manifest store
- download and persist raw files under the campaign workspace
- add idempotent ingest tests and workspace-layout tests

### Step 3: Analysis And Prompt Exposure

- add best-effort document extraction and image summaries
- surface compact asset refs and summaries through setup state and runtime context
- add tests proving later turns can reuse stored summaries without reopening raw files

### Step 4: Explicit Sendable Labeling

- add deterministic manifest updates for explicit operator labeling
- keep outbound send behavior out of scope
- add tests proving eligibility stays false until explicitly flipped

## Storage Direction

- raw files live under the campaign workspace
- one manifest indexes asset metadata and analysis summaries
- setup state should hold asset refs, not duplicate the whole asset payload
- campaign memory may later reference assets, but should not become the raw file store

## Acceptance Criteria

- text-only operator turns still work normally
- document uploads create stored files plus asset records
- image uploads create stored files plus asset records
- campaign-facing summaries are available without reopening the raw file every turn
- attachment-only turns still create usable campaign assets
- duplicate delivery of the same Telegram attachment does not create duplicate manifest entries
- setup state holds asset refs that survive later turns and session reload
- sendable eligibility stays false until the operator explicitly labels an asset for outbound use

## Validation

- focused tests for attachment normalization
- tests for workspace asset persistence and manifest updates
- tests for idempotent re-ingest of the same attachment
- tests for degraded-but-durable behavior when analysis fails after storage succeeds
- tests proving setup state and later prompt context can reference stored assets by ref
- manual smoke test with one document upload and one image upload in Telegram

## Open Questions To Resolve Before Coding

- Which document mime types should count as supported in the very first pass versus stored-only?
- Should the first prompt-context exposure include only recent assets or also operator-pinned assets?
- Do we want a dedicated `assets/index.md` human-readable view in v1, or is `manifest.json` plus prompt context enough for the first landing?
