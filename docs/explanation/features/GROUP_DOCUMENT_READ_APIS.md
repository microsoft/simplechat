# Group Document Read APIs (v0.261.129)

## Overview

Explicitly scoped group document reads let a client browse one selected group
without changing, or relying on, the user's saved active group. This is the
backend read-only slice of the V2 shared workspace rollout, not its management
or download milestone.

Implemented in version: **0.261.128**. Management capability and pending-artifact
projection updates were implemented in **0.261.129**, tracked in
`application/single_app/config.py`.

Dependencies are the existing group and group-document Cosmos containers,
current group membership, `enable_group_workspaces`, and the existing Content
Screening metadata projection. No new setting, container, or index is required.

## API contract

| Request | Response |
|---|---|
| `GET /api/group_documents?group_id=G` | `documents`, `page`, `page_size`, `total_count`, `file_downloads_enabled`, `file_download_enabled_group_ids`, `needs_legacy_update_check` |
| `GET /api/group_documents/facets?group_id=G` | `total`, `untagged`, `processing`, `errors`, `recent`, `shared_with_me`, `by_tag`, `by_classification` |
| `GET /api/group_documents/tags?group_id=G` | `tags` containing `{name, count, color}` |
| `GET /api/group_documents/D?group_id=G` | The document's metadata and processing progress |
| `GET /api/group_documents/D/versions?group_id=G` | `document_id`, `group_id`, `revision_family_id`, `versions` |

`group_id` selects exactly one group. Empty, malformed, duplicate, or mixed
`group_id`/`group_ids` parameters return HTTP 400; they never fall back to an
active group. A missing group returns 404 and denied membership or view status
returns 403. Facets and versions require `group_id`.

Without `group_id`, the pre-existing list and tag `group_ids` mode and active
group fallback remain available. The detail route also retains its active-group
fallback. Explicit parameters do not retarget any upload, edit, sharing,
approval, delete, reprocessing, or download route.

## Full-set queries

The list accepts `place=all|recent|shared|processing|errors|untagged`, `search`,
comma-separated `tags` with AND matching, `classification`, `page`, `page_size`,
`sort_by`, and `sort_order=asc|desc`. The existing `author`, `keywords`, and
`abstract` substring filters remain supported. Search matches filename or title;
`classification=none` matches missing, null, or empty classification metadata.

Supported sorts are `_ts`, `file_name`, `title`, `upload_date`, `file_size`,
`number_of_pages`, `version`, and `document_classification`. Numeric fields use
the shared numeric-safe sort; text fields are case-insensitive. Equal keys have
a stable group/document-ID tie order. Defaults remain page 1, page size 10, and
`_ts` descending.

Current revisions are selected before content filters, sorting, and pagination.
Revision families from different originating groups are not collapsed together.
Historical revisions cannot reappear merely because they match a filter that
their replacement does not.

Facets ignore list filters and pagination. Tags count the same visible current
set, including authorized incoming shares, and retain the selected group's tag
definitions and safe colors, including unused definitions with count zero.
Shared means another group's document legitimately shared into `G`, not another
user's upload. Recent uses the shared 30-day calculation: Cosmos `_ts`, falling
back to the upload date when that timestamp is unavailable.

## Authorization and screening

Every scoped read revalidates current Owner, Admin, DocumentManager, or User
membership and group view eligibility. Active, locked, and upload-disabled
groups are readable. Inactive or unrecognized statuses are denied; an active
group preference is not an authorization grant.

List, detail, and each visible revision derive relationship metadata from the
source record. `group_id` and `owner_group_id` identify the originating group.
Incoming shares carry `shared_group_active_id=G`, `owner_group_name`, and the
actual `shared_approval_status`: `approved` or `not_approved`. A legacy bare
recipient ID is approved. Owned documents report `owner`. One revision's share
does not authorize its siblings, and the requested document must itself be
authorized before a version family is queried.

Pending shares and held documents remain visible as identifying/progress
metadata, but do not expose extracted titles, abstracts, tags, classifications,
text, or blob references. Filters and facets use that safe projection rather
than leaking withheld metadata through matches or counts. Screening release
proof remains bound to the originating document, not the recipient's group.
Existing holds remain effective when the screening setting is disabled.
Unapproved shares use the stable status `Awaiting group share approval` rather
than exposing the source's free-text processing diagnostics.

Pending generated artifacts are also restricted when no screening marker is
present, including the initial `Pending approval` status before a promotion
marker exists. Their safe requester/status fields and promotion flag remain;
owned documents still report `shared_approval_status=owner`.

Version 0.261.129 adds fresh `document_actions` to outgoing records and an
optional `document_management` handshake to workspace context. These are
computed only at the final outgoing-record boundary; list query, facets and
tag calculations never probe every candidate's blob for operation eligibility.
Stored action fields are not trusted. See
[Group Document Management APIs](GROUP_DOCUMENT_MANAGEMENT_APIS.md) for policy,
immutable operation URLs and result contracts.

The final response guard batch-refreshes returned IDs in the selected group.
It never probes personal documents with matching IDs, borrows another group's
membership, or silently turns a revoked target into an empty successful page.
Responses are private and non-cacheable. Provider failures are logged using
`[DOCUMENTS]` and return a stable error without provider diagnostics.

## Read architecture and limitations

`functions_group_document_reads.py` implements the strict read boundary.
Explicit reads deliberately use the existing source-container ownership/share
query, regardless of access-index readiness. A complete-looking index can still
omit a newly shared document or its current revision, so hydrating index hits
cannot establish complete counts or facets. Legacy list and tag reads retain
their existing index/source switch.

The source query materializes the full scoped set before applying explorer
queries. Final revalidation uses one scoped ID-batch query per requested group,
not one source point read per result. Cleared screening records still require
their independent release-proof reads. This favors correct authorization and
complete results over access-index latency; no large-workspace performance
benchmark or live Azure deployment is claimed.

### Document identity invariant

The supported `group_documents` container is partitioned by `/id`, not by
`/group_id`. This is defined consistently in `application/single_app/config.py`,
`deployers/bicep/modules/cosmosDb.bicep`, and `deployers/terraform/main.tf`.
Cosmos requires an item's ID to be unique within its logical partition; equal
IDs here also have equal partition keys. Two originating groups therefore
cannot hold separate records with the same ID in this container. A document
shared into several groups remains one source record.

The final projection can consequently key group source records by ID while
separately revalidating the requested group relationship and rejecting changed
origin/version identity. Personal and group containers can have equal IDs,
which is why every strict read and final refresh chooses the group container.
The schema invariant has a regression test; manually provisioned containers
with a different partition path are not a supported alternative schema.

### Shared helpers

`functions_document_queries.py` contains the shared pure place/facet logic;
personal routes retain their user-relative semantics. Existing revision,
filter, sort, tag-color, membership, and screening helpers remain in use.
`functions_workspace_context.py` advertises the eight supported sorts and
facets/places. Read contracts remain unchanged by the additive M2B management
handshake and routes.

## Testing and validation

`functional_tests/test_group_document_read_apis.py` runs real helpers and a
Flask Blueprint with isolated, read-only source containers. It covers explicit
versus active selection, malformed parameters, roles and statuses, membership
and share revocation, colliding personal/group IDs, independent version
authorization, pending/held metadata, full-set filtering and paging, all sorts,
facets, tags, stale/missing index entries, both legacy data-source paths, safe
errors, and unchanged mutation targeting.

Related coverage is in `test_v2_group_workspace_context.py`,
`test_content_screening_access.py`, `test_v2_documents_explorer.py`, and the
three policy checks under `functional_tests/route_tests/`. All source storage,
screening proof storage, and index records in the behavioral tests are local
fakes; no live Azure data is written.
