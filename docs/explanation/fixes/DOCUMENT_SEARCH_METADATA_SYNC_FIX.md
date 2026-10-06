# Document Search Metadata Sync Fix (React V2)

Fixed in version: **0.261.268**

Related issue: [#1657](https://github.com/microsoft/simplechat/issues/1657). This is the React V2 port of [#1658](https://github.com/microsoft/simplechat/pull/1658), merged into `Development` as `900a3e431`, including its hardening commit `9c156a429` and the search cache refresh from [#1673](https://github.com/microsoft/simplechat/pull/1673) (`df3879c07`). V2 never received the `0.261.051` browser-driven continuation protocol (#1645), so nothing here removes it.

## Issue

Saving tags or other metadata on a large document (large XML exports, long PDFs) ran until the front-end request timed out. The browser then received an HTML error page and reported "invalid JSON". Bulk tagging, tag rename, and tag delete timed out the same way in large workspaces.

In V2 the native group and public document APIs had a second failure: a metadata edit on any group document with more than one search chunk returned `document_propagation_incomplete`, even when Search was healthy.

## Root Cause

Every search chunk mirrors the document's title, authors, file name, classification, and tags. `document_tags` drives chat tag filters; title, author, and classification appear in citations. Updating them did per-chunk work inside the request:

- `update_document()` listed every chunk, then called `update_chunk_metadata()` once per chunk. That call read the whole chunk from AI Search, embedding included, and sent a one-document merge through the Data Management write slot. For group documents the merge also passed through the group projection fence, which claims and releases a marker on the Cosmos document. A 10,000-chunk document needed about 20,000 Search calls and about 40,000 Cosmos operations.
- In strict mode, which the native group and public APIs use, the loop re-read the Cosmos document before every chunk and required its etag to match the saved document. The projection fence's claim changes that etag, so on a group document the check failed at the second chunk and the API answered `document_propagation_incomplete`.
- Bulk tag, tag rename, and tag delete synced every chunk twice (`update_document()` plus `propagate_tags_to_chunks()`). The legacy group and public metadata PATCH routes called `update_document()` once per field, so a multi-field save made several full passes.
- Non-strict `update_document()` swallowed chunk sync errors and reported success, so a partially synced document was never retried.

Group sharing had a related gap. The chunk loop wrote nothing when only `shared_group_ids` changed, so share, approve, unshare, and remove-self never reached the chunks through the legacy routes. Search filters on `shared_group_ids/any(... 'group,approved')`, so approvals might never become searchable, and an unshare could leave a revoked group with search access to chunks that an earlier rebuild had copied the list into.

## Technical Details

### Files modified

- `application/single_app/functions_documents.py`
- `application/single_app/background_tasks.py`
- `application/single_app/functions_group_document_management.py`
- `application/single_app/functions_public_document_management.py`
- `application/single_app/functions_group_document_collaboration.py`
- `application/single_app/route_backend_documents.py`
- `application/single_app/route_backend_group_documents.py`
- `application/single_app/route_backend_public_documents.py`
- `application/single_app/route_external_public_documents.py`
- `application/single_app/static/js/workspace/workspace-documents.js`
- `application/single_app/static/js/public/public_workspace.js`
- `application/single_app/templates/group_workspaces.html`
- `application/v2_ui/src/lib/documentOperations.ts`, `application/v2_ui/src/lib/endpoints.ts`
- `application/v2_ui/src/components/documents/DocumentExplorer.tsx`, `application/v2_ui/src/pages/workspace/TagsSection.tsx`
- `application/single_app/config.py`

### Merge-based projection engine

- `iter_document_chunk_key_pages()` lists a document's active chunk keys with `select=id`, ordered by `id`, and pages by key (`id gt '<last>'`). The filter is the document id plus its exact workspace scope, so archived revision chunks, which carry an archived scope value, are excluded. Key paging has no `$skip` ceiling.
- `project_fields_to_document_chunks()` sends `merge_documents` batches (default 500, maximum 1000, capped at 8 MB) through `_execute_document_search_write()`. Each action carries only the chunk key and the projected fields, so embeddings never round-trip. Any unacknowledged batch raises. An optional `before_batch` hook lets the worker confirm it still holds its lease.
- A projection carries either mirrored metadata or the workspace's access list, never both. Metadata merges carry no access or scope field, so they skip the group projection fence and never write to the document. Every merge still holds the Data Management write slot. Only `shared_group_ids` payloads go through the fence.

### Durable background sync for metadata

- When `update_document()` saves a change to the title, authors, file name, classification, or tags, it first calls `request_document_search_metadata_sync()`. That creates or conditionally updates a record in the settings container:
  - id `document_search_metadata_sync:{personal|group|public}:{document_id}`, type `document_search_metadata_sync`;
  - a revision counter, a unique token for the latest request, and the union of pending fields;
  - status, lease, and backoff state, with fixed-width UTC timestamps.
- The document is then saved with the same token in `search_metadata_sync_token`. Strict and non-strict saves both carry it, so V2's strict etag checks and operation guards are unchanged. A strict caller re-requests every mirrored field it sends, so a retry after a failure always projects again.
- `schedule_document_search_metadata_sync()` queues the sync on a dedicated two-thread pool and deduplicates queued documents in-process. The save does no per-chunk work.
- `run_document_search_metadata_sync()` takes a per-document lease and projects the latest saved value of every pending field, so a retry also heals partially synced chunks. How each pass ends:
  - **A newer edit arrived:** the same worker continues with it.
  - **The document doesn't carry the latest token yet:** the pass is deferred and re-checked. After 10 minutes the request is treated as abandoned and completes.
  - **Success:** the record is deleted with an etag-conditioned delete.
  - **Failure:** the record is kept with a backoff of 1, 5, 15, and 60 minutes, then every 6 hours, and `[DOCUMENT_SEARCH_SYNC]` is logged. While a Data Management migration has frozen Search writes, the record retries every 5 minutes instead of climbing the backoff.
- The worker never writes to the document. Document lists sort by `_ts`, and V2 strict saves compare etags, so a worker write would reorder lists and break concurrent saves.
- A held screened document has no released chunks, and publication rebuilds them from the document. `update_document()` reports `not_required` for it, and the worker treats it as having nothing to sync.
- After a pass that changed chunks, the worker clears cached search results for the document's workspace and for every user or group with an approved share, matching `Development` [#1673](https://github.com/microsoft/simplechat/pull/1673). Routes already clear the cache when a change is saved, but a search that ran while the sync was merging could otherwise keep serving the old values for the search cache lifetime (5 minutes by default).
- `run_document_search_metadata_sync_loop()` in `background_tasks.py` runs every 60 seconds under the distributed lock `document_search_metadata_sync_scan`. It finishes requests that failed, never started because the process restarted, or lost their lease.

### Blob tag metadata

V2 propagated tags to the source blob's metadata inside strict saves, after the document had saved. That refresh now runs in the sync worker for every workspace:

- It is best effort and never fails the pass. Nothing in V2 reads blob `document_tags`, so failing the edit would only tell the user to retry a change that had already been saved.
- It is conditioned on the blob ETag it just read, so it never overwrites the metadata of a concurrent blob replacement.
- It still never touches a screened document's blob. The release pins that blob by ETag and content hash, and a metadata write would make the released file unreadable.

### Access-control projections stay synchronous and fail closed

`update_document()` projects real access-list changes itself: `shared_group_ids` for groups and `shared_user_ids` for personal documents. A missing list and an empty list count as the same, so the legacy document upgrade never depends on Search.

V2's group projection fence admits only access entries the Cosmos document already records, so a group change is split:

- A revocation is projected first, as the new list without anything it adds, and fails closed.
  - The fence's claim changes the document's etag. `update_document()` re-reads the document and compares everything except Cosmos system properties and the fence's claim field.
  - If nothing else changed, the save proceeds with the new etag. Otherwise another writer won: Search is projected back to the list Cosmos now records, and the update is refused with a conflict (409).
- New grants are projected after the save, once the fence admits them.
  - If a grant does not reach Search, the call raises `DocumentMutationPropagationError`. The native APIs report that as `document_propagation_incomplete`; the legacy routes answer 503 with `Retry-After` while Search writes are frozen, or 500 otherwise.
  - Entries that grant nothing, such as pending shares, are projected best effort. Grants skip held documents.
- Personal lists have no fence. The new list is projected before the save for released documents; for a held document, only revocations are.

Errors and the sharing routes:

- `project_document_acl_to_chunks()` maps a frozen write fence to `DocumentSearchAclProjectionDeferredError` (503 with `Retry-After`) and any other failure to `DocumentSearchAclProjectionError` (500). Both carry fixed, safe messages, and `describe_document_search_acl_error()` turns them into route responses.
- Personal unshare and share approval also project before saving. A pending personal share grants nothing, so it saves first and projects best effort.
- Approving a share that is already approved now repairs its search access, so a saved grant whose projection failed can be completed by approving again:
  - the legacy group route and the personal route re-project the recorded list;
  - the native group API checks the chunks first and re-runs its own search effect only when they differ, so a repeat has no effects.

### Routes, receipts, and clients

- The personal, legacy group, legacy public, and external public metadata PATCH routes save every field in one `update_document()` call and return `search_sync`. Error responses carry fixed messages, never exception text.
- Bulk tag, tag rename, and tag delete in all three workspaces no longer call `propagate_tags_to_chunks()`, which was removed. Their receipts summarize the sync as `search_sync: {status, document_count}`.
- The native group and public metadata receipts keep `status: 'updated'`, `updated_fields`, `document_id`, and the scope id, and add `search_sync: {status, revision, fields}`. Their tag receipts keep `success`, `errors`, `documents_updated`, and `vocabulary_retained`, and add the summary. A metadata projection failure no longer produces `document_propagation_incomplete`, because the background sync retries it; an access index failure still does.
- The React V2 explorer and tag manager show an info toast when a receipt reports a pending sync. Only an `updated` 200 confirms a metadata edit, and an unrecognized `search_sync` value never fails an otherwise confirmed change. The classic personal, group, and public workspace dialogs show the same notice.

### Impact

| Area | Before | After |
|---|---|---|
| Azure load | A full chunk read, embedding included, plus a fenced merge for every chunk: about 20,000 Search calls and 40,000 Cosmos operations for a 10,000-chunk document, doubled for bulk tag operations. | About 40 Search calls for a 10,000-chunk document (20 key pages and 20 merges of a few hundred bytes per chunk), roughly 500 times fewer. |
| Metadata or tag save on a large document | Timed out with "invalid JSON". | Returns immediately; the search index updates in the background. |
| Native group metadata edits | Failed with `document_propagation_incomplete` on any document with more than one chunk. | Succeed; the receipt reports the pending sync. |
| Bulk tag, tag rename, tag delete | Synced every chunk twice inside one request. | Only Cosmos writes happen in the request. |
| Chat tag filters and citations | A partially synced document stayed partly stale, with no retry. | Every chunk converges, with automatic retries. |
| Group sharing through the legacy routes | Approvals and revocations never reached the chunks. | Revocations are enforced before they are saved; approvals become searchable. |

Trade-offs:

- Chat tag filters can lag for a few seconds after a save, and up to a minute or two on very large documents.
- Sharing changes can return an error instead of a silent success when Search writes fail or are frozen during a Data Management migration.
- Access-control projections remain synchronous by design. They are about 500 times cheaper, but sharing changes on documents with tens of thousands of chunks still take a while.

Not changed: search ranking and relevance, embeddings, upload-time chunking, and the UI layout.

### Known limitations and follow-ups

- The native collaboration and publication paths (`_search_acl` in `functions_group_document_collaboration.py` and `set_document_chunk_visibility()`) still write a document's chunks as one batch, which Azure AI Search caps at 1,000 documents. Moving them onto `project_fields_to_document_chunks()` would remove that limit.
- Chunk access lists are not backfilled. Group shares approved through the classic workspace before this fix become searchable when that document's sharing changes again, or when the share is approved again.
- The projection fence can mark a claim uncertain after an ambiguous Search error, and nothing reconciles uncertain claims yet. This predates the port.
- Chunks saved by an upload that is still processing carry the metadata the processor read when it saved them. This predates the port.

## Validation

### Tests

- `functional_tests/test_document_search_metadata_sync.py` (34 tests) loads the real definitions with in-memory Cosmos and Search fakes and the real projection fence. It covers:
  - key-paged, scoped, id-only listing; field-only merges in byte-capped batches; and fail-loud merges that still hold the write slot;
  - `update_document()` queuing without chunk work, strict saves carrying the token in the same save, and strict group edits no longer racing the fence;
  - the worker: latest values, an edit arriving mid-sync, failure backoff healed by the reconciler, lease contention and loss, uncommitted saves, stale tokens, a record removed mid-write, frozen Search writes, missing or moved documents, and held screened documents;
  - clearing cached search results for the workspace and approved share recipients after a sync, and scheduler de-duplication;
  - group revocations projected before the save, refused when Search cannot enforce them, and restored after a concurrent change; group grants once Cosmos records them, and re-approval repair;
  - personal access lists, equivalent lists, pending shares, unshare failures, and the safe error mapping;
  - route, client, and native receipt wiring.
- `functional_tests/test_group_document_management.py` runs the real routes and `update_document()`. It covers receipts with `search_sync`, a Search failure retried durably, the access index failure, the conditional best-effort blob refresh, the screened tag edit that never rewrites the pinned blob, and storage CAS races whose rejected values never reach Search.
- `functional_tests/test_public_document_management.py`, `test_group_document_fixture_parity.py`, and `test_public_document_fixture_parity.py` hold the UI fixture receipt builders to the real receipts, including `search_sync`.
- `functional_tests/test_v2_group_document_operations.mjs` covers the React receipt validation and the pending-sync flag.
- `functional_tests/test_data_management_search_write_fence_authorization.py`, `test_document_auto_metadata_extraction_consistency.py`, `test_group_tag_definition_writers.py`, and `test_public_workspace_tag_writer_safety.py` were updated for the removed per-chunk helpers.
- `ui_tests/test_workspace_metadata_search_sync_toast.py` checks that the classic workspace dialog sends one PATCH and shows the notice only when a sync is pending.

### Before and after

- **Before:** a tag save on a 10,000-chunk document made about 20,000 Search calls and 40,000 Cosmos operations inside the request and timed out. A native group metadata edit failed on any multi-chunk document.
- **After:** the save records the sync request, saves the document with its token, and returns without Search work. The background sync makes about 40 Search calls and retries until every chunk matches the document.
