# Data Management Backup and Migration

Implemented in version: **0.241.211**

## Overview

The Data Management feature adds an admin-only portal section for SimpleChat-owned backup, restore preparation, and migration orchestration. It stores its configuration as a separate `backup_settings` document in the Cosmos `settings` container rather than mixing backup secrets and schedules into normal app settings.

## Technical Specifications

### Architecture

- Admin API routes live in `route_backend_data_management.py` and require `@swagger_route(security=get_auth_security())`, `@login_required`, and `@admin_required` on every endpoint.
- Settings, scheduler logic, encryption-key handling, job leasing, and backup artifact creation live in `functions_data_management.py`.
- Job records are stored in the `data_management_jobs` Cosmos container with partition key `/id`.
- Job checkpoints are stored in the `data_management_job_items` Cosmos container with partition key `/job_id`.
- Scheduled scans use the existing distributed background task lease pattern with the `data_management_scheduler_scan` lock.

### Backup Artifacts

Backup jobs write JSON/JSONL artifacts to the configured Azure Blob Storage container:

- Cosmos DB app data for settings, users/groups/workspaces, conversations, documents, agents, actions, prompts, and workspace identities.
- AI Search schemas and retrievable index documents for personal, group, and public indexes.
- Optional source document blob backup can be enabled from the admin UI.
- A manifest records artifact paths, app version, backup type, encryption status, and warnings.

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
- Target Cosmos authentication: managed identity or account key.
- Backup scope toggles for Cosmos DB, AI Search, and source document blobs.

## Usage Instructions

1. Open Admin Settings and select the top-level Data Management tab.
2. Configure backup storage using managed identity or a storage connection string.
3. Use Test Storage to validate and create the backup container if needed.
4. Generate an encryption key or let the first encrypted backup generate one automatically.
5. Configure the full backup cadence and scheduled UTC time.
6. Queue a full or partial backup, or use the restore/migration dry-run buttons to create durable orchestration records.

For managed identity target Cosmos migration, assign this App Service identity Cosmos DB Data Contributor on the target Cosmos account and ensure network access from the application environment.

## Testing and Validation

- Functional security coverage: `functional_tests/test_data_management_security_patterns.py`.
- UI/template coverage: `ui_tests/test_admin_data_management_settings_ui.py`.
- Syntax validation: `python -m py_compile` for modified backend modules and `node --check` for the admin browser module.

## Limitations

- Backup artifact export is implemented for Cosmos DB and AI Search, with optional source blob copying.
- Restore and migration apply logic currently create durable admin job records and warnings; the target import/apply engine is the next implementation layer.

## Version References

- Application version updated in `application/single_app/config.py` to `0.241.211`.
- Functional and UI tests include the same implementation version.