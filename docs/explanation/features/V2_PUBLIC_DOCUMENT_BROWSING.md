# V2 Public Document Browsing

## Overview

Implemented in version: **0.261.132**, tracked in
`application/single_app/config.py`.

Public workspace documents can now be browsed in the same native explorer used
for My Workspace and for group workspaces, rather than only on the classic
page. This is the read-only slice; management and approval follow in M3B and
M3C.

The endpoint reference is
[Public Document Read APIs](PUBLIC_DOCUMENT_READ_APIS.md).

## Purpose and boundaries

Before this, `/public` in the V2 interface was a placeholder that linked out to
the classic page. Selecting a public workspace now opens a real workspace page
on the shared shell, with the same document explorer, filtering, sorting,
pagination, and detail behavior that personal and group workspaces already use.

M3A covers browsing only: reading the document list, facets, tags, a single
document, and its version history. Upload, metadata editing, tags mutation,
downloads, extraction, reprocessing, deletion, sharing, and artifact approval
are not part of this slice, and the interface offers no affordance for them.

## Addressing a workspace

Routes are `/public`, `/public/:id`, `/public/:id/:section`, and
`/public/:id/:section/:resourceId`. The workspace is identified by the URL, and
every document request carries that identifier in its own path — never a query
parameter, and never the account's stored active workspace.

Returned documents are checked against the workspace that was asked for. The
list, detail, and version readers all assert that each payload carries the
requested `public_workspace_id`, and the version reader additionally checks the
top-level `document_id`. A response that does not identify the requested
workspace and document raises rather than rendering, so a late or misrouted
response cannot populate the wrong workspace.

## Active workspace selection

Selecting a workspace still records it as the user's active public workspace,
because that selection is read by other surfaces — chat document scoping and
the classic public workspace page both consult it.

That call is deliberately **fire-and-forget**. It never gates rendering,
navigation, or reads, and a refused or failed activation leaves the surface
fully functional. This is possible precisely because reads carry their target
in the path: nothing on this page depends on active state being correct.

The group workspace page has activate-and-reconcile machinery with an
unsaved-work guard. That exists because group operations were active-scoped, so
a stale activation could misdirect a write. No equivalent is needed here, and a
read-only surface has no unsaved work to protect.

## Capability handling

The workspace context advertises what the surface may show. It is an interface
hint, never an authorization grant, and every endpoint reauthorizes
independently.

The surface is gated on the context resolving successfully together with
`document_permissions.can_view`. There is no separate read-capability block to
look for. `document_management`, `document_collaboration`, and
`native_delegation` are absent in M3A rather than empty, and the client treats
absence as "not available" rather than "empty set".

A missing or unrecognized context leaves the public documents surface
unavailable rather than degraded. It never falls back to personal or group
behavior.

## What the explorer shows

Filtering by place, search, tags, and classification; sorting by the shared
sort fields with `_ts` descending as the default recency order; pagination;
facets; and the workspace's tag definitions with their colors.

There is no Shared place. Public workspaces have no cross-workspace share
relationship in this slice, and the facet validator omits `shared_with_me`
entirely so one cannot appear by accident.

## File structure

| File | Role |
|---|---|
| `application/v2_ui/src/lib/documentReadAdapter.ts` | `DocumentReadScope` public kind and the path-scoped reader family |
| `application/v2_ui/src/lib/publicWorkspaceNavigation.ts` | Public workspace routing |
| `application/v2_ui/src/stores/publicWorkspaceStore.ts` | Load, revalidate, clear |
| `application/v2_ui/src/pages/PublicWorkspacePage.tsx` | The workspace page |
| `application/v2_ui/src/components/workspace/PublicWorkspacePicker.tsx` | Workspace selection |
| `application/v2_ui/src/lib/workspaceContext.ts` | Shared context, already modelled the public kind |

## Testing and validation

At this milestone, `ui_tests/test_v2_public_documents.py` covered the surface
with 26 executable cases: reading, filtering, sorting, pagination, empty and error states, an
unknown workspace returning 404, an unauthorized workspace returning 403, the
feature being disabled, a non-blocking `setActive`, classic handoff, chat
ceiling, markup inertness, and responsive layout in light and dark at 1440x900
and 390x844.

Run the V2 browser suites together, with `PYTHONPATH` set:

```powershell
$env:PYTHONPATH = "$PWD;$PWD\ui_tests;$PWD\ui_tests\fixtures"
python -m pytest .\ui_tests\test_v2_public_documents.py `
  .\ui_tests\test_v2_personal_document_scope.py `
  .\ui_tests\test_v2_group_documents.py `
  .\ui_tests\test_v2_group_document_collaboration.py `
  .\ui_tests\test_v2_group_document_management.py `
  .\ui_tests\test_v2_group_workspace_shell.py -q --disable-warnings
```

**153 passed** at the closeout commit, alongside `npm run build` in
`application/v2_ui`, which runs `tsc -b` before the production bundle. Run
browser suites in a single process; two concurrent runs race timing-sensitive
visibility assertions.

`ui_tests/test_v2_personal_document_scope.py` is the isolation baseline:
selecting a public workspace must never leak into personal reads.

## Related

- [Public Document Read APIs](PUBLIC_DOCUMENT_READ_APIS.md)
- [V2 Group Document Browsing](V2_GROUP_DOCUMENT_BROWSING.md) — the M2A equivalent
- [V2 My Workspace](V2_MY_WORKSPACE.md) — the personal surface both mirror
