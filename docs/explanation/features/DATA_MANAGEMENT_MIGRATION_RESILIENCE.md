# Data Management Migration Resilience

Implemented in version: **0.250.071**
Updated in version: **0.250.103**

GitHub issue: [#1043](https://github.com/microsoft/simplechat/issues/1043)

## Overview

Data Management migrations use durable, job-scoped provenance and checkpoints across selected Cosmos DB records, Azure AI Search documents, and Enhanced Citations source blobs. A migration retry retains the original migration GUID and resumes from verified service checkpoints. Operators can run create-only, delta/upsert, or explicitly confirmed mirror migrations, preview estimated destination changes, and review final source/destination reconciliation plus preview divergence.

## Dependencies

- Data Management administrator access.
- Source and destination data-plane permissions for the selected Cosmos containers, Azure AI Search indexes, and source blob containers.
- Destination Cosmos DB Data Contributor for target record writes.
- For temporary Cosmos capacity management, destination ARM access that can read and update database or dedicated-container throughput, plus the target subscription ID and resource group.

## Technical Specifications

### Durable Provenance

Each migration job uses its job ID as a GUID-stable migration identity and records a single UTC start time. Successful copies add destination-specific metadata:

- Cosmos documents: `simplechatMigration` with migration identity, status, and source `_ts` version.
- Azure AI Search documents: queryable migration fields plus a canonical SHA-256 source-document hash. Existing target indexes are updated with compatible provenance fields when necessary.
- Source blobs: migration identity, ETag/last-modified version fingerprint, available content MD5, and a non-reversible scope hash in Blob metadata.

Only a `succeeded` marker is eligible for a skip. The current migration GUID always skips its completed work on resume. Cross-run age-based skipping is explicit and defaults to `0` hours.

The migration does not overwrite an unowned destination collision. A Cosmos record, AI Search key, or Blob path that already exists without eligible provenance causes the affected resource to stop and record a collision count. This avoids replacing destination content that may have been created independently. Target Cosmos containers must also have the exact expected partition-key path before probing or writing.

### Checkpoints And Throughput

The migration state is stored on the existing Data Management job record. It contains a secret-free configuration fingerprint, resource status, attempts, copied/skipped/failed counts, bytes, Cosmos request units, rate calculations, preflight results, and capacity lifecycle state. Privacy-safe per-item outcomes are stored separately in bounded batches in the existing job-items container and use SHA-256 logical identities instead of raw document IDs or Blob paths.

- Cosmos records use bounded parallel creates or ETag-conditional replacements with transient retry handling and response-charge capture. Updates are allowed only for successfully migration-owned records.
- AI Search uses deterministic `id asc` keyset pages capped at 1,000 records, a persisted per-index cursor, bounded selected-scope filters, concurrent upload batches, and per-document indexing outcomes. Migrations beyond 100,000 documents do not use deep `$skip` pagination.
- Before an AI Search transfer, the target SimpleChat `data_management_jobs` container closes and drains a durable Search write gate. Normal target SimpleChat document indexing takes a short bounded gate slot, so it cannot race migration uploads or final mirror deletes. The gate is renewed with migration heartbeats, released after a clean transfer or drained cancellation, and retained for the full uncertainty window after a lost response.
- Azure AI Search does not provide document-level ETag or create-only indexing actions. The migration therefore requires a checked external destination-writer freeze acknowledgement, rejects a destination that resolves to the source Search service, and re-reads unresolved keys after a timeout or partial response before retrying. External target writers remain an operational cutover precondition.
- Blob migration streams chunked source content instead of loading each blob into App Service memory. It renews the job lease while long futures are still active, reports in-flight bytes, observes cancellation between chunks, preserves content settings, metadata, tags, access tier, and blob type where supported, and uses source/target ETag conditions.
- Blob uploads use `pending` migration metadata during transfer. The worker verifies destination size/MD5 and source ETag stability before conditionally stamping `succeeded`; failed creates are removed while still owned by the pending attempt.
- Destination marker and Blob deduplication lookups are bounded to the active item or batch rather than retaining a full migration key set in App Service memory.
- ETag-based job replacement and worker-lease checks prevent a stale worker from silently overwriting a newer checkpoint. Each retry gets a fresh attempt timestamp so displayed rates exclude downtime.
- A target-side conditional coordinator lease in the destination `data_management_jobs` container prevents independent SimpleChat source deployments from overlapping before inventory, Cosmos, Search, or Blob writes. The source job persists only the target lock token and keeps the target SDK client process-local; clean completion and drained cancellation release the lease, while uncertain failures retain its expiry quarantine.

Failed, canceled, or stale migration jobs can be retried from the existing job detail. Completed resource checkpoints and the migration GUID remain unchanged.

### Incremental Modes And Watermarks

- **New only** is the default. It creates missing destination identities and never updates or deletes existing data.
- **Delta / upsert** requires a compatible completed migration baseline. The backend uses an explicitly selected baseline job or pins the newest compatible completed job when the field is blank. It creates new items, updates changed migration-owned items, and retains destination-only data.
- **Mirror with deletions** runs delta/upsert and then removes destination-only items only when they carry successful migration ownership. The exact phrase `MIRROR WITH DELETIONS` is required. Unowned destination data is retained and reported.

Each run captures a UTC cutoff for Cosmos and intentionally includes the baseline second again to avoid timestamp-resolution gaps. Cosmos combines `_ts` with a canonical content hash, so different revisions in the same second are still detected. AI Search has no shared modified-time field, so it uses the source version observed during resumable keyset enumeration plus a canonical source hash. Blob Storage uses the ETag observed immediately before transfer and verifies it again after upload. Search or Blob changes observed after inventory can therefore cause preview divergence or a retryable `not_ready` reconciliation; they are never represented as having a global timestamp cutoff.

### Preview, Reconciliation, And Divergence

The explicit Preview action performs a read-only source/destination inventory and estimates creates, updates, unchanged items, deletes, not-applicable blobs, missing sources, and conflicts. Execute Migration queues immediately. After the worker owns the global migration lock, it captures a fresh server-owned inventory as a durable, heartbeat-backed job stage and pins the resolved baseline before transfer begins.

After copy stages complete, memory-bounded reconciliation compares selected source and destination identities across Cosmos, Search, and Blob Storage. Cosmos and Blob use bounded point reads; Search merges ordered source/destination keyset streams without retaining full key maps. Reconciliation records matched, missing, stale, destination-only owned, destination-only unowned, unresolved-scope, conflict, and deleted counts. A `not_ready` report fails retryably and cannot become an incremental baseline.

Mirror deletion is two phase. The worker first persists a private bounded candidate plan and a read-only report. It blocks all deletion when transfer outcomes diverge from the queued preview, copied items are stale/missing/failed/conflicting, unowned extras remain, or any candidate changes. Only then does it stream the private plan again, revalidate current source absence and destination ownership/ETag immediately before each write, and apply guarded deletes.

Job detail exposes readiness, actual outcomes, preview divergence, keyset cursor/checkpoint counters, and Retry/Cancel controls. Admins can download a sanitized JSONL manifest or a filtered failure list (`failed`, `missing`, and `collision`) for remediation; retry resumes the incomplete resource while verified successful items remain idempotent.

### Cancellation And Automatic Recovery

- An administrator can request cancellation from the migration job list. Queued migrations become terminally canceled immediately. Running migrations retain their lease until the worker reaches the next guarded checkpoint, then stop without starting additional migration work.
- Authorization-reducing personal document unshare operations fail retryably while the target Search write gate is frozen. The existing share grant remains authoritative until its Search ACL projection succeeds, so a revoked user is never reported as removed while stale Search chunks could still authorize retrieval.
- Temporary destination Cosmos capacity restoration is allowed during a cancellation request so a canceled migration does not leave the destination boosted.
- Canceled jobs retain their migration ID and completed resource checkpoints. The job detail exposes **Retry** or **Resume** once the canceled worker reaches its terminal state.
- The Data Management scheduler scans delayed queued and stale running migration jobs independently of scheduled backup enablement. It records recovery activity and submits the work asynchronously through the Flask executor or standalone scheduler worker thread.

### Destination Preflight

**Validate Cosmos Migration Access** checks the current selected migration plan for source Cosmos reads plus destination Cosmos create, read, and delete access. The full preflight runs when the migration worker starts:

- Source Cosmos read access for each selected resource.
- Destination Cosmos create, read, and delete access using a short-lived probe item in every planned container.
- Source AI Search read access, destination index/provenance-field readiness, and a temporary Search upload/read/delete probe.
- Source and target blob container access when source-blob migration is selected, plus a temporary Blob upload/read/delete probe.

Preflight results are saved in the migration state and shown through existing job details and activity history without credentials or source content.

Version 0.250.103 also exposes these checks through the staged browser workflow's **Review** step. The review API accepts the current redacted settings form plus migration plan, resolves stored secret placeholders on the server, and returns only sanitized pass, warning, or blocker results. It combines exhaustive scope/document counts, temporary access probes, partition-key validation, destination coordinator and Search write-gate availability, optional capacity inspection, and the read-only destination inventory preview. Only a ready review receives a short-lived, administrator-bound authorization. Job creation atomically reserves it, releases that exact reservation if durable queueing fails, and the resulting job consumes it before work; blocked, expired, replayed, or changed reviews are rejected. The worker also verifies the reviewed migration-setting fingerprint before execution. The review remains a snapshot, and execution-time worker preflight is authoritative.

### Temporary Cosmos Capacity

The optional **Temporarily increase destination Cosmos capacity during this migration** control raises eligible destination database or dedicated-container throughput to the configured target, capped at **10,000 RU/s**.

- The original mode and RU/s value are persisted before every ARM capacity change.
- Only targets below the requested value are changed.
- Capacity is restored after successful or failed migration execution.
- Restoration is skipped if the target changed independently after the migration boost, preventing the migration from overwriting an external administrator's update.
- If capacity restoration fails or its outcome is uncertain after an interruption, the migration fails retryably with durable `restore_pending` state. Retry restores the recorded snapshot before any other work and does not reapply the boost.

## Usage

1. Open **Admin Settings > Data Management > Migration** and complete **Target**.
2. In **Scope**, choose none, selected, or all for each principal type. Search and page selected catalogs without losing choices.
3. In **Content & Options**, choose document surfaces, Search/blobs, synchronization mode, concurrency, retry, and optional capacity behavior.
4. In **Review**, run preflight and resolve blockers for access, partition keys, collisions, locks, compatibility, and capacity. Review estimated creates, updates, unchanged items, deletes, missing sources, and conflicts.
5. In **Confirm**, acknowledge the normalized plan. Mirror mode requires the exact destructive confirmation phrase.
6. Execute the migration and use **Progress** or the full job log to observe durable inventory, stage state, transfer rates, in-flight Blob bytes, keyset checkpoints, outcome counts, reconciliation readiness, and preview divergence.
7. Download the manifest or failure list when item-level remediation is required.
8. Use **Cancel** to request a cooperative stop. Use **Retry** or **Resume** on a failed, canceled, or stale job. The original migration GUID and completed destination markers are retained.

### Recommended Cutover

1. Run **New only** for the initial transfer.
2. Keep the source active and run one or more **Delta / upsert** catch-up migrations.
3. Resolve preview conflicts and any reconciliation state that is `not_ready`.
4. Freeze source writes and external destination AI Search writers for the final cutover window. Confirm the destination Search writer freeze in the migration workflow.
5. Run a final **Delta / upsert**, or a confirmed **Mirror with deletions** only when the destination must exactly follow source deletions.
6. Switch traffic only after final reconciliation is `ready` or its warnings are explicitly accepted.

## Testing And Validation

- `functional_tests/test_data_management_migration_provenance.py`
- `functional_tests/test_data_management_migration_state.py`
- `functional_tests/test_data_management_cosmos_migration_resilience.py`
- `functional_tests/test_data_management_ai_search_migration_resilience.py`
- `functional_tests/test_data_management_blob_migration_resilience.py`
- `functional_tests/test_data_management_destination_cosmos_capacity.py`
- `functional_tests/test_data_management_migration_orchestration.py`
- `functional_tests/test_data_management_migration_retry.py`
- `functional_tests/test_data_management_migration_coordinator.py`
- `functional_tests/test_data_management_migration_preflight.py`
- `functional_tests/test_data_management_migration_cancellation.py`
- `functional_tests/test_data_management_migration_recovery.py`
- `functional_tests/test_data_management_incremental_migration_modes.py`
- `functional_tests/test_data_management_migration_reconciliation.py`
- `functional_tests/test_data_management_migration_manifest.py`
- `functional_tests/test_data_management_security_patterns.py`
- `functional_tests/test_data_management_migration_workflow_contract.py`
- `ui_tests/test_admin_data_management_settings_ui.py`

The focused coverage verifies provenance and source fingerprints, unowned collision rejection, equal-second Cosmos updates, Search transfer and reconciliation beyond 100,000 documents, failed-page cursor retention, Blob mid-transfer heartbeats and pending-to-succeeded verification, mode and baseline validation, two-phase migration-owned mirror deletion, post-cutoff source protection, preview divergence, durable hashed manifests, global coordination, cancellation/retry recovery, route protection, and safe browser rendering.

## Limitations

- The application migrates selected SimpleChat scopes, not every arbitrary resource in the source account.
- Azure AI Search request-unit charges are not available through the data-plane response; job telemetry reports item and byte rates for Search.
- Throughput above 10,000 RU/s remains Azure portal managed and is not changed by SimpleChat.
- A migration that encounters unowned destination records, Search keys, or Blob paths must be reconciled by an administrator before it can continue. The job detail records the collision rather than overwriting destination data.
- A global destination coordinator prevents partially overlapping SimpleChat Data Management migrations from running concurrently. The target Search write gate also coordinates normal SimpleChat target indexing, but external writers remain outside that gate and must be frozen for final cutover.
- The browser workflow test requires a configured authenticated UI environment; the static UI contract remains runnable locally.
- AI Search has no shared source modified-time field, so delta mode keyset-scans selected documents and avoids writes through source-hash comparison.
- Selected-scope Blob mirror deletion requires the destination blob's scope hash. Older migration-owned blobs without that marker are retained and reported as unresolved rather than deleted.

## Version References

- Application version updated in `application/single_app/config.py` to `0.250.071`.
- The staged migration workflow and catalog/review contracts were updated in `application/single_app/config.py` version `0.250.103`.
- This documentation and the related functional tests use their corresponding implementation versions.