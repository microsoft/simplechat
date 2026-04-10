# Historical Enhanced Citation Revision Rendering Fix (v0.240.025)

Fixed/Implemented in version: **0.240.025**

## Header Information

### Issue Description

Once document revisioning is enabled, users can open a newer revision in a new chat while still expecting older chat citations to render the exact archived PDF and tabular file that was cited originally.

The archived file content still exists in blob storage under the revision-aware path, but older chat citations were falling back to standard text/schema citations instead of opening the enhanced viewer.

### Root Cause Analysis

The chat page only keeps the current workspace document list in memory.

Older chat citations reference exact historical `doc_id` values that are no longer part of that current-only list. `showEnhancedCitationModal(...)` required in-memory metadata to determine the file type, so it treated older cited revisions as unknown documents and immediately fell back to standard citation rendering before the archived blob could ever be requested.

### Version Implemented

`0.240.025`

## Technical Details

### Files Modified

- `application/single_app/route_enhanced_citations.py`
- `application/single_app/static/js/chat/chat-documents.js`
- `application/single_app/static/js/chat/chat-enhanced-citations.js`
- `application/single_app/config.py`
- `functional_tests/test_historical_enhanced_citation_revision_rendering_fix.py`

### Code Changes Summary

- Added an enhanced citation metadata endpoint that resolves an exact `doc_id` across personal, group, and public workspaces.
- Added client-side caching and on-demand metadata fetch for cited revisions that are not present in the current workspace document list.
- Updated the enhanced citation modal flow so older chat citations can still render archived PDF and tabular content instead of falling back to standard text or schema citations.
- Bumped the application version to `0.240.025`.

## Validation

### Testing Approach

- Added `functional_tests/test_historical_enhanced_citation_revision_rendering_fix.py`.
- Verified the chat client now fetches exact document metadata on demand for historical cited revisions.
- Verified the enhanced citation backend exposes a metadata lookup route keyed by exact `doc_id`.
- Verified version and fix documentation alignment for `0.240.025`.

### Impact Analysis

- Older chat citations now keep rendering archived PDF and tabular content after a newer document revision becomes current.
- Current-only workspace document loading remains intact while historical citation rendering gains a revision-aware metadata lookup path.