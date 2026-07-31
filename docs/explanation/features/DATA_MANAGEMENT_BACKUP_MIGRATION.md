# Data Management Backup and Migration

Implemented in version: **0.241.211**
Updated in version: **0.250.104**

## Overview

The Data Management feature adds an admin-only portal section for SimpleChat-owned backup, restore preparation, and migration orchestration. It stores its configuration as a separate `backup_settings` document in the Cosmos `settings` container rather than mixing backup secrets and schedules into normal app settings.

## Technical Specifications

### Architecture

- Admin API routes live in `route_backend_data_management.py` and require `@swagger_route(security=get_auth_security())`, `@login_required`, and `@admin_required` on every endpoint.
- Settings, scheduler logic, encryption-key handling, job leasing, and backup artifact creation live in `functions_data_management.py`.
- Job records are stored in the `data_management_jobs` Cosmos container with partition key `/id`.
- Job and backup history use a `created_at DESC, id DESC` composite index so equal timestamps retain deterministic order across continuation pages.
- Bicep/ARM and Terraform deployments apply this composite index to `data_management_jobs`; the application indexing-maintenance contract also detects or applies it for existing environments.
- Job timeline entries are stored in the `data_management_job_items` Cosmos container with partition key `/job_id`.
- Latest-only backup item state is stored independently in `data_management_backup_item_states` with partition key `/source_scope`. It never updates a source Cosmos record, source ETag, source `_ts`, or source blob metadata.
- Data Management job lifecycle events are also written to the shared `activity_logs` container with `activity_type` set to `data_management`, allowing Control Center Activity Logs to filter and search backup job activity by job ID, operation, backup type, and status.
- Scheduled scans use the existing distributed background task lease pattern with the `data_management_scheduler_scan` lock.

### Durable Backup Jobs

Full and partial backups use the same Cosmos-backed durable job contract as resilient migrations:

- Queueing captures an immutable, normalized, secret-free backup plan, source scope, conservative Cosmos cutoff, storage identity fingerprint, version-pinned Key Vault encryption contract when applicable, and explicit non-destructive deletion policy.
- Each worker attempt receives a lease generation and attempt ID. Source-scoped backup locks prevent full and partial jobs from overlapping across manual requests, scheduled scans, workers, and App Service instances. Long JSONL staging, artifact upload, source-blob download, and source-blob upload calls renew the fenced lease while in flight.
- Resource checkpoints retain bounded counters and rolling batch identities. Per-item outcomes are stored in bounded job-manifest batches plus the latest-only sidecar state, so verified units are not replayed after a restart or focused retry.
- Cosmos exports read deterministic `c.id`-ordered source pages and stream checkpoint-sized JSONL batches. A bounded worker pool stages no more than the configured concurrent batch count while the lease-owning coordinator commits manifests, latest-item state, and checkpoints strictly in source sequence. This avoids materializing whole containers in memory and preserves deterministic retry/resume output.
- Cosmos page reads and batch staging retry `408`, `429`, `449`, and `5xx` responses with bounded exponential backoff, jitter, and `Retry-After` guidance where supplied. Throttle events reduce active staging concurrency; clean completed batches gradually restore it up to the configured limit. Permanent serialization/upload failures are checkpointed as retryable item outcomes rather than silently omitted.
- AI Search exports use independent, bounded JSONL page artifacts under `ai_search/<index>/pages/` rather than a monolithic index JSONL blob. Each supported index validates its captured schema before export: `id` must be the single retrievable, filterable, sortable `Edm.String` key and `upload_date` must be retrievable, filterable, and sortable.
- Search pages use `upload_date` source windows from the immutable backup cutoff and partial-backup lower bound, capture an index-specific upper `id`, then advance with `id gt last_committed_id and id le upper_id` ordered ascending. This avoids deep `skip` paging and supports restart from the last committed page without duplicate or omitted manifest outcomes.
- Search page reads and uploads are scheduled across indexes with at most one page in flight per index. The immutable Search execution plan records the bounded concurrency, retry budget, page size, and clean-page recovery threshold. `429` and `503` responses honor `Retry-After`, reduce active concurrency, and clean pages gradually restore it.
- Page uploads, manifest outcomes, checkpoints, and latest-only state acknowledgements commit in that order through the lease-owning coordinator. Per-index checkpoints retain the source window, upper key, last committed key, next page, bounded recent parts, counts, retries, throttles, and bytes. Raw key cursors remain durable-only and are not exposed in admin progress.
- Azure AI Search does not provide a transactional snapshot. The date window and upper key bound make traversal deterministic, while missing, duplicate, out-of-order, out-of-window, or schema-incompatible documents fail that index's integrity check. Incomplete indexes are retained for diagnostics/resume but marked unavailable for restore-ready output; other indexes continue.
- Queued jobs cancel immediately. Running jobs stop cooperatively at a durable boundary; already verified work remains available for Retry or Resume.
- The scheduler resubmits delayed queued and stale backup jobs through the executor. Scheduled runs defer when another active backup owns the same source scope instead of overlapping it. Pending source-capacity restoration is claimed only by the newly fenced recovery attempt and runs before storage or encryption initialization.
- Backup progress and job timelines expose bounded resource counters, warnings, failed/skipped summaries, attempt history, checkpoint counts, source page position, request units, retries/throttles, elapsed time, records/sec, and RU/sec. They do not expose settings, credentials, source content, ARM routing, SAS query strings, signed artifact URLs, or provider error strings containing secrets.

### Cosmos Backup Performance and Source Capacity

The Backup card provides opt-in controls for Cosmos batch staging concurrency (1-16), retry attempts (1-10), a source capacity failure policy, and a temporary local/source Cosmos throughput boost capped at **10,000 RU/s**.

- Each queued backup records its concurrency, retry, boost, target RU, and failure policy in its immutable plan. Retrying the job uses that recorded plan rather than current settings.
- Before a source boost, the job discovers whether the source has shared database throughput or dedicated container throughput and persists the exact original mode/value for every target before any mutation.
- A boost applies only to eligible manual or autoscale database/container throughput at or below 10,000 RU/s. Serverless, shared/dedicated layouts without an eligible throughput resource, and capacity values already above the SimpleChat cap cannot be managed by the job.
- The `continue_without_boost` policy records a warning and runs the backup at current capacity when ARM capacity discovery or mutation is denied or unsupported. The `fail` policy stops before export so administrators can correct capacity permissions or topology first.
- Every applied boost records `restore_pending` before mutation. Completion, cancellation, worker failure, stale-worker recovery, and scheduler recovery attempt restoration in a fenced `finally` path. Restore writes only when the live capacity still equals this job's boosted value; an external post-boost change is preserved and reported instead of overwritten.
- A stale worker cannot restore capacity from a newer attempt because restore ownership includes the current backup attempt ID and lease generation. Unresolved restoration remains durable and retryable until a new fenced attempt restores or explicitly reports the current external capacity.

Temporary capacity can increase Cosmos DB charges and can affect workload behavior. Use it only during an approved maintenance window, start with the default bounded concurrency, and inspect retry/throttle telemetry before increasing parallelism.

The latest-only sidecar records source identity and version, backup lineage, job/attempt and lease generation, checkpoint/artifact identity, timestamp, terminal outcome, and bounded failure or skip summary for Cosmos records, AI Search documents, and source blobs. Backup lineage is derived from the immutable destination and encryption identity, so a changed destination or key cannot reuse another destination's differential state. Attempts remain historical job-record data; the sidecar stores only the latest outcome for each source item.

### Differential and Restore Semantics

- **Full backup** captures an immutable upper source cutoff and exports a complete source snapshot within that cutoff. Cosmos uses a conservative whole-second boundary (`_ts` strictly before the captured second) because Cosmos `_ts` has second precision.
- **Partial backup** compares each source identity/version against latest-only state. New, changed, previously failed, and untracked items are eligible; unchanged successful items are recorded as skipped.
- Partial state does not mutate source objects and does not rely on advancing source metadata. This keeps later restore work compatible with original Cosmos ETags and `_ts` values and Blob Last-Modified values.
- Deletions are explicit and non-destructive by default. A source item absent from a later backup is not treated as a delete operation, and backup manifests record `deletion_policy: none` for restore workflows.
- Independent item or resource failures remain visible as warnings and retryable checkpoints. A completed job can finish with warnings while preserving failed resources for focused retry.

### Backup Artifacts

Backup jobs write JSON/JSONL artifacts to the configured Azure Blob Storage container:

- Cosmos DB app data for settings, users/groups/workspaces, conversations, documents, agents, actions, prompts, and workspace identities.
- AI Search schemas and retrievable index documents for personal, group, and public indexes. Search documents are stored as deterministic page parts with schema fingerprints, source-window metadata, bounded part summaries, integrity status, and concurrent-write semantics in the artifact manifest.
- Optional source document blob backup can be enabled from the admin UI.
- Source document blobs use bounded concurrent Azure SDK block transfer,
  source/target version verification, durable per-file outcomes, adaptive
  throttling, and `raw-v1` or authenticated `fernet-chunked-v1` artifacts. See
  [Data Management Source Blob Backup Throughput](DATA_MANAGEMENT_BLOB_BACKUP_THROUGHPUT.md).
- A manifest records artifact paths, app version, backup type, encryption status, and warnings.

### Job History and Backup Inventory

The Data Management tab shows two complementary historical views:

- **Backup Inventory** leads with available backups, then full and partial backup filters. The inventory table summarizes completed jobs by backup identity, contents, storage/manifest state, protection, warning count, and a View Log action.
- **Job History** lists recent Data Management jobs with status, progress, message, and a View Log action. The detail modal shows a live progress bar while queued or running, then structured sections for timeline events, backup contents, storage/manifest details, and warnings.
- Both lists request one bounded server page at a time instead of materializing a fixed 25- or 100-record slice in the browser. Page size supports 10, 25, 50, or 100 records.
- Job History filters by operation, status, scheduled/manual run type, and an optional created-date range of at most 366 days. Backup Inventory filters by backup type, status, scheduled/manual run type, and the same bounded date range.
- The API returns `pagination.page_size`, `pagination.returned_count`, `pagination.has_more`, and an opaque `pagination.next_token`. Cross-partition history uses a `created_at`/`id` keyset cursor because the Python Cosmos SDK does not support continuation tokens for cross-partition ordered queries. Tokens expire after one hour and are encrypted and bound to the list, normalized filters, page size, and sort contract. Invalid, expired, tampered, or mismatched tokens return a safe validation error without exposing cursor or query details.
- Previous navigation reuses opaque tokens retained only in the current browser session. Changing a filter or page size resets to page 1, while explicit refresh and job-completion refresh preserve the current page when its token remains valid.
- Each list aborts superseded requests and applies a request-generation guard, preventing a slower response for an older page or filter from replacing the latest result.
- Backup summary counts and latest full/partial references come from independent global queries, so they remain correct regardless of page size, active filters, or current page.
- **Advanced Backup Scope** lives inside the Schedule card as a collapsed drawer. It includes the Cosmos DB, AI Search index, and source document blob backup switches with explicit risk guidance because excluding a surface can create incomplete backups for restore or migration.

Full backup details focus on the full snapshot contents: Cosmos containers exported, AI Search schemas/documents exported, optional source blob containers, artifact sizes, item/blob counts, encryption status, manifest location, and warnings.

Partial backup details use the same artifact layout but expose immutable cutoff metadata, latest-only differential state, checkpoint counts, bounded failed/skipped summaries, and retry eligibility. This makes it possible to understand what changed without modifying source records or relying on destructive deletion semantics.

### Migration Workflow

The Migration card supports a guided migration workflow:

- Configure Target Cosmos DB, Target Search, and Target Enhanced Citation Storage, with test buttons for each target service.
- Select whether to migrate no users, all users, or selected users, with optional user document migration.
- Select whether to migrate no groups, all groups, or selected groups, with optional group document migration.
- Select whether to migrate no public workspaces, all public workspaces, or selected public workspaces, with optional public workspace document migration.
- Preview the migration plan to refresh counts and selected IDs before execution.
- Choose New only, Delta / upsert, or explicitly confirmed Mirror with deletions. Delta and mirror pin a compatible completed migration as their prior watermark.
- Run a read-only live inventory preview for estimated create, update, unchanged, delete, missing, not-applicable, and conflict counts. Execution also captures its own durable inventory after the worker acquires the global migration lock.
- Execute Migration queues a durable Data Management migration job. The job history modal shows live progress, per-step timeline events, migrated artifact counts, and warnings.

Migration execution currently copies selected SimpleChat Cosmos records, matching AI Search documents for selected document scopes, and source document blobs when Enhanced Citations source and destination storage are configured.

For durable provenance, destination access probes, collision protection, checkpoint retries, transfer telemetry, and temporary destination Cosmos capacity controls, see [Data Management Migration Resilience](DATA_MANAGEMENT_MIGRATION_RESILIENCE.md).

### Security

- All Data Management routes are admin-only.
- History validation failures return a fixed public message; raw exception text and internal cursor/query details are never returned to the browser.
- Backup storage connection strings, target Cosmos keys, and encryption key references are redacted before being returned to the browser.
- The admin JavaScript uses DOM creation and `textContent` for API-returned job data.
- Browser runtime JavaScript is served from the local SimpleChat static path: `static/js/admin/admin_data_management.js`.
- Encryption uses a generated 256-bit Fernet key. When Key Vault secret storage is available, the key is stored there under the `backup` source; otherwise it is stored in the separate backup settings document.

### Configuration Options

- Scheduled backup enablement.
- Full backup frequency: daily, weekly, every 14 days, or every 30 days.
- Partial backups: daily only.
- Default scheduled time: `03:00` UTC.
- Backup storage authentication: managed identity or connection string.
- Managed identity storage shows the Blob endpoint field.
- Connection string storage shows the connection string field and indicates when a redacted connection string is already saved.
- Backup storage must use a dedicated Azure Storage account. Data Management rejects backup settings or storage tests that match the Enhanced Citations storage connection string or normalized Blob endpoint.
- Source document blob backup is available only when Enhanced Citations is enabled. It defaults on when available and is disabled when Enhanced Citations is off.
- Backup encryption keys can be stored in Key Vault when Key Vault secret storage is enabled. If Key Vault is unavailable, generated keys fall back to the Data Management settings document and the admin UI recommends enabling Key Vault.
- Cosmos backup performance: bounded concurrent JSONL batch staging (default 4, maximum 16), retry attempts (default 5, maximum 10), and `continue_without_boost` or `fail` behavior when optional source capacity management cannot proceed.
- Source blob backup performance: concurrent file transfers (default 4, maximum
  8), bounded chunk size in MiB (default 8, range 1-16), and independent retry
  attempts (default 5, maximum 10).
- Temporary local/source Cosmos capacity boost: disabled by default; capped at 10,000 RU/s and restored from a durable source capacity snapshot.
- Target Cosmos authentication: managed identity or account key.
- Target Cosmos database name: always `SimpleChat`.
- Target Search authentication: managed identity or admin key.
- Target Enhanced Citation Storage authentication: managed identity or connection string.
- Backup scope toggles for Cosmos DB, AI Search, and source document blobs.

The admin portal groups schedule, storage, and encryption controls under a parent **Backup** card. Migration settings are grouped under a separate **Migration** card with an inner **Target Cosmos Database** card.

Data Management settings save through their own API and are excluded from the regular Admin Settings floating Save button. The Data Management Save Settings button is disabled and labeled `Saved` until one of the Data Management controls changes.

## Usage Instructions

1. Open Admin Settings and select the top-level Data Management tab.
2. Configure backup storage using managed identity or a storage connection string.
3. Use Test Storage to validate and create the backup container if needed.
4. Generate an encryption key or let the first encrypted backup generate one automatically.
5. Configure the full backup cadence and scheduled UTC time.
6. Configure Cosmos Backup Performance when needed. Keep the default bounded concurrency for normal workloads; enable the source boost only when the cost, topology, and ARM permissions have been reviewed.
7. Queue a full or partial backup, or use the restore/migration dry-run buttons to create durable orchestration records.
8. Configure and test Target Cosmos, Target Search, and Target Enhanced Citation Storage before running an actual migration.
9. Use the Migration Workflow to choose users, groups, and public workspaces, then decide whether documents, AI Search entries, and source blobs should be included.
10. Choose the synchronization mode, preview live destination changes, and then Execute Migration to queue the job. Mirror mode requires the exact destructive confirmation phrase.
11. Open Advanced backup scope only when you need to alter the default Cosmos DB, AI Search index, or source blob backup surfaces.
12. Use Backup Inventory to see available backups first, filter to full or partial backups, and open View Log for structured backup details.
13. Use Job History to inspect active container, checkpoint position, records, bytes, RU, retries/throttles, rates, capacity restoration state, durable backup cutoff/checkpoint state, completed steps, reconciliation readiness, preview divergence, and artifact contents. Backup and migration detail both provide Retry/Resume and Cancel; migration detail also provides full or failure-only JSONL manifest downloads.

Migration is used when moving SimpleChat data into another SimpleChat environment, rehearsing a cutover, or preparing a controlled environment transfer. The target Cosmos account, authentication type, and optional account key are configurable. The target database name is fixed to `SimpleChat` so future migration apply jobs use the standard SimpleChat container layout.

For managed identity target Cosmos migration, assign this App Service identity Cosmos DB Data Contributor on the target Cosmos account and ensure network access from the application environment.

For optional local/source Cosmos backup capacity management, assign the App Service managed identity only the management-plane actions needed to read Cosmos account/database/container throughput settings, read/write database/container `throughputSettings`, read throughput operation results, run `migrateToAutoscale` when applicable, and read Cosmos metrics. Bicep and Terraform provision the `SimpleChat Cosmos Throughput Operator` custom role with these actions. This role is distinct from Cosmos DB data-plane access and does not grant access to source record content.

## Testing and Validation

- Functional security coverage: `functional_tests/test_data_management_security_patterns.py`.
- History pagination, filtering, deterministic ties, continuation validation, global summary, and sanitization coverage: `functional_tests/test_data_management_history_pagination.py`.
- Cosmos composite-index maintenance coverage: `functional_tests/test_cosmos_wave3a_indexing_maintenance.py`.
- Authenticated pagination, filter reset, refresh preservation, responsive controls, and request-order guard coverage: `ui_tests/test_admin_data_management_settings_ui.py`.
- Backup durability coverage: `functional_tests/test_data_management_backup_durability.py`.
- Parallel Cosmos backup, retry/adaptive pressure, source capacity restoration/recovery, fencing, resume, and sanitized telemetry coverage: `functional_tests/test_data_management_backup_parallelism.py`.
- AI Search keyset paging, >100,000 logical-result traversal, page concurrency, `429`/`503` recovery, resume, latest-state skips, schema/integrity validation, isolated index failure, and sanitized telemetry coverage: `functional_tests/test_data_management_ai_search_backup_export.py`.
- Source blob bounded transfer, encryption, resume, throttling, fencing, and
  failure-isolation coverage:
  `functional_tests/test_data_management_blob_backup_transfers.py`.
- UI/template coverage: `ui_tests/test_admin_data_management_settings_ui.py`.
- Scheduler/recovery, cancellation, retry, coordinator, provenance, and write-fence coverage remains in the focused `functional_tests/test_data_management_*` modules.
- Syntax validation: `python -m py_compile` for modified backend modules and `node --check` for the admin browser module.

## Limitations

- Backup artifact export is implemented for Cosmos DB and AI Search, with optional source blob copying. Restore application remains a follow-up workflow and consumes the recorded non-destructive manifest contract.
- Bicep and Terraform deployments provision `data_management_jobs`, `data_management_job_items`, and `data_management_backup_item_states` so durable job and latest-state storage are available on either IaC path.
- Source capacity boosts are not available for serverless Cosmos, non-scalable shared/dedicated topology, or targets above 10,000 RU/s. Existing source capacity above the cap remains portal-managed and is never reduced by SimpleChat.
- Capacity operations can take time to apply and may be denied by network/RBAC policy. The documented failure policy determines whether the backup continues at existing capacity or fails before export; unresolved `restore_pending` state must be retried before another boost is applied.
- Restore execution is documented separately. Migration apply supports selected SimpleChat Cosmos, Search, and Enhanced Citations Blob surfaces rather than arbitrary Azure resources.
- Search page artifacts are restore-ready only after every page, schema fingerprint, and integrity result agrees. Concurrent writes or deletes inside an active Search window can cause an index to be marked unavailable and require a resume or new backup.

## Version References

- Application version updated in `application/single_app/config.py` to `0.250.102`.
- Functional and UI tests include the same implementation version.