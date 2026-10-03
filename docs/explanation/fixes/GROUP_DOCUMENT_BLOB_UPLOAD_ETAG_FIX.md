# Group Document Blob Upload Etag Fix

Fixed in version: **0.261.217**

## Issue

With Enhanced Citations turned on, every document uploaded to a group workspace failed. The document row showed "Document processing failed. Contact an administrator if the problem persists." within a few seconds of the upload. That covered files added in the workspace and Word and Markdown documents saved to a group by an agent or workflow. Personal workspace uploads were not affected.

The application log showed `Error uploading <file> to Blob Storage.` after the blob itself had been written successfully, with `[ENHANCED_CITATIONS] Blob upload failed.` and error type `ScreeningConflictError`.

## Root Cause

`upload_to_blob` reads the document record, uploads the source file, and then writes the blob location back with `_upsert_document_and_sync_access_index`. Since group document projections were fenced against concurrent changes, that write for a group document requires the record's etag to match the one it read.

Between the read and the write, `upload_to_blob` reported progress with `update_callback(status="Uploading ... to Blob Storage...")`. The callback updates the same Cosmos record, which issues a new etag, so the final write always saw a changed record and raised `ScreeningConflictError`. Personal documents without a screening marker use a plain upsert, so they were unaffected.

## Technical Details

Files modified:

- `application/single_app/functions_documents.py`
- `functional_tests/test_group_document_blob_upload_etag.py`
- `application/single_app/config.py`

`upload_to_blob` now posts the "Uploading ... to Blob Storage..." status before it reads the record. The read therefore returns the current etag, and the guarded write still rejects a change made by anyone else while the blob uploads.

## Validation

`functional_tests/test_group_document_blob_upload_etag.py` runs the real `upload_to_blob` and `_upsert_document_and_sync_access_index` definitions against an etag-tracking container:

- Group and personal uploads complete after their own status update, and the record gets its blob path.
- A group upload still fails when another writer changes the record during the blob upload.

Without the fix, the group upload test fails with `ScreeningConflictError`.
