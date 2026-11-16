# File Source Browse Path Fix (v0.261.171)

## Issue

**Browse** in the V2 group file source editor didn't work for SMB sources.
Every browse answered an error. Choosing an entry in the list also replaced the
source's root path with that entry's path, so saving afterwards could change
what the source synced.

Fixed in version: **0.261.171**, tracked in `application/single_app/config.py`.

## Root cause

- The browse routes resolve `browse_path` **under the source's root**. For a
  source rooted at `\\files\contracts\team`, `browse_path` names a folder
  inside that root.
- The V2 editor sent the root field's own value as `browse_path`. The server
  therefore looked for `\\files\contracts\team\files\contracts\team`, and every
  SMB browse failed with a 500.
- Choosing an entry wrote the entry's root-relative path into the root field.
- The browser fixture listed children under any path it was given, so the
  browser suite passed. `test_browse_opens_a_folder_by_type` even pinned the
  broken request.

The V2 group file source editor shipped in version 0.261.147, so versions
0.261.147 through 0.261.170 are affected.

## Technical details

### The change

- Browse starts at the root (no `browse_path`), and opens a folder by its path
  under the root. **Up one folder** goes back.
- Choosing an entry never changes the root; it selects the entry for **What to
  sync**. The same release adds that field to the editor; see
  [V2 Group File Sources](../features/V2_GROUP_FILE_SOURCES.md).

### Files modified

| File | Change |
| --- | --- |
| `application/v2_ui/src/components/fileSources/FileSourceEditorDialog.tsx` | Browse from the root, open folders by their path under it, **Up one folder**, and select instead of overwriting the root |
| `application/v2_ui/src/lib/fileSourceFields.ts` | Path helpers for the browse location and the selection |
| `ui_tests/fixtures/group_workspace.py` | The browse fixture resolves paths over a small tree under the root, and answers the server's 500 or 400 for anything else, as the real routes do |
| `functional_tests/test_group_file_source_fixture_parity.py` | Browse compared by how paths resolve: 5 listings and 5 refusals |
| `ui_tests/test_v2_group_file_sources.py` | The browse test now checks the request and that the root is kept |

## Validation

- The browse parity cases run the real browse route through the file source
  harness, and fail against the old fixture.
- A mutation that sends the root as the first `browse_path` fails the browser
  suite, and so does one that lets a selection overwrite the root.

## Related

- [V2 Group File Sources](../features/V2_GROUP_FILE_SOURCES.md)
- [Group File Source APIs](../features/GROUP_FILE_SOURCE_APIS.md)
