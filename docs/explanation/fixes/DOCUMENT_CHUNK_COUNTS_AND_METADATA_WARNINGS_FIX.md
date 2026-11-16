---
layout: page
title: "Document chunk counts and obsolete metadata warnings"
description: "Accurate indexed chunk bookkeeping and metadata-only retry status reconciliation."
version: "0.261.401"
---

## Issue and root causes

Fixed/Implemented in version: **0.261.400**.
Deletion-receipt follow-up implemented in version: **0.261.401**.
The application version is updated in `application/single_app/config.py`.

Most unscreened upload processors returned a local chunk total, but the shared
finalizer wrote it only to `number_of_pages`, leaving the initial `num_chunks=0`.
Those local totals were not authoritative: an empty chunk could be skipped, a
repeated key could overwrite an existing chunk, or a media writer could fail.
Audio/video source-file processing also left `num_file_chunks` at its initial zero.

Metadata-only retries correctly saved `metadata_extraction_status=succeeded`,
but did not retire the older `Processing complete (metadata extraction warning)`
message. Successful indexing and successful metadata analysis could therefore
appear contradictory even when the expected content was retrievable.

The access-index projection omitted chunk counters, and the final response guard
rehydrated raw source metadata. Repairing only the initial detail payload would
therefore be undone before the browser received it.

## Technical changes

`document_chunk_counts.py` enumerates distinct Search keys with filters for the
document ID, owning workspace and source version. Key paging has no document-size
cap and downloads neither chunk text nor embeddings. It does not use approximate
Search totals, page counts, embedding tokens, or attempted-write counts.

The shared Search writer records acknowledged chunk uploads in a job-local
context. Upload and extraction-reprocess finalizers combine the visible keys with
those acknowledgements to account for Search's near-real-time visibility delay.
Repeated keys count once; failed writes are not added. Acknowledged deletions are
removed even if still visible in Search. Tracking is reset on success, failure,
and private screening extraction. Partial ingestion failures retain the failure
status and attempt to record the actual successful partial count; a failed count
lookup is logged rather than converted to success.

The **0.261.401** follow-up captures deletion receipts inside the shared Search
write boundary, before batch validation or fence cleanup can raise. Both whole-
document and version-specific deletes use the SDK's `delete_documents(documents=...)`
entry point. Only requested keys with successful receipts are removed from the
tracked count; failed, missing and unrelated receipts do not invent deletions.
This fixes stale Search visibility incorrectly retaining acknowledged deletes
during failed-reprocess reconciliation. The original follow-up gap was that the
whole-document path recorded all requested keys only after the wrapper returned,
and the version-specific path recorded no receipts and used an invalid `actions`
keyword in place of the SDK's required `documents` argument.

Authoritative counts carry `indexed_chunk_count_version`, bound to the source
version. A new processing attempt invalidates that binding until its actual
count is recorded. Screened publication records the same binding.

The shared upload finalizer now persists `num_chunks` across personal, group, and
public workspaces, including single, batch, audio and video paths. Source-file
chunking remains separate: an unsplit source starts at one, Document Intelligence
keeps its existing split count, and audio records the actual WAV split count or
one when using the source-file transcription fallback. No Search chunk count is
copied into `num_file_chunks`.

`update_document()` clears only the exact old metadata warning when the newly
persisted metadata outcome is `succeeded`, content is available, and the caller
has not supplied a newer processing status. The cleanup uses an ETag-conditional
save, so a concurrent reprocess or hold cannot be overwritten by this transition.
Failed, empty, disabled, and running metadata outcomes do not clear the warning.
Existing nonempty user metadata and source version are not regenerated.

The shared safe serializer represents unrecorded historical zero counts as
`num_chunks: null` (unknown), not as a numeric claim that Search is empty. Known
positive legacy counts and version-bound current counts (including genuine zero)
are preserved. A lifecycle message alone does not prove that the index is empty;
an unrecorded zero or stale version binding is unknown. V2 already renders an
unknown count as an em dash; its API type now allows null.

Access-index rows and candidate queries include the counter, version binding,
physical-file count, and metadata outcome. Redis cache hits normalize historical
unrecorded zeros in memory; no Search query or durable backfill is needed for a
list. Ordinary source updates continue to invalidate the cache and project new
recorded counts.

## Existing records and usage

Completed document detail reads with an unrecorded count obtain
the current version's actual Search key count without writing to Cosmos. Details
also reconcile an already-succeeded metadata outcome with the exact legacy warning.
Personal/public details use the shared detail helper; group details apply the same
behavior only after membership, share approval and screening projection.
Pending and held documents do not trigger this compatibility lookup.

A verified detail count survives the final fresh-source response guard through
request-local state bound to document ID, owning scope, source version and ETag.
It is not trusted across source changes, different scopes or later requests.
No client-supplied count is treated as verified.

Refreshing document details is sufficient to stop displaying a historical bogus
zero or obsolete metadata warning. It does not require re-upload, extraction,
embedding, transcription or another metadata-model call. Ordinary future successful
metadata retries also persist the warning cleanup.

Lists/grid responses show an unknown count for historical unrecorded zeros without
scanning Search for every row. Details show the verified current-version count.
This is not a bulk historical migration: raw historical Cosmos records can still
retain their old counters/status until a separately approved repair or an ordinary
applicable processing operation persists them. Historical
physical file splits cannot reliably be reconstructed from Search, so a stored
media `num_file_chunks=0` is not replaced with a guessed value. A durable backfill
would need a separately approved, scoped metadata-only maintenance operation with
ETag protection; none was run as part of this fix.

## Validation and impact

`functional_tests/test_document_chunk_bookkeeping.py` executes the real writers,
upload/reprocess finalizers, metadata-only worker, detail compatibility helper and
conditional update. Offline cases cover all three workspace scopes, multiple
upload sub-batches, duplicate overwrites, skipped empty text, partial write failure,
delayed visibility, deletion/reprocess, exact version/scope filters, more than
2,500 keys, audio split/fallback metrics, preserved metadata, newer statuses,
screening holds, safe lookup errors, request/ETag-bound detail revalidation,
known zero versus unknown, Redis cache hits and invalidation in all three scopes,
and installed-SDK conditional Cosmos writes.

The deletion follow-up executes both real delete entry points and the shared
write boundary with SDK `IndexingResult` receipts from an offline Search double.
It covers successful, failed, missing and unrelated receipts, cleanup exceptions,
and stale visibility in every workspace scope. Reprocess regressions now use
the real whole-document delete function rather than a replacement, including
partial-delete and cleanup-failure reconciliation. Deletion-path tests no longer
call the receipt recorder directly to simulate a completed delete.

The existing workspace metadata, Search projection, group read, OneNote dispatch,
processing status and screening suites protect related behavior. The group read
regression verifies that pending shares and held content do not query Search for
compatibility bookkeeping.

`ui_tests/test_v2_group_documents.py` exercises unknown, genuine zero and positive
counts in the production SPA on desktop and mobile using closed local HTTP
fixtures. Those six cases passed; TypeScript checking and the production build
also passed.

Recorded local results:

| Check | Result |
| --- | --- |
| Initial 0.261.400 bookkeeping suite, including release-proof and fence-cleanup failure cases | 106 passed. |
| 0.261.401 real deletion entry points and failed-reprocess cases | 51 passed normally; 51 passed under optimized Python. |
| 0.261.401 complete bookkeeping and existing Search/fence/projection consumer suites | 232 passed; four subtests passed. |
| Broad metadata, scoped reads, status predicates, OneNote and projection regression pass | 484 passed; 15 subtests passed. |
| Screening, source-read and group/public fixture parity | 272 passed; 50 subtests passed; three pre-existing model-fixture cases excluded. |
| Final strict count policy and fence-cleanup cases under optimized Python | 11 passed. |
| Core installed-SDK Cosmos contracts, excluding the existing inventory gate failure | 61 passed. |
| Desktop/mobile production-SPA count rendering | Six passed. |
| Documentation coverage and site quality | 13 checks passed. |
| V2 typecheck, production build and whitespace check | Passed; existing bundle-size warning remains. |

The full Cosmos inventory gate remains blocked by 30 pre-existing fingerprint
discrepancies in unmodified `route_backend_chats.py`; the bookkeeping storage
boundaries were regenerated and reviewed. Three older screening-model tests
expect an imported endpoint helper to be a local AST definition. Nine older
Wave 6 cache tests seed backfill schema 2 although the unchanged readiness logic
requires schema 3. Those unrelated fixtures were not rewritten; the new cache
regressions use the actual schema and pass in all three workspace scopes.

No live beta UI, cloud record, settings, inference operation, role, secret,
storage lock or backup configuration was accessed or changed.
