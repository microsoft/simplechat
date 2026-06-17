# Data Management Backup and Migration

Implemented in version: **0.241.211**
Updated in version: **0.241.221**

## Overview

The Data Management feature adds an admin-only portal section for SimpleChat-owned backup, restore preparation, and migration orchestration. It stores its configuration as a separate `backup_settings` document in the Cosmos `settings` container rather than mixing backup secrets and schedules into normal app settings.

## Technical Specifications

### Architecture

- Admin API routes live in `route_backend_data_management.py` and require `@swagger_route(security=get_auth_security())`, `@login_required`, and `@admin_required` on every endpoint.
- Settings, scheduler logic, encryption-key handling, job leasing, and backup artifact creation live in `functions_data_management.py`.
- Job records are stored in the `data_management_jobs` Cosmos container with partition key `/id`.
- Job timeline entries are stored in the `data_management_job_items` Cosmos container with partition key `/job_id`.
- Data Management job lifecycle events are also written to the shared `activity_logs` container with `activity_type` set to `data_management`, allowing Control Center Activity Logs to filter and search backup job activity by job ID, operation, backup type, and status.
- Scheduled scans use the existing distributed background task lease pattern with the `data_management_scheduler_scan` lock.

### Backup Artifacts

Backup jobs write JSON/JSONL artifacts to the configured Azure Blob Storage container:

- Cosmos DB app data for settings, users/groups/workspaces, conversations, documents, agents, actions, prompts, and workspace identities.
- AI Search schemas and retrievable index documents for personal, group, and public indexes.
- Optional source document blob backup can be enabled from the admin UI.
- A manifest records artifact paths, app version, backup type, encryption status, and warnings.

### Job History and Backup Inventory

The Data Management tab shows two complementary historical views:

- **Backup Inventory** leads with available backups, then full and partial backup filters. The inventory table summarizes completed jobs by backup identity, contents, storage/manifest state, protection, warning count, and a View Log action.
- **Job History** lists recent Data Management jobs with status, progress, message, and a View Log action. The detail modal shows a live progress bar while queued or running, then structured sections for timeline events, backup contents, storage/manifest details, and warnings.
- **Advanced Backup Scope** lives inside the Schedule card as a collapsed drawer. It includes the Cosmos DB, AI Search index, and source document blob backup switches with explicit risk guidance because excluding a surface can create incomplete backups for restore or migration.

Full backup details focus on the full snapshot contents: Cosmos containers exported, AI Search schemas/documents exported, optional source blob containers, artifact sizes, item/blob counts, encryption status, manifest location, and warnings.

Partial backup details use the same artifact layout but also expose the partial selection metadata, including Cosmos `_ts` lower-bound epochs and AI Search date filters where available. This makes it possible to understand what changed since the previous full or partial backup window.

### Migration Workflow

The Migration card supports a guided migration workflow:

- Configure Target Cosmos DB, Target Search, and Target Enhanced Citation Storage, with test buttons for each target service.
- Select whether to migrate no users, all users, or selected users, with optional user document migration.
- Select whether to migrate no groups, all groups, or selected groups, with optional group document migration.
- Select whether to migrate no public workspaces, all public workspaces, or selected public workspaces, with optional public workspace document migration.
- Preview the migration plan to refresh counts and selected IDs before execution.
- Execute Migration queues a durable Data Management migration job. The job history modal shows live progress, per-step timeline events, migrated artifact counts, and warnings.

Migration execution currently copies selected SimpleChat Cosmos records, matching AI Search documents for selected document scopes, and source document blobs when Enhanced Citations source and destination storage are configured.

### Security

- All Data Management routes are admin-only.
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
6. Queue a full or partial backup, or use the restore/migration dry-run buttons to create durable orchestration records.
7. Configure and test Target Cosmos, Target Search, and Target Enhanced Citation Storage before running an actual migration.
8. Use the Migration Workflow to choose users, groups, and public workspaces, then decide whether documents, AI Search entries, and source blobs should be included.
9. Preview the migration plan, then Execute Migration to queue the job.
10. Open Advanced backup scope only when you need to alter the default Cosmos DB, AI Search index, or source blob backup surfaces.
11. Use Backup Inventory to see available backups first, filter to full or partial backups, and open View Log for structured backup details.
12. Use Job History to inspect live progress, completed steps, warnings, storage/manifest details, and artifact contents for any Data Management job.

Migration is used when moving SimpleChat data into another SimpleChat environment, rehearsing a cutover, or preparing a controlled environment transfer. The target Cosmos account, authentication type, and optional account key are configurable. The target database name is fixed to `SimpleChat` so future migration apply jobs use the standard SimpleChat container layout.

For managed identity target Cosmos migration, assign this App Service identity Cosmos DB Data Contributor on the target Cosmos account and ensure network access from the application environment.

## Testing and Validation

- Functional security coverage: `functional_tests/test_data_management_security_patterns.py`.
- UI/template coverage: `ui_tests/test_admin_data_management_settings_ui.py`.
- Syntax validation: `python -m py_compile` for modified backend modules and `node --check` for the admin browser module.

## Limitations

- Backup artifact export is implemented for Cosmos DB and AI Search, with optional source blob copying.
- Restore and migration apply logic currently create durable admin job records and warnings; the target import/apply engine is the next implementation layer.

## Version References

- Application version updated in `application/single_app/config.py` to `0.241.221`.
- Functional and UI tests include the same implementation version.