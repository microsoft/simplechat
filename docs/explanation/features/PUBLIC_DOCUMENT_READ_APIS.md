# Public Document Read APIs (v0.261.132)

## Overview

Explicitly scoped public workspace document reads let a client browse one
workspace without changing, or relying on, the user's saved active public
workspace. This is the backend read-only slice of M3, not its management or
approval milestone.

Implemented in version: **0.261.132**, tracked in
`application/single_app/config.py`.

Dependencies are the existing public workspace and public document Cosmos
containers, current workspace membership, `enable_public_workspaces`, and the
existing Content Screening metadata projection. No new setting, container, or
index is required.

## Immutable API family

The workspace is part of the path. It is never a query parameter, and these
routes never read `activePublicWorkspaceOid`.

| Method and path | Returns |
|---|---|
| `GET /api/public-workspaces/W/documents` | `documents`, `page`, `page_size`, `total_count`, `file_downloads_enabled`, `needs_legacy_update_check` |
| `GET /api/public-workspaces/W/documents/facets` | `total`, `untagged`, `processing`, `errors`, `recent`, `shared_with_me` (always `0`), `by_tag`, `by_classification` |
| `GET /api/public-workspaces/W/documents/tags` | `tags` of `{name, count, color}` |
| `GET /api/public-workspaces/W/documents/D` | document metadata and processing progress |
| `GET /api/public-workspaces/W/documents/D/versions` | `document_id`, `public_workspace_id`, `revision_family_id`, `versions` |

An older server that lacks these routes returns 404 rather than silently
serving whatever workspace the account currently has selected. That is the
point of putting the target in the path: a scope query parameter can be
ignored, a path cannot.

Legacy `/api/public_documents...` and `/api/public_workspace_documents...`
routes keep their existing active-workspace contracts. They are not aliases for
these routes, and this slice does not retarget any upload, edit, delete,
extraction, reprocessing, or download route.

### Why this differs from the group read slice

The M2A group read APIs scope with `?group_id=G` on existing routes. That
predates the immutable-target decision taken in M2B. Public reads are a fresh
surface, so they follow the current rule rather than the earlier precedent.

## Queries

The list accepts `place=all|recent|processing|errors|untagged`, `search`,
comma-separated `tags` with AND matching, `classification`, `page`, `page_size`,
`sort_by`, `sort_order=asc|desc`, and the existing `author`, `keywords`, and
`abstract` substring filters.

Supported sorts are `_ts`, `file_name`, `title`, `upload_date`, `file_size`,
`number_of_pages`, `version`, and `document_classification`. Numeric fields use
the shared numeric-safe sort; text fields are case-insensitive; equal keys have
a stable tie order. Defaults are page 1, page size 10, `_ts` descending.

`classification=none` matches missing, null, or empty classification. Recent
uses the shared 30-day calculation on `_ts`, falling back to the upload date.

Current revisions are selected **before** filters, sorting, and pagination, so a
historical revision cannot reappear because it matches a filter its replacement
does not.

Facets ignore list filters and pagination. Tags count the same visible current
set and retain the workspace's tag definitions and safe colors, including unused
definitions with count zero.

There is no `shared` place filter. Public workspaces have no cross-workspace
share relationship, so there is no Shared place.

Facets still include a `shared_with_me` count, because public and group
workspaces share one facet builder. For a public workspace it is always `0`:
every document returned already belongs to the workspace being read, so none is
counted as shared in from elsewhere. The client does not rely on the key — its
public facet validator omits it and its place logic offers a Shared place only
for a count above zero — so the Shared place stays hidden either way.

`file_downloads_enabled` in the list response reports whether this user may
download from this workspace. It is derived from the same policy that decides
whether the workspace context advertises `download`: a manager role, a
workspace status that permits downloads, and the workspace download setting.
Ordinary members always receive `false`.

## Authorization

Reader roles are `Owner`, `Admin`, `DocumentManager`, and `User`, matching
`PUBLIC_WORKSPACE_READER_ROLES`.

Every request revalidates current membership and workspace status. A stored
active-workspace preference is never an authorization grant.

- Unknown workspace → **404**
- Known workspace, no membership or ineligible role → **403**
- Empty, malformed, duplicated, or unknown query parameters → **400**, never a
  fallback

Statuses match the group model and are enforced the same way: `active`,
`locked`, and `upload_disabled` are readable; `inactive` is denied. `locked`
blocks upload and delete while permitting chat and view; `upload_disabled`
blocks upload only.

## Serialization

Responses place the document list under a `documents` key and single documents
at the top level. `route_backend_public_document_reads.py` calls
`register_document_api_guards(bp, document_projector=_project_public_document_read_response)`,
so the `enforce_document_response` after-request hook re-reads every record
fresh and authorized and serializes it through the redaction boundary before the
response leaves.

Nothing is hand-redacted in a handler, and no second private-field list exists.
Any field that must not reach an unauthorized reader belongs in
`PRIVATE_DOCUMENT_FIELDS` in `content_screening/access.py` and nowhere else.
`functional_tests/test_public_document_payload_redaction.py` pins the guard
registration for every document route file, including this one.

## Workspace context

`GET /api/v2/workspaces/public/<workspace_id>` mirrors the group context with
`scope: {kind: 'public', id: W}`, returning `schema_version`, `enabled`,
`viewer_id`, `scope`, `workspace` (name, description, owner, hero color, logo
URL), `role`, `status`, `can_manage_workspace`, `sections`,
`document_permissions`, and `document_queries`.

`document_management`, `document_collaboration`, and `native_delegation` were
absent in M3A rather than empty. `document_management` arrived with M3B and
`document_collaboration` with M3C; `native_delegation` remains absent. There is
no `document_read` capability block — read capability is expressed by the
context resolving plus `document_permissions.can_view`, exactly as for groups.

`document_actions` and `document_collaboration_actions` are carried per document
in the list and detail responses, computed fresh from the user's current
permissions on every request. The explorer only offers an action that appears
in these lists, so they are the per-document gate for every operation.

> In the read-only M3A release `document_actions` was a fixed empty list, which
> was correct while there was nothing to act on. It was not updated when M3B
> added operations, which left every public per-document action unavailable
> until it was fixed in M3C.

`logo_url` uses the pre-existing underscore route,
`/api/public_workspaces/<id>/logo?v=<version>`. New immutable routes are
hyphenated while existing routes keep their names, so within the public scope
the logo path is underscore and document paths are hyphen.

The context is an interface hint, never an authorization grant. Every endpoint
reauthorizes independently.

## Testing and validation

| Suite | Coverage |
|---|---|
| `functional_tests/test_public_document_read_apis.py` | Authorization per role, 404 vs 403, filters, sorts, pagination, facets, tags, versions, current-revision selection, 400 on malformed input |
| `functional_tests/test_public_document_read_transport.py` | Every new URL/method pair cannot match a legacy public route pattern |
| `functional_tests/test_public_document_payload_redaction.py` | Guard registration for the new blueprint |
| `ui_tests/test_v2_public_documents.py` | 26 browser cases over the native surface |

At the closeout commit the combined public read, transport, redaction, group
read, collaboration, screening bootstrap, screening access, multi-workspace
access, and public workspace visibility selection passes **819 cases with 34
subtests**. The V2 browser suites pass **153**, route policy passes **8/8, 4/4,
2/2**, and the broken-access-control scanner passes on all six changed backend
modules.

## Related

- [V2 Public Document Browsing](V2_PUBLIC_DOCUMENT_BROWSING.md) — the browser surface
- [Group Document Read APIs](GROUP_DOCUMENT_READ_APIS.md) — the M2A equivalent
- [V2 Shared Workspace Context](V2_SHARED_WORKSPACE_CONTEXT.md)
