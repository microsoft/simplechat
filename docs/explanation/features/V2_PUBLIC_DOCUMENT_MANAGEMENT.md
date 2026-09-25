# V2 Public Document Management

## Overview

Implemented in version: **0.261.133**, tracked in
`application/single_app/config.py`.

Public workspace documents can now be managed in the native V2 explorer, not
just browsed. This extends the read-only surface delivered in M3A.

Sharing and generated-artifact approval remain M3C. The endpoint reference is
[Public Document Management APIs](PUBLIC_DOCUMENT_MANAGEMENT_APIS.md).

## Purpose and boundaries

M3A brought public workspace documents into the same explorer used for My
Workspace and group workspaces, but read-only: everything that changed a
document still required the classic page. M3B closes that gap.

Covered: upload, metadata editing, tags and bulk tagging, permitted downloads
both singly and in batches, metadata extraction, reprocessing including the
extraction-mode change, and revision-aware deletion singly and in bulk.

Not covered: sharing, generated-artifact approval, prompts, and workspace
administration such as members, roles, ownership, settings, logo, requests,
statistics, and activity.

## One surface, not a parallel one

The management surface is an extension of the M3A public explorer, and the
operation components are the ones the group workspace already uses.
`documentOperations.ts` became scope-aware rather than being forked into a
public copy, so `personal`, `group`, and `public` share one implementation:

```ts
const base = scope.kind === 'group'
    ? `/api/groups/${encodeURIComponent(requireWorkspaceId(scope.id))}/documents`
    : scope.kind === 'public'
        ? `/api/public-workspaces/${encodeURIComponent(requireWorkspaceId(scope.id))}/documents`
        : '/api/documents';
```

That matters beyond tidiness. A parallel public implementation would be a third
place for the same rule to live, and this project has twice shipped bugs caused
by one copy of a rule falling behind another.

## Receipts are checked for identity

Every operation receipt is validated against the workspace that was asked for,
not merely parsed. The scope field is selected per kind — `public_workspace_id`
for public, `group_id` for group — and a receipt that does not identify the
requested workspace raises rather than rendering as success.

This is the write-side counterpart of the M3A read check. Without it, a late or
misrouted response could be displayed as a successful edit against the wrong
workspace.

Tag vocabulary failures carry the same discipline. A vocabulary error is
accepted only when its identity matches the active scope and it carries no
`document_id`; otherwise the client refuses it and asks for a refresh.

## Ownership has no incoming case

For a public workspace a document is manageable when
`document.public_workspace_id` equals the selected workspace. The "incoming
share" branch that groups use is hardcoded to `false`:

```ts
const incoming = scope.kind === 'public' ? false : /* group share checks */;
```

Public workspaces have no cross-workspace share relationship until M3C, so
encoding that explicitly keeps the operations layer consistent with the facets
layer, which suppresses the Shared place for the same reason.

Deletion requires ownership. Downloads additionally permit an incoming share in
group scope, which public cannot produce. Everything else additionally requires
screening availability and the current revision, and reprocessing requires that
the document supports an extraction-mode change.

## Active workspace state stays non-load-bearing

M3A established that selecting a public workspace records it as active but that
nothing on the page depends on it. That property was free in a read-only slice
because nothing *could* depend on active state.

It is no longer free. It survives because every operation names its workspace in
its own path, so `setActive` continues to be fire-and-forget and never gates
rendering, navigation, reads, **or operations**. The browser suite pins this
directly: a refused `setActive` leaves a metadata edit fully working.

## Capability handling

Affordances are gated on the `document_management` block in the workspace
context together with the per-document `document_actions` array, which stops
being empty in this milestone.

Both remain interface hints. The server revalidates role, workspace status,
revision, screening state, and feature policy on every call. An unknown or
malformed handshake degrades the surface to read-only and never falls back to
personal or group behavior. `document_collaboration` and `native_delegation`
are still absent rather than empty, and absence continues to mean "not
available".

From version **0.261.167**, a reader or other viewer who can't upload is told
who can add documents to an empty workspace, or why no one can right now, in
public-workspace terms rather than the group wording or a classic link it saw
before. A change such a viewer tries is refused the same way, instead of with
the generic per-document message. An unrecognized handshake asks for a refresh.
From version **0.261.168**, a manager who can't upload, because uploads are
disabled or the workspace is locked, is told the same reason when dropping
files.

## File structure

| File | Role |
|---|---|
| `application/v2_ui/src/lib/documentOperations.ts` | Scope-aware operations, URL construction, receipt identity validation |
| `application/v2_ui/src/pages/PublicWorkspacePage.tsx` | Workspace page wiring |
| `application/v2_ui/src/pages/workspace/DocumentsSection.tsx` | Shared documents section |
| `application/v2_ui/src/components/documents/DocumentDialogs.tsx` | Shared operation dialogs |
| `application/v2_ui/src/lib/workspaceContext.ts` | Context including the management block |

## Testing and validation

`ui_tests/test_v2_public_documents.py` covers the public surface with 41 cases:
the 26 read cases from M3A plus 15 management cases.

Run the V2 browser suites together, one process at a time, with `PYTHONPATH`
set:

```powershell
$env:PYTHONPATH = "$PWD;$PWD\ui_tests;$PWD\ui_tests\fixtures"
python -m pytest .\ui_tests\test_v2_public_documents.py `
  .\ui_tests\test_v2_personal_document_scope.py `
  .\ui_tests\test_v2_group_documents.py `
  .\ui_tests\test_v2_group_document_management.py `
  .\ui_tests\test_v2_group_document_collaboration.py `
  .\ui_tests\test_v2_group_workspace_shell.py -q --disable-warnings
```

**168 passed** at the integration commit, alongside `npm run build` in
`application/v2_ui`. Because the scope-aware refactor touches shared code, the
group management and collaboration suites are the regression net that matters
most here, and both stay green.

`ui_tests/test_v2_personal_document_scope.py` remains the isolation baseline:
selecting or operating in a public workspace must never leak into personal
reads.

## Related

- [V2 Public Document Browsing](V2_PUBLIC_DOCUMENT_BROWSING.md) — the M3A read surface
- [Public Document Management APIs](PUBLIC_DOCUMENT_MANAGEMENT_APIS.md) — the server endpoints
- [Public Document Read APIs](PUBLIC_DOCUMENT_READ_APIS.md)
- [V2 Group Document Management](V2_GROUP_DOCUMENT_MANAGEMENT.md) — the M2B equivalent
