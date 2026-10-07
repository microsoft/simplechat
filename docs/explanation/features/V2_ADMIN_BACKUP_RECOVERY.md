# V2 Admin Backup & Recovery

## Overview

V2 Admin Settings listed the Backup & Recovery group, but selecting it showed
"No settings match". The group's nine sections had no fields to render, because the
classic page draws them with its own JavaScript over a separate data-management API.
An administrator using V2 could not back up, restore, migrate, repair a Cosmos DB
document, or follow a job without switching to the classic page.

This change gives every section a V2 card with the same capabilities as the classic
page, built in the V2 design language: section cards with a status chip, list-and-detail
workbenches like the Model Catalog, the page's Save bar, and typed confirmations for
destructive actions. The copy is written for V2 rather than carried over word for word.

## Implemented in version: **0.261.274**

The application version is maintained in `application/single_app/config.py`.

**Dependencies:** the React/TypeScript V2 UI, `zustand`, local `lucide-react` icons,
Tailwind container queries, `admin_settings_nav.py`, `admin_settings_fields.py`, and the
existing admin-only `/api/admin/data-management/*` routes, which are unchanged. No new
packages, settings, routes, or browser asset sources are required.

## Technical specifications

### Architecture

Each navigation section declares one `component` field in `admin_settings_fields.py`,
and `AdminSettingsPage.tsx` renders it through a `case` branch. `SettingsSection` draws
the card shell (title, icon, status chip); each component renders only the card body.

| Section | Component | What the card does |
| --- | --- | --- |
| Start Here | `data-management-readiness` | Readiness checklist with links to each section, operational warning, guides |
| Backup | `data-management-backup-runs` | Queue full or partial backups, latest results, backup performance and source RU Boost |
| Schedule | `data-management-schedule` | Schedule, retention, partial backups, backup scope |
| Storage | `data-management-storage` | Backup storage account, container and path prefix, storage test |
| Encryption | `data-management-encryption` | Encryption switch, key storage readout, key generation and replacement |
| Migration | `data-management-migration` | Six-step migration wizard and live progress |
| Backup Inventory & Restore | `data-management-backup-inventory` | Backup workbench, restore dialog, delete, retention cleanup |
| Cosmos Editor | `data-management-cosmos-editor` | Locked JSON editor with query, open, and guarded save |
| Jobs | `data-management-jobs` | Job history workbench with live detail, retry or resume, and cancel |

State lives in `stores/dataManagementStore.ts`, a zustand store that outlives individual
cards. The page unmounts a card whenever a category or search hides it, so unsaved
settings, a migration in progress, and an unlocked Cosmos editor document are kept in
the store for the lifetime of the Admin Settings page. The page calls `reset()` when it
unmounts. `reset()` advances an epoch, and every asynchronous write checks the epoch
first, so a request that finishes after the administrator leaves cannot write into the
next visit.

The section status chips come from `dmSectionStatuses`: the schedule is off or ready,
storage is incomplete or ready, encryption is off, incomplete, or ready, and Backup is
blocked while storage is missing.

### Save model

The data-management settings are their own document, saved with
`PUT /api/admin/data-management/settings`.

- **One Save bar.** Unsaved Backup & Recovery edits count in the page's Save bar.
  **Save changes** sends the main settings `PATCH` first and the Backup & Recovery `PUT`
  second, and reports which part failed if one does. **Discard** clears both drafts.
- **The whole document, as the classic page sends it.** The `PUT` carries exactly the 42
  keys the classic `collectSettings()` sends. The server stores any extra key it is
  given, so nothing else is ever sent, including `encryption_key_reference`. Only the
  credential for the selected sign-in mode is sent, and an untouched secret is sent as
  the `***REDACTED***` placeholder, which keeps the stored value.
- **Save first.** Queueing a backup, running retention cleanup, reviewing or queueing a
  restore, and starting a migration act on the saved settings: the server reads them
  again and recomputes review fingerprints from them. These actions save pending
  Backup & Recovery edits first, as the classic page does, and their buttons say so.
  Retry and Resume never save, because a resumed backup is refused if its storage
  settings have changed since it was queued.
- **Cross-document guard.** Backup storage is validated against the *saved* Enhanced
  Citations storage settings, and a generated key is stored where the *saved* Key Vault
  settings say. When `enable_enhanced_citations`, `office_docs_storage_account_url`,
  `office_docs_storage_account_blob_endpoint`, `enable_key_vault_secret_storage`, or
  `key_vault_name` has an unsaved edit, the action offers **Save all and continue**
  instead of being checked against a value that is about to change.
- **Leaving the page.** `useBlocker` asks before a client-side navigation leaves unsaved
  changes, an edited Cosmos document, or a request that is still being sent.

### Reviews, confirmations, and concurrency

| Workflow | Contract |
| --- | --- |
| Restore | The review is keyed to the backup, policy, selected surfaces, and the matching destination endpoints and sign-in modes. Only selected surfaces require destinations: Cosmos DB needs the target Cosmos DB endpoint, AI Search needs the target AI Search endpoint, and source files need the target Enhanced Citation storage Blob endpoint or connection string for the selected storage sign-in mode. Queueing needs a passing, current review, its authorization token (15 minutes), an acknowledgement, and `RESTORE WITH OVERWRITE` for the overwrite policy. Each opening of the dialog starts from a clean draft. |
| Migration | The review is keyed to the plan and the destination and migration settings. Choosing All for a principal type requests a server count; a failed count offers **Retry count** and does not block the step, because the server review counts the records itself. When all included types are counted and total 0, the Scope step blocks review. The Confirm step displays the server-normalized review summary for principal scopes, included documents, synchronization mode, creates and updates, deletes, and conflicts. The mirror phrase `MAKE DESTINATION MATCH SOURCE` is entered after the review and is not part of the key, matching the server's fingerprint. A typed destination secret is masked when settings are saved; the review stays current because it was run against exactly what was saved, and the server still compares its own fingerprint. A `409` or a `workflow_step` of `review` returns to the Review step with the server's reason. |
| Cosmos Editor | Unlocking records an acknowledgement. Saves send the opened ETag, `confirmation_accepted`, and `I understand this can damage system data`; a `409` offers a reload. Editing the query or page size drops the previous continuation token. A failed or empty container list waits for **Load containers** rather than retrying on its own. |
| Jobs | Detail and progress requests are applied only while the same job is selected. A running job is polled every 2 seconds until it finishes. Retry, Resume, and Cancel follow the server's `can_retry` and `can_cancel`. |

### API endpoints

All endpoints are the existing admin-only routes in `route_backend_data_management.py`.

| Method | Path | Used for |
| --- | --- | --- |
| `GET`, `PUT` | `/api/admin/data-management/settings` | Load and save the settings document |
| `POST` | `/api/admin/data-management/encryption-key` | Generate or replace the backup key |
| `POST` | `/api/admin/data-management/storage/test` | Test backup storage without saving |
| `POST` | `/api/admin/data-management/target/cosmos/test`, `/target/cosmos/ru-boost/test`, `/target/search/test`, `/target/enhanced-citation-storage/test` | Test the migration and restore destination |
| `GET` | `/api/admin/data-management/backups` | Backup inventory and the latest-backup summary |
| `POST` | `/api/admin/data-management/backups/retention/cleanup` | Run retention cleanup |
| `DELETE` | `/api/admin/data-management/backups/<id>` | Delete one backup |
| `POST` | `/api/admin/data-management/restore/review` | Restore preflight review |
| `POST` | `/api/admin/data-management/migration/review` | Migration preflight review |
| `GET` | `/api/admin/data-management/migration/catalog/<type>` | Search users, groups, and public workspaces |
| `GET`, `POST` | `/api/admin/data-management/jobs` | Job history; queue a backup, restore, or migration |
| `GET` | `/api/admin/data-management/jobs/<id>`, `/jobs/<id>/progress` | Job detail and live progress |
| `POST` | `/api/admin/data-management/jobs/<id>/retry`, `/jobs/<id>/cancel` | Retry or resume; request cancellation |
| `GET` | `/api/admin/data-management/jobs/<id>/migration-manifest` | Download a migration manifest |
| `POST`, `GET`, `PUT` | `/api/admin/data-management/cosmos-editor/*` | Acknowledge, list containers, query, open, and save |

### File structure

| File | Purpose |
| --- | --- |
| `application/v2_ui/src/lib/dataManagement.ts` | API wrappers, response types, phrases, editable keys, defaults, and bounds |
| `application/v2_ui/src/lib/dataManagementLogic.ts` | Pure logic: values and payload, validation, statuses, review keys, gates, formatting |
| `application/v2_ui/src/lib/dataManagementFields.ts` | Field declarations and V2 copy for the settings the cards edit |
| `application/v2_ui/src/stores/dataManagementStore.ts` | Shared state, save, save-first readiness, epoch |
| `application/v2_ui/src/components/admin/dataManagement/` | The nine cards, the restore dialog, migration steps, job detail, guides, and shared parts |
| `application/v2_ui/src/pages/AdminSettingsPage.tsx` | Renderer cases, combined Save bar, save coordinator, leave guard |
| `application/single_app/admin_settings_fields.py` | One `component` field per Backup & Recovery section, with search keywords |
| `application/single_app/admin_settings_nav.py` | The "Backup Inventory & Restore" label no longer shows a literal `&amp;` |

`adminFields.ts` adds an optional `keywords` list to a field, so the settings search
finds a card by the settings it contains.

## Usage

1. Open **Admin Settings** and choose **Backup & Recovery**. Start Here shows what is
   ready and opens the section for anything that is not.
2. Configure **Storage** and **Encryption**, then queue a full backup from **Backup**
   and check that it appears in **Backup Inventory & Restore**.
3. Turn on **Schedule** when manual backups work, and set the retention window.
4. To restore, select a backup in the inventory, choose **Restore…**, run the review,
   acknowledge it, and queue the restore. The job opens in **Jobs**.
5. To migrate, follow the Migration steps in order. The Confirm step opens only after a
   current review.

The full administrator reference is `docs/admin/backup-recovery.md`.

## Testing and validation

### Coverage

- `functional_tests/test_v2_admin_backup_recovery.py` checks that every component is
  declared, searchable, and routed; that the Save bar saves main settings first and
  guards navigation; that the new code uses no HTML sinks; and runs the 38 checks in
  `test_v2_admin_backup_recovery_logic.ts` against the real logic module. Every declared
  check must report `ok`.
- `functional_tests/test_v2_admin_backup_recovery_parity.py` compares the editable keys,
  defaults, and number bounds with the server.
- `functional_tests/test_v2_admin_capability_placement.py` and
  `test_v2_admin_field_renderer_coverage.py` include the new group.
- `ui_tests/test_v2_admin_backup_recovery.py` runs the V2 browser coverage against an in-memory
  copy of the data-management API (`ui_tests/fixtures/v2_admin_data_management.py`): every
  card in light and dark themes; the Save bar, discard, and a rejected save; save-first
  ordering for backups, retention cleanup, restore, and migration; retry never saving;
  the cross-document guard for backup storage and key generation; restore and migration
  reviews, staleness, phrases, and `409` handling; job polling and cancellation; the
  Cosmos editor's unlock, save, conflict, container retry, and continuation token; the
  leave guard; switching categories without inventing changes or losing a pending edit;
  and no overflow at 390px or 1920px.

### Performance

Inventory and job history load when their card first scrolls into view. Start Here and
Backup share one latest-backup read per page visit, refreshed after a job changes the
inventory. Job progress is polled every 2 seconds only while a selected job is running,
and the Migration progress step does the same for its job.

### Known limitations

- `low_impact_mode` is stored but not read by the backend, so its help text makes no
  claim about what it changes.
- Migration and restore use the same destination settings, so preparing one changes the
  other.
- A review authorization lasts 15 minutes; after that the review must be run again.
