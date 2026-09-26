# Public Reader Downloads Fix

## Issue

In a public workspace whose downloads are turned on, classic offers **Download
file** to every reader. V2 offered downloads only to the workspace's Owner,
Admins and DocumentManagers, so a reader using V2 had to open the classic page
to download a document.

## Root cause

When native public document management arrived (0.261.133), `download` was one
of the management operations, all of which need a manager role. The same rule
fed the workspace context's `can_download`, the list's
`file_downloads_enabled` and each document's actions, and the native download
routes authorized through the manager-only management context. Classic's own
rule (`_authorize_public_document_download`) admits every reader. The group
workspace isn't affected: its classic download is manager-only too.

Fixed in version: **0.261.186**

## Technical details

Files modified:
- `functions_public_document_policy.py`: downloading is a reader-level
  capability, `public_document_download_allowed`: any role that can read the
  workspace, in a status that allows viewing, when downloads are enabled for
  it. `public_document_capabilities` combines it with the management
  operations, and is the one source for the context hint, the list flag and
  each document's actions.
- `functions_public_document_access.py`: the single and batch download routes
  authorize through `require_public_document_download_context` and
  `authorize_public_document_download`, a read-level path. A reader asking for a
  generated artifact awaiting publication gets the same 404 as for a missing
  document (decision 27).
- `functions_workspace_context.py` and `route_backend_public_document_reads.py`:
  `can_download`, the `document_management` hint and `file_downloads_enabled`
  follow the reader capability.

Upload, metadata and tag editing, deletion, extraction and reprocessing stay
manager-only. Content screening holds and the other per-document download
checks are unchanged.

## Validation

- `functional_tests/test_public_document_management.py` (205) and
  `test_public_document_read_apis.py` (131): a reader downloads when downloads
  are on and is refused when they're off, a reader's download of a pending
  artifact is a 404, management stays manager-only, and the batch route.
- `functional_tests/test_public_document_fixture_parity.py` (63) and
  `test_public_context_fixture_parity.py` (252): the fixtures and the context
  hints against the real builder, with downloads on and off.
- `ui_tests/test_v2_public_documents.py` (64 + 1 strict xfail): a reader
  downloads when downloads are on, and sees no Download when they're off.

## Related

- [Public Document Management APIs](../features/PUBLIC_DOCUMENT_MANAGEMENT_APIS.md)
- [V2 Public Document Management](../features/V2_PUBLIC_DOCUMENT_MANAGEMENT.md)
