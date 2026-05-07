# Chat Navigation And Grounded Search Drawer Fix

Fixed/Implemented in version: **0.241.022**

## Issue Description

The chat shell still had two visible problems after the earlier navigation unification work.

On mobile, the chat navigation drawer could crash when the user clicked the close button in the drawer header. The browser surfaced a Bootstrap error about reading `backdrop` from an undefined object.

On desktop, users in top-nav mode could land on chats with no obvious header navigation, because the desktop top-nav link surface had been removed while the mobile hamburger remained mobile-only.

The grounded-search panel also still behaved like an inline desktop filter row on phones. It consumed too much vertical space and did not match the drawer-first mobile interaction model already used elsewhere in the chat shell.

## Root Cause Analysis

The mobile chat rail offcanvas in `application/single_app/templates/_sidebar_short_nav.html` was being initialized through both `application/single_app/static/js/navigation.js` and `application/single_app/static/js/sidebar.js`. That duplicate ownership corrupted the Bootstrap offcanvas lifecycle and could break close-button dismissal on mobile.

Separately, `application/single_app/templates/_top_nav.html` explicitly removed the desktop primary navigation when `request.endpoint == 'chats'`, which left top-nav users without a visible desktop navigation surface on the chats page.

The grounded-search panel in `application/single_app/templates/chats.html` still used the same inline container for every viewport, while several JS paths in `application/single_app/static/js/chat/chat-documents.js` and `application/single_app/static/js/chat/chat-onload.js` opened it with direct `style.display = 'block'` writes. That made it difficult to present the same surface as a drawer on mobile.

## Technical Details

Files modified: `application/single_app/config.py`, `application/single_app/static/js/sidebar.js`, `application/single_app/templates/_top_nav.html`, `application/single_app/static/css/navigation.css`, `application/single_app/templates/chats.html`, `application/single_app/static/js/chat/chat-documents.js`, `application/single_app/static/js/chat/chat-onload.js`, `application/single_app/static/css/chats.css`, `functional_tests/test_chat_navigation_unified_shell.py`, `functional_tests/test_chat_searchable_selectors.py`, `ui_tests/test_chat_sidebar_toggle_controls.py`, `ui_tests/test_chat_search_panel_mobile_drawer.py`

Code changes summary:

- Stopped `sidebar.js` from creating a second Bootstrap offcanvas instance for the chat rail and changed it to dismiss only the existing instance created through Bootstrap’s normal lifecycle.
- Restored desktop top-nav links on chats by rendering the desktop nav surface for chat pages again and adding compact chat-specific header styling.
- Converted the grounded-search surface into a shared inline desktop and `offcanvas-end` mobile container in `chats.html`.
- Added `showSearchDocumentsPanel()` and `hideSearchDocumentsPanel()` helpers in `chat-documents.js` so toolbar clicks, URL-parameter flows, and feature launches all open the same search surface consistently.
- Updated the mobile onload flows in `chat-onload.js` to stop bypassing the new shared search-panel open logic.
- Added responsive search-panel styling in `chats.css` so the grounded-search controls remain inline on desktop but open as an end-side drawer on mobile.

Impact analysis:

- Mobile chat drawer close-button interactions no longer depend on duplicate Bootstrap offcanvas ownership.
- Desktop top-nav users regain a visible chat header navigation surface without bringing back the old nested top-nav drawer behavior.
- Grounded search now follows the same mobile drawer interaction model as the rest of the chat shell, while preserving the existing selector IDs and desktop inline workflow.

## Validation

Test coverage: `functional_tests/test_chat_navigation_unified_shell.py`, `functional_tests/test_chat_searchable_selectors.py`, `ui_tests/test_chat_sidebar_toggle_controls.py`, `ui_tests/test_chat_search_panel_mobile_drawer.py`, `ui_tests/test_chat_mobile_toolbar_compaction.py`

Test results:

- `functional_tests/test_chat_navigation_unified_shell.py`: passed `4/4` checks.
- `functional_tests/test_chat_searchable_selectors.py`: passed `8/8` checks.
- `ui_tests/test_chat_sidebar_toggle_controls.py`: skipped in the current environment because the authenticated UI state was not available.
- `ui_tests/test_chat_search_panel_mobile_drawer.py`: skipped in the current environment because the authenticated UI state was not available.
- `ui_tests/test_chat_mobile_toolbar_compaction.py`: skipped in the current environment because the authenticated UI state was not available.

Before/after comparison:

- Before: The mobile chat drawer could crash on close, desktop top-nav chat had no clear header navigation, and the grounded-search panel stayed inline on mobile.
- After: The chat rail uses a single Bootstrap offcanvas lifecycle, desktop chat restores compact header navigation for top-nav users, and grounded search opens as a mobile end-side drawer while staying inline on desktop.

Related config.py version update: `VERSION = "0.241.022"`