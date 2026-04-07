# Chat Citation Page Sort Fix (v0.240.055)

Fixed/Implemented in version: **0.240.055**

## Header Information

### Issue Description

Streaming chat could fail after hybrid search completed when the citation list included both numeric page numbers and text page labels such as `Metadata` or `AI Vision`.

This surfaced as `TypeError: '<' not supported between instances of 'int' and 'str'` while the backend tried to sort hybrid citations before finishing the response.

### Root Cause Analysis

`application/single_app/route_backend_chats.py` sorted hybrid citations with `page_number` directly as the key.

Search chunk citations typically use numeric page values, but metadata-derived citations and vision citations use text labels. Python cannot compare those mixed types during sort, so the response failed after retrieval succeeded.

### Version Implemented

`0.240.055`

## Technical Details

### Files Modified

- `application/single_app/route_backend_chats.py`
- `application/single_app/config.py`
- `functional_tests/test_chat_citation_page_sort_fix.py`

### Code Changes Summary

- Added `_coerce_citation_sort_number` to safely normalize numeric citation page or chunk values.
- Added `_build_hybrid_citation_sort_key` so hybrid citations sort deterministically when `page_number` mixes integers, numeric strings, and text labels.
- Updated both standard and streaming chat retrieval paths to use the shared helper instead of sorting directly on raw `page_number` values.
- Preserved descending ordering for numeric page citations while keeping metadata-style citations stable and non-crashing.
- Bumped the application version to `0.240.055`.

## Validation

### Testing Approach

- Added `functional_tests/test_chat_citation_page_sort_fix.py`.
- Verified numeric strings and numeric page values normalize correctly for sorting.
- Verified mixed numeric and text page labels sort without raising type errors.
- Verified both standard and streaming chat paths call the shared citation sort helper.

### Impact Analysis

- Streaming chat no longer crashes after successful retrieval when metadata citations are present.
- Standard chat now uses the same safer citation ordering logic, which removes the same latent mixed-type failure there.
- Citation ordering remains deterministic across page excerpts, metadata citations, and AI vision citations.