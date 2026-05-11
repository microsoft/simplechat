# Chat Search Drawer Close Fix

Fixed/Implemented in version: **0.241.030**

## Issue Description

The grounded-search mobile drawer could still throw a Bootstrap offcanvas error when users pressed the close button.

The error path appeared specifically on the mobile `X` control for the grounded-search slider. The same control was also positioned high enough on the panel that it could be obscured by the floating tutorial launcher.

## Root Cause Analysis

`application/single_app/templates/chats.html` still used a `data-bs-dismiss="offcanvas"` close button for the grounded-search drawer even though the panel was already being opened and managed through explicit JavaScript in `application/single_app/static/js/chat/chat-documents.js`.

That meant the grounded-search drawer still relied on Bootstrap's declarative dismiss path while the rest of the mobile drawer lifecycle was being controlled programmatically. This reproduced the same offcanvas ownership issue that had already been fixed for the tools drawer.

## Technical Details

Files modified: `application/single_app/config.py`, `application/single_app/templates/chats.html`, `application/single_app/static/js/chat/chat-documents.js`, `application/single_app/static/css/chats.css`, `functional_tests/test_chat_searchable_selectors.py`, `ui_tests/test_chat_mobile_toolbar_compaction.py`

Code changes summary:

- Removed the Bootstrap auto-dismiss button from the grounded-search mobile header.
- Added a dedicated mobile footer close button in the bottom-right corner of the grounded-search slider.
- Updated `chat-documents.js` to use an explicit click handler for the new close control.
- Aligned the grounded-search offcanvas instance with the tools drawer pattern by using `toggle: false`.
- Closed open scope, tag, and document dropdowns before hiding the drawer and after the drawer finishes hiding.
- Updated functional and UI regressions to validate the explicit close wiring and the absence of uncaught page errors for the mobile drawer flow.

Impact analysis:

- Closing grounded search on mobile now uses one owner for the offcanvas lifecycle.
- The mobile close control sits at the bottom-right of the slider instead of being vulnerable to overlap with the tutorial launcher.
- The drawer leaves less stale dropdown state behind when it closes.

## Validation

Test coverage: `functional_tests/test_chat_searchable_selectors.py`, `ui_tests/test_chat_mobile_toolbar_compaction.py`

Test results:

- `functional_tests/test_chat_searchable_selectors.py`: passed `10/10` checks after updating the mobile grounded-search close contract.
- `ui_tests/test_chat_mobile_toolbar_compaction.py`: updated to exercise the grounded-search mobile close path and assert there are no uncaught page errors.
- `ui_tests/test_chat_mobile_toolbar_compaction.py`: still skips in the current environment because `SIMPLECHAT_UI_BASE_URL` and authenticated UI state are not configured.

Before/after comparison:

- Before: the grounded-search mobile `X` used Bootstrap auto-dismiss and could trigger a `backdrop` error while also sitting near the tutorial launcher.
- After: the grounded-search drawer closes through explicit JavaScript and the close control now lives in a bottom mobile footer.

Related config.py version update: `VERSION = "0.241.030"`