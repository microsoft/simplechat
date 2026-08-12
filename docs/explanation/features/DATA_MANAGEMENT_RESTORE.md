# Data Management Restore

Implemented in version: **0.250.106**

## Overview

Data Management Restore adds an admin-only recovery workflow for supported SimpleChat backups. Administrators can select a completed Data Management backup, run a preflight review, choose a non-destructive or explicitly confirmed overwrite policy, queue a durable restore job, and monitor progress through the existing Data Management job history.

Restore is designed for deliberate recovery into configured target services. It does not expose backup contents, credentials, SAS URLs, storage keys, Cosmos account keys, Search keys, or internal endpoints to the browser.

## Technical Specifications

### Architecture

- Admin API routes live in `route_backend_data_management.py` under the existing `backend_data_management` Blueprint and require `@swagger_route(security=get_auth_security())`, `@login_required`, and `@admin_required`.
- Restore planning, review, artifact reading, target writes, durable checkpoints, and retry/cancel support live in `functions_data_management.py`.
- Restore checkpoint primitives live in `functions_data_management_restore_state.py`.
- Restore jobs are stored in the existing `data_management_jobs` container with operation `restore`.
- Restore uses the existing `data_management_job_items` timeline and backup-manifest batch records to locate durable artifact paths.
- Restore activity is recorded in Activity Logs with the same Data Management audit path used by backup and migration jobs.

### Restore Policies

- **Create only** is the default and recommended policy. It creates missing target records and blocks or skips existing target collisions instead of overwriting them.
- **Overwrite existing target records** requires a separate confirmation phrase: `RESTORE WITH OVERWRITE`.
- Destructive behavior is never implicit. The UI disables queueing until a restore review is current, the final review acknowledgement is checked, and the overwrite phrase matches when overwrite mode is selected.

### Preflight Review

Restore review validates the selected backup and target before a job is queued:

- Backup job is completed or completed with warnings.
- Manifest exists, has the expected SimpleChat schema, and matches the selected backup job.
- Failed backup resources block restore until the backup is retried or a different backup is selected.
- Partial backups warn that deletion replay is not supported because partial backup deletion policy is non-destructive.
- Target Cosmos DB is reachable and existing container partition keys match SimpleChat's expected contract.
- Target AI Search is reachable and existing indexes can be checked for create-only collisions.
- Target Enhanced Citation Storage is reachable when source blob restore is included.
- Review results are sanitized before returning to the browser.

Ready reviews issue a short-lived, administrator-bound authorization. Job creation reserves that authorization before durable job creation and consumes it before restore execution starts, preventing replay or changed-plan execution.

### Restore Execution

Restore execution runs as a durable Data Management worker:

1. Initializes a secret-free restore plan and checkpoint state.
2. Revalidates the selected backup manifest and target preflight.
3. Restores supported Cosmos DB JSONL artifact batches into configured target Cosmos containers.
4. Restores supported AI Search JSONL artifact pages after ensuring target indexes exist.
5. Restores supported Enhanced Citation source blob artifacts into target storage containers.
6. Persists per-resource progress, warning, collision, skip, failure, and retry counters.

Queued restores can be canceled before execution. Running restores stop cooperatively at durable checkpoints. Failed, canceled, or stale restore jobs can be retried from their recorded restore state without changing the immutable plan.

## Usage Instructions

1. Open **Admin Settings > Data Management**.
2. Configure the target Cosmos DB, AI Search, and Enhanced Citation Storage settings.
3. In **Backup Inventory**, choose **Restore** on a completed backup row.
4. Select the restore policy and included surfaces.
5. Run **Restore Review** and resolve any blockers.
6. Confirm the reviewed plan. If overwrite mode is selected, type `RESTORE WITH OVERWRITE`.
7. Queue the restore job and monitor it in **Job History**.

## Testing and Validation

Coverage includes:

- Restore state immutability and retry safety.
- Destructive overwrite confirmation.
- Manifest preflight blockers and partial-backup warnings.
- Admin-bound restore review authorizations.
- Admin UI restore controls and client-side route wiring.

Known limitations:

- Partial backups remain non-destructive and do not replay deletions.
- Restore requires backup storage and encryption-key access to remain available.
- Create-only restore blocks/skips existing target collisions; use overwrite only during an approved recovery window.
