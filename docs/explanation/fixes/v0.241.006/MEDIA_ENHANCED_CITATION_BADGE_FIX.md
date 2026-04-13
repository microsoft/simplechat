# Media Enhanced Citation Badge Fix

Fixed/Implemented in version: **0.241.007**

## Issue Description

Audio and video files uploaded while Enhanced Citations was enabled were stored in Azure Blob Storage and could open through the enhanced citation experience on the chat page, but the workspace document details panel still showed the citation mode as Standard.

## Root Cause Analysis

The workspace document list renders the citation badge from the persisted `enhanced_citations` field on the document metadata record.

Audio and video processing uploaded originals to blob storage, but the metadata record was not updated to set `enhanced_citations` to `true`.

At the same time, the chat-side enhanced citation metadata endpoint could still infer enhanced support from blob-backed document state, so chat behavior and workspace metadata drifted apart.

## Technical Details

Files modified: `application/single_app/functions_documents.py`, `application/single_app/route_enhanced_citations.py`, `application/single_app/config.py`, `functional_tests/test_media_enhanced_citations_metadata_flag.py`

Code changes summary:

- Added normalization helpers so blob-backed documents read back with `enhanced_citations=True` even when older records are missing that field.
- Updated `upload_to_blob()` to stamp `enhanced_citations=True` on the stored document metadata for new blob-backed uploads.
- Initialized new document metadata records with `enhanced_citations=False` so the field is always explicit.
- Updated the enhanced citation document metadata route to use the normalized per-document flag instead of inferring state from a derived blob path.

Impact analysis:

- Existing audio and video documents that already have persisted blob references now render the Enhanced badge in workspace details without requiring re-upload.
- New blob-backed uploads keep workspace metadata aligned with the chat enhanced citation experience.

## Validation

Test coverage: `functional_tests/test_media_enhanced_citations_metadata_flag.py`

Test results:

- Validates normalization of current and archived blob-backed documents to `enhanced_citations=True`.
- Validates that blob uploads stamp the document metadata with the enhanced citation flag.
- Validates that document list/detail reads and the enhanced citation metadata route use the normalized value.

Before/after comparison:

- Before: Blob-backed media could behave as enhanced in chat while still displaying Standard in workspace details.
- After: Workspace details and chat enhanced citation behavior use the same normalized document metadata state.

Related config.py version update: `VERSION = "0.241.007"`