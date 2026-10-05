# Document Metadata Chunk Sync Batching Fix

Fixed/Implemented in version: **0.261.051**

## Issue Description

Saving metadata for a large uploaded document could time out after users added or selected tags such as `bills`. The browser then attempted to parse the timeout response as JSON, which surfaced as an invalid JSON error instead of a useful completion path.

## Root Cause Analysis

The personal document metadata PATCH route updated the document record, then synchronously propagated tag metadata to every search chunk. The shared document update helper also propagated changed tag metadata to every chunk, so tag saves could perform duplicate full-document chunk updates during a single request.

## Technical Details

Files modified:

- `application/single_app/functions_documents.py`
- `application/single_app/route_backend_documents.py`
- `application/single_app/static/js/workspace/workspace-documents.js`
- `functional_tests/test_document_metadata_chunk_sync_batching.py`
- `application/single_app/config.py`

Code changes summary:

- Added bounded chunk-sync support to `update_document()` with `chunk_sync_limit`, `chunk_sync_offset`, and `chunk_sync_fields`.
- Updated the personal metadata route to apply metadata changes once and return chunk-sync progress when large chunk updates need continuation.
- Updated the workspace metadata form to continue the same PATCH request until chunk synchronization completes.
- Removed the duplicate immediate search chunk tag propagation call from the personal metadata route while preserving quick blob metadata tag updates.

## Validation

Validation coverage:

- `functional_tests/test_document_metadata_chunk_sync_batching.py` verifies that a large metadata sync returns a continuation after a bounded batch and resumes from the saved offset without requiring the document metadata to change again.

Expected user impact:

- Large XML and other high-chunk-count documents can finish metadata/tag saves across multiple shorter requests instead of timing out during one long request.