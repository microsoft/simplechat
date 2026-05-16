# Chat Toolbar Desktop Mobile Parity Fix

Fixed/Implemented in version: **0.241.024**

## Issue Description

The previous chat toolbar change still treated desktop and mobile as the same layout surface.

That caused desktop tool buttons to be grouped and repositioned in ways that did not match the intended inline toolbar, while mobile prompts and agents still behaved inconsistently with the new drawer-based interaction model.

The mobile tools drawer itself also rendered the action buttons in a cramped presentation that made the surface feel unfinished.

## Root Cause Analysis

`application/single_app/templates/chats.html` still used a single toolbar surface for both the desktop rail and the mobile tools drawer.

`application/single_app/static/css/chats.css` then had to style that same surface for conflicting breakpoint behaviors, which leaked mobile drawer structure back into desktop layout.

`application/single_app/static/js/chat/chat-mobile-toolbar.js` only managed offcanvas open and close state. It did not relocate the shared toolbar controls by breakpoint, so prompt and agent selectors could still appear outside the mobile drawer flow.

## Technical Details

Files modified: `application/single_app/config.py`, `application/single_app/templates/chats.html`, `application/single_app/static/css/chats.css`, `application/single_app/static/js/chat/chat-mobile-toolbar.js`, `functional_tests/test_chat_searchable_selectors.py`, `ui_tests/test_chat_mobile_toolbar_compaction.py`

Code changes summary:

- Split the chat toolbar into explicit desktop and mobile destinations in `chats.html` instead of keeping a shared inline and offcanvas container.
- Restored a stable desktop tools rail on the left side of the toolbar.
- Converted the mobile tools surface to an `offcanvas-bottom` drawer so it slides upward from the bottom instead of dropping from the top.
- Added dedicated mobile selector slots so prompt and agent selectors stay inside the mobile drawer rather than reopening inline.
- Updated `chat-mobile-toolbar.js` to move the shared toolbar surfaces between desktop and mobile slots at the `lg` breakpoint and to keep prompt and agent interactions inside the mobile drawer.
- Reworked the mobile drawer styling in `chats.css` so action buttons render as readable full-width controls instead of compressed icon pills.

Impact analysis:

- Desktop chat no longer inherits the mobile drawer grouping behavior.
- Mobile tools now open from the bottom in a format that is visually closer to the composer-driven chat flow.
- Prompt and agent selection now follow the same mobile drawer interaction instead of mixing drawer and inline patterns.

## Validation

Test coverage: `functional_tests/test_chat_searchable_selectors.py`, `ui_tests/test_chat_mobile_toolbar_compaction.py`

Test results:

- `functional_tests/test_chat_searchable_selectors.py`: updated to validate the split desktop/mobile toolbar contract.
- `ui_tests/test_chat_mobile_toolbar_compaction.py`: updated to validate that the prompt selector stays inside the mobile drawer.

Before/after comparison:

- Before: Desktop inherited the mobile drawer grouping, the tools sheet opened from the top, and mobile prompt selection escaped back into the inline toolbar row.
- After: Desktop keeps a fixed inline tool rail, the mobile tools drawer opens upward from the bottom, and mobile prompt or agent selection stays within the drawer.

Related config.py version update: `VERSION = "0.241.024"`