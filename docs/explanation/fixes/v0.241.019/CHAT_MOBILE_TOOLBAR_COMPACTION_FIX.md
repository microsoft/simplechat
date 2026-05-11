# Chat Mobile Toolbar Compaction Fix

Fixed/Implemented in version: **0.241.019**

## Issue Description

The chats page still felt like a desktop toolbar compressed into a phone-sized column even after the navigation shell was unified.

On smaller screens, action buttons, selectors, and toggle controls competed for the same horizontal space. That forced the toolbar to wrap into multiple dense rows and made prompt or agent controls feel disconnected from the primary message composer.

## Root Cause Analysis

The mobile chat composer reused the same flat toolbar grouping as desktop in `application/single_app/templates/chats.html`.

That layout worked for wide viewports, but it kept too many controls visible at the same time on mobile. The prompt, agent, model, reasoning, and TTS controls all lived in the same visual layer, with no progressive disclosure for lower-frequency actions.

## Technical Details

Files modified: `application/single_app/config.py`, `application/single_app/templates/chats.html`, `application/single_app/static/css/chats.css`, `application/single_app/static/js/chat/chat-conversation-info-button.js`, `application/single_app/static/js/chat/chat-mobile-toolbar.js`, `functional_tests/test_chat_toolbar_layout.py`, `functional_tests/test_chat_navigation_unified_shell.py`, `ui_tests/test_chat_mobile_toolbar_compaction.py`

Code changes summary:

- Reshaped the chats toolbar into a mobile quick-action rail plus a secondary tools panel in `chats.html` while preserving the existing button and selector IDs used by chat modules.
- Kept the model selector as the primary always-available control and moved prompt, agent, reasoning, and TTS controls into a collapsible mobile tools region.
- Added responsive toolbar styling in `chats.css` so mobile actions scroll horizontally instead of wrapping into a dense stack.
- Added `chat-mobile-toolbar.js` to automatically expand the mobile tools panel when prompt or agent selectors become visible.
- Switched the conversation info button visibility handling to Bootstrap-friendly `d-none` class toggling.

Impact analysis:

- Mobile chat now exposes the most common actions without forcing the full selector stack into view.
- Secondary controls remain available but no longer dominate the initial composer layout.
- Prompt and agent flows still reveal their selectors automatically, so the new compaction does not hide active controls behind a closed panel.

## Validation

Test coverage: `functional_tests/test_chat_toolbar_layout.py`, `functional_tests/test_chat_navigation_unified_shell.py`, `ui_tests/test_chat_mobile_toolbar_compaction.py`

Test results:

- Validates the template exposes the quick-action rail, primary model selector wrapper, and collapsible mobile tools panel.
- Validates the responsive CSS enables horizontal action scrolling and stacked secondary controls at mobile breakpoints.
- Validates the mobile toolbar coordination script expands the tools panel when prompt or agent selectors are activated.
- Validates in the browser that the mobile tools panel starts collapsed, opens on demand, and auto-reveals when prompt controls are activated.

Before/after comparison:

- Before: Mobile chat reused the full desktop toolbar with wrapping controls and no progressive disclosure.
- After: Mobile chat presents a compact quick-action rail, keeps the model selector prominent, and reveals the remaining controls through an explicit tools panel.

Related config.py version update: `VERSION = "0.241.019"`