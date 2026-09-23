# Public Document Management APIs (v0.261.133)

## Overview

The M3B backend adds immutable-target management operations for public
workspace documents. The workspace is part of every URL, so an older worker
cannot ignore a scope parameter and write into whatever workspace the account
currently has selected.

Implemented in version: **0.261.133**, tracked in
`application/single_app/config.py`.

Dependencies are the existing public workspace and public document Cosmos
containers, Search, source Blob Storage, the executor, and Content Screening.
No new setting, container, or cloud architecture is required. The M3A read APIs
remain available.

This slice does not implement sharing, generated-artifact approval, prompts, or
workspace administration.

## Why the target is in the path

M3A established the pattern for reads. It matters more here.

A read scoped by a query parameter that an older server ignores returns the
wrong data. A **write** scoped that way executes an upload, an edit, or a
deletion against the wrong workspace. A path the server does not implement
returns 404 instead, which is the failure mode worth having.

These routes never read `activePublicWorkspaceOid` and never call
`require_active_public_workspace`. Legacy `/api/public_documents...` and
`/api/public_workspace_documents...` mutation routes keep their existing
active-workspace contracts and are not aliases for these.

## Immutable API family

All paths begin `/api/public-workspaces/W/documents`. `W` is the sole target.
Body and query scope overrides, unknown request fields, and duplicate query
parameters are rejected.

| Method and suffix | Input |
|---|---|
| `POST /upload` | Multipart repeated `file` fields |
| `PATCH /D` | Changed metadata fields only |
| `DELETE /D` | Required `delete_mode`, optional confirmation parameters in query |
| `POST /bulk-delete` | `document_ids`, required `delete_mode`, optional confirmation fields |
| `GET /D/download` | No body |
| `POST /download` | `document_ids` |
| `POST /extract_metadata` | `document_ids` |
| `POST /reprocess_extraction` | `document_ids`, `extraction_mode=read\|layout` |
| `POST /tags` | `tag_name`, optional `color` |
| `PATCH /tags/T` | `new_name` and/or `color` |
| `DELETE /tags/T` | No body |
| `POST /bulk-tag` | `document_ids`, `action=add_tags\|remove_tags\|set_tags`, `tags` |

Document batches accept 1–1000 identifiers and deduplicate them in request
order. Uploads enforce the configured per-file size limit before creating a
source record. Empty files, directory-containing filenames, and unsupported
extensions are rejected per file while other valid files still queue.

Edit, tag, extract, and reprocess apply to the current revision only.

## Receipts and errors

Metadata receipt:

```json
{
  "message": "...",
  "document_id": "D",
  "public_workspace_id": "W",
  "updated_fields": ["..."],
  "status": "updated"
}
```

`status` is `updated` (200) or `queued` (202). The scope field is
`public_workspace_id` where the group equivalent carries `group_id`.

Incomplete propagation surfaces as a `document_propagation_incomplete` repair
error rather than a silent partial success. Tag vocabulary responses carry
`vocabulary_retained`, and tag-only failures use the
`{stage: 'vocabulary', public_workspace_id, ...}` error union. Delete receipts
identify the requested IDs.

Validation failures are raised before any effect, so a rejected request leaves
no partial work behind.

### Batch outcomes and HTTP status

Operations that act on several documents or files report each item's result in
arrays — `success`, `queued`, `deleted`, `document_ids`, and `errors` — and use
the HTTP status to summarize. Two rules apply, and they differ in what happens
when nothing succeeds:

| Operation | All succeed | Some succeed | None succeed |
|---|---|---|---|
| `POST /upload` | 200 | 207 | 400 |
| `POST /extract_metadata`, `POST /reprocess_extraction` | 202 | 207 | 400 |
| `POST /bulk-tag`, `PATCH /tags/T`, `DELETE /tags/T` | 200 | 207 | **207** |
| `POST /bulk-delete` | 200 | 207 | **207** |
| `POST /tags` (create) | 201 | — | — |

Upload and the extraction jobs return 400 when no item was accepted. Tagging,
tag changes, and bulk deletion return 207 whenever **any** item failed, including
when every item failed.

So a 207 alone does not tell a client whether anything changed. **Inspect the
arrays rather than relying on the HTTP status.** In particular, do not treat a
207 from bulk deletion as proof that some documents were deleted.

For tag rename and delete, the order of operations determines what a 207 means.
The new definition is written first, documents are updated one at a time, and
the old definition is removed **only if every document succeeded**.

- If any document failed, the old definition is deliberately kept so that
  documents still carrying the old tag are not left without a definition. After
  a partial rename, both the old and the new name exist. Per-document errors
  carry a `document_id`.
- If every document succeeded but removing the old definition failed, the
  response carries an error with `stage: "vocabulary"` and `error` of
  `vocabulary_conflict` (a concurrent change) or `vocabulary_update_failed`, and
  no `document_id`.

`vocabulary_retained` is `true` in **both** cases — it reports that the old
vocabulary is still present, whatever the cause. The successful document updates
stand either way. Refresh the vocabulary rather than replaying the writes that
already succeeded.

## Authorization

Manager roles are `Owner`, `Admin`, and `DocumentManager`. Ordinary `User`
membership grants reads only and acquires no mutation or download.

Workspace status is enforced identically to groups:

| Status | Upload | Delete | Chat | View |
|---|---|---|---|---|
| `active` | yes | yes | yes | yes |
| `locked` | no | no | yes | yes |
| `upload_disabled` | no | yes | yes | yes |
| `inactive` | no | no | no | no |

Downloads are independently gated by
`is_public_workspace_file_download_enabled`.

Every request revalidates role, workspace status, revision, screening state,
and feature policy. Queued jobs revalidate when they run. A stored active
workspace preference is never an authorization grant.

## Serialization

Unchanged from M3A. Responses keep document lists under `documents` and single
documents at the top level, and the blueprint registers the document API guards,
so `enforce_document_response` re-reads each record fresh and authorized and
serializes it through the redaction boundary.

Nothing is hand-redacted in a handler and no second private-field list exists.
`document_actions` is computed fresh per document per request from current
authorization; it is in `PRIVATE_DOCUMENT_FIELDS` precisely so a stored copy
cannot be served in its place.

## Context changes

`build_public_workspace_context` now emits a `document_management` block,
`{schema_version: 1, operations: [...]}`, computed from role, status, and the
download setting, mirroring the group block. `document_permissions` stops being
uniformly false: `can_upload`, `can_edit`, `can_delete`, and `can_download`
reflect real policy.

`document_collaboration` and `native_delegation` remain **absent** rather than
empty; they arrive with M3C. The context is an interface hint, never an
authorization grant.

## Invariants carried forward

`facets.shared_with_me` stays structurally 0. Public workspaces have no
cross-workspace share relationship until M3C, and the client offers a Shared
place on any value above 0. The frontend encodes the same rule independently by
hardcoding its incoming-share branch to `false` for public scope.

Active workspace state stays non-load-bearing. It was free in the read-only
slice because nothing could depend on it; it survives now only because every
operation names its workspace in its own path.

## Testing and validation

| Suite | Coverage |
|---|---|
| `functional_tests/test_public_document_management.py` | Per-role and per-status authorization for every operation, receipts, batch dedupe and limits, per-file upload rejection, current-revision-only, 400-before-effects, propagation-incomplete, download binding, queued-job revalidation |
| `functional_tests/test_public_document_read_transport.py` | All twelve new URL/method pairs proven unmatchable against legacy public routes |
| `functional_tests/test_public_document_call_boundary.py` | Every keyword the public wrappers pass to a shared write primitive is one the real function accepts |
| `functional_tests/test_public_document_payload_redaction.py` | Guard registration for the management blueprint |

### A note on the test strategy

The management suite stubs the shared write primitives in `functions_documents`
with behavior-simulating fakes and keeps the real public access, policy, and
management authorization logic under test. The reasoning is that this slice is
public wrappers plus authorization, and the storage internals are already
exercised by the group suite.

That trade has one blind spot: a stub accepts any signature, so a later change
to a shared primitive could break the public wrappers while the stubbed suite
stayed green. `test_public_document_call_boundary.py` closes it by checking the
real signatures in `functions_documents` against every call the public module
makes, and by pinning that `update_document` — which takes `**kwargs` and so
cannot be signature-checked — still reads and branches on `public_workspace_id`
explicitly.

At the closeout commit the public suites pass **370 cases**, the group and
cross-scope regression passes **489 cases with 34 subtests**, the V2 browser
suites pass **168**, route policy passes **8/8, 4/4, 2/2**, and the
broken-access-control scanner passes on all six changed backend modules.

## Related

- [V2 Public Document Management](V2_PUBLIC_DOCUMENT_MANAGEMENT.md) — the browser surface
- [Public Document Read APIs](PUBLIC_DOCUMENT_READ_APIS.md) — M3A
- [Group Document Management APIs](GROUP_DOCUMENT_MANAGEMENT_APIS.md) — the M2B equivalent
