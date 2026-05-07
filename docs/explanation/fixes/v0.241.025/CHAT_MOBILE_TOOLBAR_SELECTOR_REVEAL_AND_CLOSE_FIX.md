# Chat Mobile Toolbar Selector Reveal And Close Fix

Fixed/Implemented in version: **0.241.025**

## Issue Description

The mobile chat tools drawer still had three usability defects after the desktop and mobile toolbar split.

Unselected toolbar buttons could render without visible text inside the mobile drawer, prompt and agent activation could leave the actual selector controls below the fold, and the drawer close button could still trigger a Bootstrap offcanvas error even though tapping outside the drawer worked.

## Root Cause Analysis

The mobile drawer reused button classes that were originally designed for the desktop compact pill behavior.

Those desktop rules hid label text by default using `opacity: 0` and `width: 0`, which meant the mobile drawer could still inherit invisible labels even after forcing the label spans to display.

The prompt and agent selector containers were already moved into the mobile drawer, but the activation flow in `application/single_app/static/js/chat/chat-prompts.js` and `application/single_app/static/js/chat/chat-agents.js` did not tell the drawer to reveal or focus those selectors.

The drawer close button in `application/single_app/templates/chats.html` still relied on Bootstrap's declarative `data-bs-dismiss="offcanvas"` path, which continued to produce the `backdrop` lifecycle error in this specific mobile tools drawer path.

## Technical Details

Files modified: `application/single_app/config.py`, `application/single_app/templates/chats.html`, `application/single_app/static/js/chat/chat-mobile-toolbar.js`, `application/single_app/static/js/chat/chat-prompts.js`, `application/single_app/static/js/chat/chat-agents.js`, `application/single_app/static/css/chats.css`, `functional_tests/test_chat_searchable_selectors.py`, `ui_tests/test_chat_mobile_toolbar_compaction.py`

Code changes summary:

- Replaced the mobile tools drawer header close button with an explicit JavaScript close path instead of Bootstrap's `data-bs-dismiss` data API.
- Added a mobile-toolbar helper that closes open prompt and agent dropdowns before hiding the drawer.
- Added a mobile-toolbar reveal helper that scrolls the active selector into view and opens the prompt or agent dropdown after activation.
- Updated the prompt and agent activation handlers to dispatch a shared mobile selector activation event.
- Added mobile-specific toolbar rules so unselected button labels remain visible inside the drawer while desktop buttons keep their compact hidden-label behavior.

Impact analysis:

- Mobile users can see button labels before selection.
- Prompt and agent activation now leads directly to the relevant chooser instead of forcing users to hunt for it lower in the drawer.
- The mobile drawer close button now uses the same stable programmatic offcanvas hide path that already worked when dismissing the drawer externally.

## Validation

Test coverage: `functional_tests/test_chat_searchable_selectors.py`, `ui_tests/test_chat_mobile_toolbar_compaction.py`

Test results:

- `functional_tests/test_chat_searchable_selectors.py`: passed `9/9` checks after adding assertions for safe close wiring and selector reveal behavior.
- `ui_tests/test_chat_mobile_toolbar_compaction.py`: updated to verify the dedicated mobile close button and prompt dropdown reveal behavior.
- `ui_tests/test_chat_mobile_toolbar_compaction.py`: skipped in the current environment because `SIMPLECHAT_UI_BASE_URL` and authenticated UI state are not configured.

Before/after comparison:

- Before: Mobile button labels could disappear, prompt and agent toggles did not reliably reveal their selectors, and the drawer X could still throw a Bootstrap `backdrop` error.
- After: Mobile button labels remain readable, prompt and agent toggles scroll and open their selector controls inside the drawer, and the drawer X uses a stable programmatic close path.

Related config.py version update: `VERSION = "0.241.025"`