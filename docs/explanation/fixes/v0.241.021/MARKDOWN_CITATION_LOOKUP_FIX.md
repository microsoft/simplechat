# Markdown Citation Lookup Fix

Fixed/Implemented in version: **0.241.021**

## Issue Description

Opening citations for Markdown and other text-derived documents could show a toast such as `Error fetching citation: Server responded with status 404`. The chat message still displayed the citation, but `/api/get_citation` could not always find the underlying AI Search chunk when the rendered citation id was stale, incomplete, or reconstructed from older stored citation metadata.

## Root Cause Analysis

The citation route only attempted an exact AI Search key lookup using the browser-supplied `citation_id`. Markdown chunks are indexed as document-scoped chunk keys such as `<document_id>_<chunk_number>`, but some stored or fallback-rendered citation buttons could supply only a chunk-derived id. Once the exact key lookup failed, the route moved through the workspace indexes and returned 404 without trying the document and chunk context already present in the citation metadata.

Enhanced citation fallback made the issue more visible for `.md` files because Markdown is not opened in the enhanced PDF/image/audio/video viewers. The browser fell back to text citation retrieval, but that fallback did not preserve document and page context.

## Technical Details

### Files Modified

- `application/single_app/route_backend_documents.py`
- `application/single_app/static/js/chat/chat-citations.js`
- `application/single_app/static/js/chat/chat-enhanced-citations.js`
- `application/single_app/static/js/chat/chat-messages.js`
- `application/single_app/config.py`
- `functional_tests/test_markdown_citation_lookup_fallback.py`
- `ui_tests/test_chat_markdown_citation_lookup_payload.py`

### Code Changes Summary

- Added citation lookup helpers that try exact keys first, then rebuild document-scoped chunk keys from `document_id`, `page_number`, and `chunk_id`.
- Added a final metadata query fallback for legacy chunks whose indexed key does not match the current `<document_id>_<chunk>` pattern.
- Kept the existing document access check in place after chunk resolution so recovered chunks still require authorized document visibility.
- Updated citation buttons to carry `data-document-id`, `data-page-number`, and `data-chunk-id` attributes.
- Updated text citation fetches and enhanced-citation fallbacks to send the extra lookup context to `/api/get_citation`.
- Bumped the application version to `0.241.021`.

## Testing Approach

- Added a functional regression test that loads the citation helper functions, simulates missing exact keys, and verifies markdown chunks are recovered by reconstructed key and metadata query fallback.
- Added source-level assertions that browser citation code sends document/page/chunk context through text and enhanced fallback paths.
- Added a Playwright UI regression that renders a markdown citation button without a stored `citation_id`, clicks it, and verifies the `/api/get_citation` payload includes the recovered document-scoped citation id plus lookup context.

## Validation

### Before

- `/api/get_citation` returned 404 as soon as exact key lookup failed across personal, group, and public indexes.
- Markdown enhanced-citation fallback could call text citation lookup without the document context needed to recover the chunk.

### After

- Exact citation IDs continue to work as before.
- Markdown/text citation buttons can recover the indexed chunk from document, page, and chunk metadata.
- Unauthorized or inaccessible documents still return access errors instead of exposing chunk text.

### User Experience Improvement

Users can open citations for Markdown files without the red 404 toast when the chat already has enough stored citation metadata to identify the source chunk.