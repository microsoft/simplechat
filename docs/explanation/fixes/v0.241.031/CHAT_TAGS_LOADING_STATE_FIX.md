# Chat Tags Loading State Fix

Fixed/Implemented in version: **0.241.031**

## Issue Description

On the first grounded-search drawer open, the Tags control could appear to be missing until the initial scope refresh finished.

The control eventually appeared after the first tag request completed, but the initial empty space looked like a broken UI because users were given no indication that tag data was still loading.

## Root Cause Analysis

`application/single_app/templates/chats.html` rendered the Tags control hidden by default.

`application/single_app/static/js/chat/chat-documents.js` then opened the grounded-search drawer before the async document and tag refresh pipeline had completed. Because the tag filter was hidden rather than shown in a disabled loading state, the first open looked incomplete until the backend-backed tag requests finished.

## Technical Details

Files modified: `application/single_app/config.py`, `application/single_app/templates/chats.html`, `application/single_app/static/js/chat/chat-documents.js`, `application/single_app/static/css/chats.css`, `functional_tests/test_chat_searchable_selectors.py`, `ui_tests/test_chat_mobile_toolbar_compaction.py`

Code changes summary:

- Kept the Tags control visible in the grounded-search drawer instead of hiding it by default.
- Added a disabled loading presentation with an inline spinner and `Loading tags...` label.
- Added explicit loading, ready, and empty-state helpers in `chat-documents.js`.
- Introduced a shared document or tag refresh helper so scope changes and first drawer open use the same loading-state workflow.
- Preserved the previously loaded ready state on plain drawer reopen so the control does not flicker unnecessarily.
- Updated source and UI regressions to validate the visible Tags control on first drawer open.

Impact analysis:

- The first grounded-search drawer open now communicates that tag data is loading instead of making the control appear broken.
- Scope changes reuse the same loading-state behavior consistently.
- Reopening the drawer without changing scope keeps the already-resolved Tags state visible.

## Validation

Test coverage: `functional_tests/test_chat_searchable_selectors.py`, `ui_tests/test_chat_mobile_toolbar_compaction.py`

Test results:

- `functional_tests/test_chat_searchable_selectors.py`: passed `11/11` checks after adding the Tags loading-state contract.
- `ui_tests/test_chat_mobile_toolbar_compaction.py`: updated to assert the Tags control is visible when the search drawer opens on mobile.
- `ui_tests/test_chat_mobile_toolbar_compaction.py`: still skips in the current environment because `SIMPLECHAT_UI_BASE_URL` and authenticated UI state are not configured.

Before/after comparison:

- Before: the Tags control was hidden on first drawer open and only appeared after the async tag request completed.
- After: the Tags control is visible immediately, shows a disabled loading state while tag data is being fetched, and transitions to ready or empty messaging when the request finishes.

Related config.py version update: `VERSION = "0.241.031"`