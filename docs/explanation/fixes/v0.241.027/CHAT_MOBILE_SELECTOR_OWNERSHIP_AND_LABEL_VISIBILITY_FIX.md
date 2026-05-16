# Chat Mobile Selector Ownership And Label Visibility Fix

Fixed/Implemented in version: **0.241.027**

## Issue Description

The chat toolbar still had one mobile inconsistency after the earlier drawer fixes.

The model selector remained on the main page while the prompt and agent selectors lived inside the mobile drawer, which created two competing selector locations on small screens.

At the same time, inactive mobile drawer buttons could still render with missing labels because the compact desktop pill styles were continuing to collapse the text.

## Root Cause Analysis

`application/single_app/static/js/chat/chat-mobile-toolbar.js` only moved the prompt and agent selector surface into the drawer on mobile. The model selector stayed in its desktop wrapper, so mobile users had split selector ownership between the page and the drawer.

`application/single_app/static/css/chats.css` already contained a mobile label override, but the later base `.search-btn .search-btn-text` and `.file-btn .file-btn-text` rules still applied `opacity: 0` and `width: 0`, which could override the earlier mobile intent.

## Technical Details

Files modified: `application/single_app/config.py`, `application/single_app/templates/chats.html`, `application/single_app/static/js/chat/chat-mobile-toolbar.js`, `application/single_app/static/css/chats.css`, `functional_tests/test_chat_searchable_selectors.py`, `ui_tests/test_chat_mobile_toolbar_compaction.py`

Code changes summary:

- Added dedicated desktop and mobile slots for the model selector in `chats.html`.
- Updated `chat-mobile-toolbar.js` to move the model selector into the mobile drawer at small breakpoints and restore it to the desktop slot at larger breakpoints.
- Added a later mobile-only label visibility override in `chats.css` so the base compact button rules cannot collapse text inside the mobile drawer.
- Simplified the mobile toolbar control row because selector ownership now lives entirely inside the drawer.
- Updated source and UI regressions to validate mobile selector ownership and label visibility expectations.

Impact analysis:

- Mobile users now see model, prompt, and agent selection in one consistent location.
- Mobile tool buttons keep their labels visible while inactive.
- Desktop retains the existing inline model selector and compact inactive button behavior.

## Validation

Test coverage: `functional_tests/test_chat_searchable_selectors.py`, `ui_tests/test_chat_mobile_toolbar_compaction.py`

Test results:

- `functional_tests/test_chat_searchable_selectors.py`: passed `9/9` checks after updating the selector ownership and label visibility assertions.
- `ui_tests/test_chat_mobile_toolbar_compaction.py`: updated to assert the model selector appears inside the mobile drawer.
- `ui_tests/test_chat_mobile_toolbar_compaction.py`: skipped in the current environment because `SIMPLECHAT_UI_BASE_URL` and authenticated UI state are not configured.

Before/after comparison:

- Before: The model selector stayed on the mobile page while prompt and agent selection moved into the drawer, and inactive mobile tool buttons could still appear as icon-only rows.
- After: All toolbar selectors live in the drawer on mobile, and inactive mobile tool buttons display readable labels.

Related config.py version update: `VERSION = "0.241.027"`