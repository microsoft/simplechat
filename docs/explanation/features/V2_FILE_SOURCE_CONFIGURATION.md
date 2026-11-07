# V2 File Source Configuration - 0.261.310

## Overview

Implemented in version: **0.261.310**, recorded in
`application/single_app/config.py`. Refs
[#1722](https://github.com/microsoft/simplechat/issues/1722), row 4.

Personal, group and public workspaces create and configure file sources
without opening a classic page. This removes the personal workspace's
configuration hand-off and reuses the already-native group/public editor.
File-source workflows no longer depend on legacy-page access in New UI only
mode; this change does not implement the separate legacy routing policy.

Dependencies are the existing File Sync engine, Redis readiness, workspace
permissions, approved connectors and stored credentials or eligible identities.
No browser libraries, admin settings or connector types are added.

## Technical specifications

`FileSourcesWorkbenchSection` supplies the shared list and editor lifecycle.
`FileSourceEditorDialog` and `fileSourceFields.ts` keep connection, credential,
selection and filtering behavior identical across scopes. Each adapter uses
its scope's routes and response envelopes:

| Scope | Sources | Options | Response keys |
|---|---|---|---|
| Personal | `/api/file-sync/personal/sources` | `/api/file-sync/personal/source-options` | `sources`, `source` |
| Group | `/api/groups/<id>/file-sources` | `/api/groups/<id>/file-source-options` | `file_sources`, `file_source` |
| Public | `/api/public-workspaces/<id>/file-sources` | `/api/public-workspaces/<id>/file-source-options` | `file_sources`, `file_source` |

The personal source family adds a single-source GET for a fresh editor
baseline. Options return visible implemented connectors, same-scope identity
IDs, recursion policy, schedule limits, source limits and the new-source remote
delete default. They never return raw settings or secrets.

Personal writes include the additive `expected_config_revision` token;
PATCH/DELETE callers without it remain compatible. The revision covers
configuration, not sync-run progress. A configuration conflict keeps the
draft and offers reload/merge; an etag-only write conflict permits retry.
Fresh secret references are staged, discarded on refused writes, and replace
old secrets only after a committed save. Browser projections expose stored
secret flags, never stored credentials or Key Vault references.

Personal targets come from the authenticated user, including session roles
for admin-only/app-role policies. Group/public requests remain bound to their
immutable workspace ID and require management hints and row actions. Locked
or upload-disabled shared workspaces remain read-only.

## Usage

Choose **File sources → New file source**, or use **Edit** on a saved source.
Use a same-workspace identity or source-local credentials. SMB supports
anonymous and username/password; Azure storage supports managed identity,
service principal and connection string/SAS authentication.

**Test connection** and **Browse the source** use the unsaved draft. Select
root-relative folders/files, or leave the selection empty to import the root.
Configure recursion, filename patterns, extensions, fixed/folder tags, remote
deletions, enabled state and scheduling. Creation saves without starting a sync.
Ignore/Restore is an immediate operation on a saved source and uses the
server's canonical remote file path, not the browse-relative path.

Editing retains blank stored secrets. Reload after a conflict preserves locally
edited fields and adopts untouched remote changes. A deleted source cannot be
saved, tested, browsed or ignored. Loading failures offer retry; optional tag
suggestions can fail without preventing a typed tag.

Connection changes discard stale test/browse feedback. Cancel/Escape protects
unsaved work, and focus returns to the original action after the dialog closes.
The editor uses the existing light/dark theme and scrollable mobile modal.

See [Create a file sync](../../guides/create-a-file-sync.md) for the workflow.

## Testing and limitations

- `functional_tests/test_personal_file_source_apis.py` exercises real routes,
  ownership, capability/role policies, connector/auth round trips, conditional
  writes, secret staging, delete outcomes and classic compatibility.
- `functional_tests/test_v2_personal_file_sources.py` executes the real adapter
  and shared serializers, including exact transport, malformed responses and
  existing OneDrive configuration safety.
- `ui_tests/test_v2_personal_file_sources.py` exercises the production SPA;
  existing group/public suites cover shared-scope gates, editing and deletion.
- Route policy tests cover both new personal reads. Fixture parity checks
  keep options aligned with the actual backend.

New connector availability stays administrator-controlled: SMB, Azure Files
and Azure Blob are the implemented selectable types. An existing personal
OneDrive source retains selected paths and the administrator-managed global
connector; V2 does not enable new OneDrive or coming-soon sources. Identity
creation is separate work.

The checked-out app still uses the `/v2` basename. Live root-hosted/Teams
validation and New UI only enforcement depend on the companion routing work
and a configured deployment; synthetic tests do not claim those checks.
