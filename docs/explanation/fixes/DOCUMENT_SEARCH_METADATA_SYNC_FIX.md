# Document Search Metadata Sync Fix

Fixed/Implemented in version: **0.261.052**

Related issue: [#1657](https://github.com/microsoft/simplechat/issues/1657). Supersedes the request-batching approach in [Document Metadata Chunk Sync Batching Fix](DOCUMENT_METADATA_CHUNK_SYNC_BATCHING_FIX.md) (`0.261.051`, #1645).

## Issue Description

Saving tags or other metadata on a large document (large XML, long PDFs) ran until the front-end request timeout. The browser then received an HTML error page and reported an "invalid JSON" error. Bulk tagging, tag rename, and tag delete timed out the same way in large workspaces.

Version `0.261.051` kept the personal workspace dialog from timing out by splitting the same work across browser-driven continuation requests. The per-chunk cost, the group and public workspaces, bulk tag operations, and failure handling were unchanged.

## Root Cause Analysis

Every search chunk mirrors the document's title, authors, file name, classification, and tags (`document_tags` drives chat tag filters; title, author, and classification appear in citations). Updating them did O(chunks) work inside the request:

- `update_chunk_metadata()` read each chunk in full, including its embedding vector, then re-uploaded the whole chunk. Each chunk cost about 2 AI Search calls and 4 Cosmos write-fence operations, so a 10,000-chunk document needed about 20,000 Search calls and 40,000 Cosmos operations.
- Bulk tag, tag rename, and tag delete synced every chunk twice (`update_document()` plus `propagate_tags_to_chunks()`). The group and public metadata PATCH routes called `update_document()` once per field, so a multi-field save made several full passes.
- `update_document()` swallowed chunk sync errors and reported success. A partially synced document was never retried, and the `0.261.051` continuation state lived only in the browser.

Two access-control problems shared the same code path:

- Group sharing changes that only changed `shared_group_ids` (share, approve, unshare, remove-self) never reached the chunks, because the loop skipped the write when no non-ACL field changed. Search filters on `shared_group_ids/any(... 'group,approved')`, and rebuilt chunks copy the document's list. So approved shares might not be searchable, and an unshare could leave a revoked group with search access.
- A full-chunk re-upload could write back a stale `shared_user_ids` or `shared_group_ids` value if it raced a sharing change.

## Technical Details

### Files modified

- `application/single_app/functions_documents.py`
- `application/single_app/route_backend_documents.py`
- `application/single_app/route_backend_group_documents.py`
- `application/single_app/route_backend_public_documents.py`
- `application/single_app/background_tasks.py`
- `application/single_app/static/js/workspace/workspace-documents.js`
- `application/single_app/static/js/public/public_workspace.js`
- `application/single_app/templates/group_workspaces.html`
- `application/single_app/config.py`
- `docs/reference/logging-tags.md`, `docs/guides/use-tags-in-chat.md`

### Code changes summary

**Merge-based projection engine.**
- `iter_document_chunk_key_pages()` lists a document's active chunk keys (`select=id`, ordered by `id`, keyset paging with `id gt <last>`) inside the document's exact workspace scope. Paging by key has no `$skip` ceiling. Archived revision chunks are excluded on purpose.
- `project_fields_to_document_chunks()` sends `merge_documents` batches (default 500, API maximum 1000, byte-capped) through the existing fenced writer `_execute_document_search_write()`.
- Each merge carries only the chunk key and the changed fields, so embeddings never round-trip and concurrent projections of other fields cannot undo each other. Any unacknowledged batch raises.

**Durable background sync for metadata.**
- When `update_document()` changes the title, authors, file name, classification, or tags, it first records a sync request in the settings container with `request_document_search_metadata_sync()`. The record has type `document_search_metadata_sync`, a revision counter, the union of pending fields, and its status, lease, and backoff state.
- `update_document()` then saves the document with a matching `search_metadata_revision`, queues the sync, and returns `{'updated': ..., 'search_sync': {'status': 'pending', ...}}`. It does no per-chunk work.
- `run_document_search_metadata_sync()` runs on a small dedicated thread pool and takes a per-document lease on the record. Each pass projects the latest saved value of every pending field, so a retry also heals partially synced chunks.
- If an edit lands during a sync, the same worker projects it next. On success the record is deleted with an etag check. On failure the record keeps a retry time with backoff (1, 5, 15, and 60 minutes, then every 6 hours), the exception type is recorded, and `[DOCUMENT_SEARCH_SYNC]` is logged.
- The worker never writes sync state back onto the document. The document `_ts` (which drives list sorting and the access index) and its etag only change when users save.
- Tag changes also refresh blob metadata tags from the worker.
- `run_document_search_metadata_sync_loop()` in `background_tasks.py` runs every 60 seconds under a distributed lock. It picks up requests that failed, never started because the process restarted, or lost their lease.

**Access-control projections stay synchronous and fail closed.**
- `update_document()` projects `shared_group_ids` (group) and `shared_user_ids` (personal) changes to every chunk before saving the document, using `project_document_acl_to_chunks()`. This fixes ACL-only changes never reaching Search.
- A frozen Search write fence raises `DocumentSearchAclProjectionDeferredError` (HTTP 503 with `Retry-After`). Any other failure raises `DocumentSearchAclProjectionError` (HTTP 500 with a safe message). In both cases the access change is not saved.
- Personal unshare and share approval also project before saving. A pending personal share grants no access, so it still saves first and projects best effort.

**Routes and client.**
- The personal, group, and public metadata PATCH routes save every field in one `update_document()` call and return `search_sync`. Error responses no longer include raw exception text.
- Bulk tag, tag rename, and tag delete in all three workspaces dropped their duplicate `propagate_tags_to_chunks()` pass. That function was removed.
- The personal workspace dialog sends one PATCH again; the `0.261.051` `_metadata_chunk_sync` continuation protocol is removed.
- All three workspace dialogs show an info toast when the response reports a queued search update.

### Impact analysis

| Area | Before | After |
|---|---|---|
| Azure load | Every chunk's embedding was downloaded and re-uploaded to change a tag, at about 2 Search calls and 4 Cosmos fence operations per chunk (bulk tag operations doubled that). | A few hundred bytes per chunk merge. A 10,000-chunk document takes about 40 Search calls, roughly 500 times fewer. |
| Metadata or tag save on a large document | Personal: many sequential requests. Group and public: timeout with "invalid JSON". | Returns immediately; the search index updates in the background. |
| Bulk tag, tag rename, tag delete | Synced every chunk twice inside one request. | Only Cosmos writes happen in the request. |
| Chat tag filters and citations | A partially synced document was only partly findable, and stale titles or classifications could appear in citations, with no retry. | Every chunk converges, with automatic retries. |
| Group sharing in search | Approvals and revocations never reached the chunks. | Approvals become searchable; revocations are enforced before success is reported. |
| Personal share approval | A failed chunk update was swallowed, and a retry reported "Already approved". | Fails closed with a clear error, so a retry works. |
| Other users on the same server | A large tag save held the process-wide Search write lock for tens of thousands of writes. | A few dozen writes. |

Trade-offs:
- Chat tag filters can lag for a few seconds after a save, and up to a minute or two on very large documents.
- Sharing changes can now return an error instead of a silent success when Search writes fail or are frozen during a Data Management migration.
- Access-control changes remain synchronous by design. They are about 500 times cheaper, but share and unshare on documents with tens of thousands of chunks can still take a while.

Not changed: search ranking and relevance, embeddings, upload-time chunking, and the UI layout.

## Validation

### Tests

- `functional_tests/test_document_search_metadata_sync.py` (17 tests) covers:
  - Key-paged, scoped, id-only listing, and merges that carry only the changed fields.
  - The byte cap and fail-loud merges.
  - `update_document()` queuing without any chunk work.
  - The worker: latest values, an edit arriving mid-sync, failure backoff healed by the reconciler, lease contention and lease loss, uncommitted document writes, and missing documents.
  - Group ACL projection before commit, including the failed and frozen cases, and best-effort pending shares.
  - Scheduler de-duplication, plus route, client, and background wiring.
- `functional_tests/test_document_metadata_chunk_sync_batching.py` verifies that a 5,000-chunk tag save does no Search work in the request and syncs in 10 merge batches.
- `functional_tests/test_data_management_search_write_fence_authorization.py` keeps the fail-closed unshare guarantees and checks the share-approval and group-sharing error handling.
- `functional_tests/test_document_auto_metadata_extraction_consistency.py` checks that public workspace scope reaches the sync request, scheduling, and projection.
- `ui_tests/test_workspace_metadata_search_sync_toast.py` verifies the workspace dialog sends one PATCH and shows the toast only when a search update is queued.

### Before and after

- **Before:** a tag save on a 10,000-chunk document made about 20,000 Search calls and 40,000 Cosmos operations inside the request, and timed out.
- **After:** the save records the sync request, saves the document, and returns without any Search work. The background sync makes about 40 Search calls and retries on failure until every chunk matches the document.
