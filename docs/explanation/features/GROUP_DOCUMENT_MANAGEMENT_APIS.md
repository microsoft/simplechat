# Group Document Management APIs (v0.261.129)

## Overview

The M2B backend adds immutable-target group document operations. A selected
group is part of each URL, so an older worker cannot ignore a new scope query
parameter and write into a different active group.

Implemented in version: **0.261.129**, tracked in
`application/single_app/config.py`.

Dependencies are the existing authenticated group-document Blueprint, group
and document containers, Search, source Blob Storage, executor, and Content
Screening services. There is no new setting, container, or cloud architecture.
The M2A read APIs remain available.

This slice does not implement sharing/unsharing, recipient removal, artifact
or share approval decisions, public workspaces, or group saved views.

## Immutable API family

All paths below start with `/api/groups/G/documents`. `G` is the sole target.
Body/query scope overrides, unknown request fields, and duplicate query
parameters are rejected. No operation reads or changes `activeGroupOid`.

| Method and suffix | Input |
|---|---|
| `POST /upload` | Multipart repeated `file` fields |
| `PATCH /D` | Changed metadata fields only |
| `DELETE /D` | Required `delete_mode` and optional confirmation parameters in query |
| `POST /bulk-delete` | `document_ids`, required `delete_mode`, optional confirmation fields |
| `GET /D/download` | No body |
| `POST /download` | `document_ids` |
| `POST /extract_metadata` | `document_ids` |
| `POST /reprocess_extraction` | `document_ids`, `extraction_mode=read|layout` |
| `POST /tags` | `tag_name`, optional `color` |
| `PATCH /tags/T` | `new_name` and/or `color` |
| `DELETE /tags/T` | No body |
| `POST /bulk-tag` | `document_ids`, `action=add_tags|remove_tags|set_tags`, `tags` |

Document batches accept 1-1000 identifiers and deduplicate them in request
order. Uploads enforce the configured per-file size limit before creating a
source record. Empty files, directory-containing filenames, and unsupported
extensions are rejected per file, while other valid files can still be queued.

Legacy `/api/group_documents/...` mutation routes retain their active-group
contracts. They are not aliases for the new routes.

## Policy and capability handshake

Selected-group context adds:

```json
{"document_management":{"schema_version":1,"operations":["upload","edit_metadata","tag_documents","manage_tags","delete","download","extract_metadata","reprocess"]}}
```

The example is the complete vocabulary, not an unconditional grant. The
operation list depends on current role, status, download policy and extraction
settings. Existing `document_queries` and `document_permissions` remain.

Strict outgoing list/detail/version records add a freshly computed
`document_actions` array. Stored arrays are discarded. Clients must intersect
workspace support with current record actions and treat missing support as
read-only. Routes independently reauthorize; a capability is not a token.

| Group status | Manager operations |
|---|---|
| Active | Applicable operations, subject to feature/resource guards |
| Locked | Policy-authorized downloads only |
| Upload-disabled | Permitted delete, reprocess and download |
| Inactive or unknown | No content operations |

Content managers are Owner, Admin and DocumentManager. User does not gain
mutation or download rights. Current membership and exact document relationship
are checked at operation boundaries, not inferred from the uploader or active
preferences.

Editing metadata/tags, extracting metadata, and reprocessing require the
selected group's actual current revision. Historical records can retain
independently permitted download and explicit revision-aware delete. Canonical
family lookup resolves legacy records without a current flag. A revision that
becomes historical is rejected, never replaced with a newer target.

An incoming share is not ownership: even an approved readable share cannot be
edited, tagged, deleted, extracted or reprocessed through the recipient group.
Approved incoming downloads require both recipient and actual source group
view/download policies. The approved share authorizes the relationship; unrelated
membership in the source group is not required.

Pending/held content is not ordinary editable or downloadable content. Owned
restricted deletion follows the explicit review cleanup states:
`pending_review`, `scan_error`, `incomplete`, `rejected`, and `deleting`, with
matching current scan/subject identity. In-flight scanning, extraction,
remediation and publication states are denied. A held historical promotion
does not copy its private original into a current alias or reactivate its chunks.
Strict promotion conditionally claims the source before changing visibility and
keeps the exact archived blob reference instead of overwriting a mutable filename
alias. Source deletion uses conditional Blob ETags and surfaces cleanup failures
before removing source metadata.

Pending generated artifacts stay restricted without a screening marker, including
the creation gap with `status=Pending approval` and no promotion flag. Safe
request/status metadata is retained; summaries, tags and blob references are not.
Owned artifacts remain `shared_approval_status=owner`. Explicit promotion states
such as `approved` and `approval_failed` are not rewritten as pending approval.

## Metadata acknowledgements and conditional writes

Allowed metadata is `title`, `abstract`, `keywords`, `publication_date`,
`document_classification`, `authors`, and `tags`. The entire payload is validated
before any update. Omitted fields and source identity are preserved. Text nulls
clear to empty strings; null authors/keywords clear to empty arrays. Tags use the
existing validator. Authors and keywords retain compatible text/list inputs.

Successful PATCH returns only a scope-bound receipt:

```json
{"message":"Group document metadata updated.","document_id":"D","group_id":"G","updated_fields":["title"],"status":"updated"}
```

Immediate saves return HTTP 200 and `updated`. Accepted enrolled metadata rescans
return HTTP 202 and `queued`; saved metadata remains unavailable until screening
completes. Clients must validate the receipt instead of accepting arbitrary
successful HTML, objects, or message-only responses.

Strict writes conditionally persist the source before changing downstream
projections. An ETag conflict or disappeared expected-ETag source cannot mutate
Search/Blob/index state or recreate a deleted record. Required projection failure
returns an explicit error, not an updated receipt:

```json
{"error":"document_propagation_incomplete","message":"The operation changed stored data, but required cleanup or propagation is incomplete. Refresh before retrying.","document_id":"D","group_id":"G","repair_required":true}
```

Already-saved requested fields are reprojected on a deliberate retry. Blob tag
metadata also uses conditional ETag persistence. Legacy callers retain the
existing default behavior of shared helpers.

## Batch outcomes and deletion

Upload returns `document_ids`, `processed_filenames`, `errors`, and a safe queue
message. Accepted work is not completed extraction.

Tagging returns `success:[{document_id,tags}]` and `errors`. Extraction and
reprocessing return `queued:[{document_id,...}]` and `errors`; full acceptance is
202, mixed outcomes are 207, and no accepted work is 400. Clients inspect arrays,
not only HTTP success.

Deletion requires `delete_mode=current_only|all_versions`. Both single and batch
success identify requested IDs in `deleted:[{document_id}]`, with `errors`,
`deleted_count`, and `error_count`. Single success also includes
`deleted_mode`, actual `deleted_document_ids`, and `promoted_document_id`.
Overlapping same-family all-versions targets are not executed twice or falsely
reported missing after deletion by the same batch.

Conversation-linked confirmation uses the explicit
`conversation_linked_delete_confirmed` boolean. File Sync choices are exactly
`delete_only` and `ignore_remote`. Guard failures preserve
`needs_confirmation`, the established error/message, conversation/document or
file-sync details, and advertised options. There is no `force` bypass.

All selected family members are checked before revision deletion begins.
Partial cleanup failures remain explicit; multi-resource deletion is not a
distributed transaction.

## Tag vocabulary concurrency and partial results

Create returns 201 with `{message,tag:{name,color}}`. PATCH/DELETE return
`message`, `documents_updated`, `success`, `errors`, and `vocabulary_retained`;
PATCH also returns `tag:{name,color}`. Recolour changes no documents.

Tag definitions are conditional per-key patches, not stale whole-group upserts.
Other membership, settings and tag changes are preserved. Newly created/renamed
names use the existing normalized 50-character slug policy; existing broader
targets, including slashes, remain addressable through the path converter.

Renames/deletes affect only current owned revisions. Historical and incoming
shared records are not rewritten. The old vocabulary is retained when targeted
propagation fails; a rename may retain both old and new vocabulary for already
updated documents.

A final vocabulary CAS conflict can follow successful document updates. It
returns 207, retains those document successes, sets `vocabulary_retained=true`,
and reports `{stage:"vocabulary",group_id:G,error,message}` without inventing a
failed document ID. Per-document errors retain `document_id`. Clients refresh
authoritative vocabulary and do not automatically replay successful writes.

From version **0.261.167**, a vocabulary write that finds the group changed
answers the same way wherever it's caught: at its etag check, or when Cosmos
refuses its conditional patch (412). Create, recolour and rename answer 409
"The group's tags or permissions changed. Refresh and retry." with
`error_code: "vocabulary_conflict"`. The 207 vocabulary stage reports
`error: "vocabulary_conflict"` with that sentence, and bulk tagging reports it
per document. Before, a lost patch answered the generic "The resource changed.
Refresh and retry the operation." with no code.

## Worker and download boundaries

Jobs capture group, actor, document and revision; workers revalidate those
bindings rather than active preferences. Scoped progress writes use guarded,
conditional updates and safe failure text. Explicit metadata extraction does
not rediscover a personal document with the same ID.

Downloads use the existing canonical source helpers with an authorized reader
bound to the selected recipient. Pre-read, provenance-refresh and final-response
checks retain that binding. An owner/recipient same-name collision cannot select
the recipient's bytes, and missing source bytes never trigger another-scope
fallback. Every batch member is authorized before any archive is returned.
Attachments retain private/no-store, disposition and nosniff protections.

## Files, verification and limitations

The operation layer is `functions_group_document_management.py`; shared access
and policy are in `functions_group_document_access.py` and
`functions_group_document_policy.py`. Routes remain on the existing group
Blueprint. `functions_documents.py` adds opt-in strict/helper bindings while
preserving defaults. Context and final read projection expose capabilities.

`functional_tests/test_group_document_management.py` covers role/status matrices,
scope/worker binding, malformed inputs, current/history constraints, independent
screening cleanup, precise source downloads, conditional-write races, tag
concurrency and partial results. Read/context, screening, extraction, revision,
and route-policy suites provide related compatibility checks.

Full-set read filtering remains source-authoritative. Management action/source
probes occur only for outgoing page/detail/version records, not the full query
or facet/tag set. Settings and group context are reused within one response;
operations still check live authority. No live Azure writes, model calls,
deployment or large-workspace performance benchmark is claimed.
