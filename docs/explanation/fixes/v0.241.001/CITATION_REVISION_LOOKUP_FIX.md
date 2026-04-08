# Citation Revision Lookup Fix (v0.240.024)

Fixed/Implemented in version: **0.240.024**

## Header Information

### Issue Description

Moving forward, once document revisioning is active, older chat citations must continue to resolve against the exact document revision that was cited when the message was created.

The chat UI already preserves the citation chunk ID and enhanced citations already load documents by exact `doc_id`, but the text citation lookup route was still authorizing against mutable search chunk ownership fields instead of the exact document record behind the chunk.

### Root Cause Analysis

When an older personal revision is archived, chunk visibility updates rewrite the indexed chunk scope fields so the archived revision is no longer part of normal workspace search.

That is correct for search visibility, but it means the chunk record is no longer a reliable source of document ownership for historical citation lookup. The authoritative source is the exact document metadata record identified by `document_id`.

### Version Implemented

`0.240.024`

## Technical Details

### Files Modified

- `application/single_app/route_backend_documents.py`
- `application/single_app/config.py`
- `functional_tests/test_citation_revision_lookup_fix.py`

### Code Changes Summary

- Added citation helpers that extract the exact document ID behind the citation chunk.
- Updated `/api/get_citation` to authorize citation access by resolving the exact document record for personal, group, and public scopes.
- Kept citation content lookup keyed by the original chunk ID, while moving access checks to the revision-aware document metadata path.
- Bumped the application version to `0.240.024`.

## Validation

### Testing Approach

- Added `functional_tests/test_citation_revision_lookup_fix.py`.
- Verified citation document ID extraction prefers chunk metadata and falls back to the chunk ID prefix when needed.
- Verified citation access lookup uses the exact document ID across personal, group, and public scopes.
- Verified enhanced citations still resolve blob-backed content from exact document metadata.

### Impact Analysis

- New conversations and citations created after revisioning now continue to resolve the correct document revision by exact document ID.
- Historical text citations no longer depend on archived search chunk scope fields to prove ownership.
- Enhanced citations keep using the exact document record, including its stored blob path metadata, for revision-aware blob retrieval.