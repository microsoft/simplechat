# File Source Browse Ignore Fix (v0.261.172)

## Issue

In the V2 group file source editor, **Ignore** on a browsed file had no effect:
the file kept syncing. **Restore** did nothing either. Folders were offered
**Ignore** too, which the sync engine can't honour.

Fixed in version: **0.261.172**, tracked in `application/single_app/config.py`.

## Root cause

- The ignore route records the ignore on the sync item keyed by
  `_item_id_for_path(source_id, remote_path)`.
- The sync engine keys each file's item by the file's **full** remote path, for
  example `\\files.example.test\reports\budget.xlsx` for SMB, or the blob's full
  URL for Azure Blob.
- Browse returned each entry's path **relative to the source's root**, for
  example `budget.xlsx`, and V2 sent that path to the ignore route. The
  ignore was stored on an item the engine never reads.
- The engine keeps items only for files, so a folder's ignore never mattered.

Classic has no browse-based ignore; ignore and restore from Browse arrived with
the V2 editor in version 0.261.147.

## Technical details

### The change

- **Server** (`functions_file_sync.py`): browse gives every **file** entry a
  `remote_path`, built with the same helper each source type's lister uses for
  the path it keys the item by:
  - SMB: `_join_smb_path`;
  - Azure Files: `_build_azure_files_url` over the full share path;
  - Azure Blob: `_build_azure_blob_url` over the full blob name;
  - OneDrive: the engine's own `_onedrive_remote_file_from_item`.

  Folders carry none. The ignore route is unchanged.
- **Client** (`FileSourceEditorDialog.tsx`, `lib/types.ts`): **Ignore** and
  **Restore** send the entry's `remote_path`, and appear only on entries that
  have one. The client joins no paths itself.
- The server owns the path rules, so the client can't drift from the engine.

### Files modified

| File | Change |
| --- | --- |
| `application/single_app/functions_file_sync.py` | `remote_path` on file entries, for each browsable source type |
| `application/v2_ui/src/components/fileSources/FileSourceEditorDialog.tsx` | Ignore and Restore send `remote_path`, on files only |
| `application/v2_ui/src/lib/types.ts` | The browse entry's `remote_path` |
| `ui_tests/fixtures/group_workspace.py` | The fixture builds `remote_path` with the engine's helpers and keys ignored items as the server does |
| `functional_tests/test_support/group_file_source_harness.py` | Loads the real Azure endpoint validation, whose stub had kept any Azure Blob source from being saved in the harness |

### Tests

- `functional_tests/test_group_file_source_sync_fields.py`:
  - ignoring a browsed file reaches the item the engine syncs, and restoring it
    clears the ignore;
  - every browsed file carries the path the engine keys it by, for SMB, Azure
    Files and Azure Blob;
  - OneDrive at function level;
  - a root-relative path still reaches no engine item.
- `functional_tests/test_group_file_source_fixture_parity.py`: file entries'
  `remote_path` on saved and unsaved browse, and an ignore keying the same item
  on both sides.
- `ui_tests/test_v2_group_file_sources.py`: ignore, then restore, tracks the
  returned item.
- Mutations: 16 of 16 killed across the server, the fixture and the client.

## Validation

- Before: ignoring `budget.xlsx` stored an ignore the engine never read, and the
  file synced again on the next run.
- After: the ignore is stored on the file's own item, and the next run skips
  it.

## Related

- [V2 Group File Sources](../features/V2_GROUP_FILE_SOURCES.md)
- [Group File Source APIs](../features/GROUP_FILE_SOURCE_APIS.md)
- [File Source Browse Path Fix](FILE_SOURCE_BROWSE_PATH_FIX.md)
