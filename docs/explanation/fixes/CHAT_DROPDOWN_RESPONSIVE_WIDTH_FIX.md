# Chat Dropdown Responsive Width Fix

Fixed in version: **0.242.017**

## Issue Description

The chat pane workspace scope, tags, and document dropdown menus were capped to narrow trigger widths. Long workspace names, tag labels, and document titles were truncated too aggressively, especially when users opened the grounded search controls from the compact chat toolbar.

## Root Cause Analysis

The dropdown menu width was controlled in several places at once: inline template styles, fixed CSS max-width rules, and JavaScript runtime sizing that set each popup menu `maxWidth` to the trigger field width. Because the same controls are reused in the mobile grounded-search drawer, the behavior affected desktop and mobile layouts.

## Technical Details

Files modified:

- `application/single_app/templates/chats.html`
- `application/single_app/static/css/chats.css`
- `application/single_app/static/js/chat/chat-documents.js`
- `ui_tests/test_chat_search_panel_mobile_drawer.py`
- `functional_tests/test_chat_searchable_selectors.py`
- `application/single_app/config.py`

Code changes summary:

- Replaced inline dropdown menu widths with a shared `chat-search-filter-menu` class.
- Updated the shared search-filter dropdown sizing helper to use viewport-aware desktop bounds and full drawer-width mobile sizing.
- Configured the document dropdown to open upward on desktop and downward in the mobile grounded-search drawer using Popper placement instead of CSS-forced positioning.
- Refreshed Bootstrap dropdown placement after responsive sizing so the desktop document menu remains visible above the composer.
- Added label overflow rules so long item text truncates inside the expanded popup instead of forcing viewport overflow.

## Testing Approach

- Extended the Playwright chat grounded-search drawer test to validate dropdown bounds in both desktop and mobile viewports.
- Extended the chat searchable selector functional test to verify the responsive sizing helper and prevent the old `maxWidth = containerWidth` cap from returning.

## Impact Analysis

Desktop dropdown menus can now grow beyond narrow trigger fields while staying within the viewport. The document dropdown opens upward from the desktop composer through Bootstrap/Popper placement so it remains interactive above the message box. Mobile dropdowns remain constrained to the grounded-search drawer width and open downward inside that drawer, so the change improves readability without causing offcanvas overflow.

## Validation

Before the fix, scope, tags, and document menus could be hard capped to widths like 250px or the narrow trigger field width. After the fix, desktop menus use a wider responsive popup and mobile menus stay aligned to the drawer fields.

Related tests:

- `ui_tests/test_chat_search_panel_mobile_drawer.py`
- `functional_tests/test_chat_searchable_selectors.py`

Config version updated in `application/single_app/config.py` to **0.242.017**.