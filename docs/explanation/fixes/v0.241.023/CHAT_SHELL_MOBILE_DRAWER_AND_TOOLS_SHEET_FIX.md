# Chat Shell Mobile Drawer And Tools Sheet Fix

Fixed/Implemented in version: **0.241.023**

## Issue Description

The chat shell still had a final cluster of responsive issues after the earlier navigation unification work.

Desktop top-nav pages could still render content slightly underneath the fixed header because different parts of the shell were using different header heights.

On mobile, the chat drawer could open underneath the fixed header, which clipped the drawer header and made the surface feel broken.

The chat drawer also did not expose the workspace and global navigation routes that top-nav users needed, which forced users to bounce through Home just to reach Personal, Groups, or Public pages.

Finally, the mobile chat toolbar still rendered a cramped inline strip of low-frequency action buttons and relied on a collapse panel instead of a drawer-first mobile interaction model.

## Root Cause Analysis

The top navigation height contract was inconsistent across `application/single_app/static/css/navigation.css`, `application/single_app/static/css/sidebar.css`, and inline shell rules in `application/single_app/templates/base.html`. Some paths still padded for `56px`, while others positioned fixed chat surfaces using `66px` and `98px` offsets.

The mobile chat rail in `application/single_app/templates/_sidebar_short_nav.html` focused on conversations and support actions, but it did not reuse the workspace and external-link navigation content already present in `application/single_app/templates/_top_nav.html`.

The mobile chat toolbar in `application/single_app/templates/chats.html` still treated the low-frequency action buttons as an inline horizontal rail and used a `collapse`-based secondary panel. That was the wrong abstraction for small screens, because it expanded within the page flow instead of behaving like a bounded sheet above the selector row.

## Technical Details

Files modified: `application/single_app/config.py`, `application/single_app/static/css/navigation.css`, `application/single_app/static/css/sidebar.css`, `application/single_app/static/css/chats.css`, `application/single_app/templates/base.html`, `application/single_app/templates/_sidebar_short_nav.html`, `application/single_app/templates/chats.html`, `application/single_app/static/js/navigation.js`, `application/single_app/static/js/sidebar.js`, `application/single_app/static/js/chat/chat-mobile-toolbar.js`, `functional_tests/test_chat_navigation_unified_shell.py`, `functional_tests/test_chat_searchable_selectors.py`, `ui_tests/test_chat_sidebar_toggle_controls.py`, `ui_tests/test_chat_mobile_toolbar_compaction.py`

Code changes summary:

- Normalized the top-nav height to `66px` in `navigation.css` and reused that shared variable for drawer and rail offsets instead of keeping multiple hardcoded header heights.
- Offset the standard mobile top-nav drawer and the mobile chat rail below the fixed header so their headers are fully visible when opened.
- Added a mobile-only workspace and external-links section to the chat drawer in `_sidebar_short_nav.html` so top-nav chat users can navigate directly to Personal, Groups, Public, Chat, and external destinations from the drawer.
- Kept the chat rail out of the generic offcanvas initializer in `navigation.js` so the chat drawer retains a single Bootstrap ownership path.
- Reworked the chat toolbar in `chats.html` so the `Tools` trigger sits alongside the selector row on mobile while the low-frequency actions now live inside an `offcanvas-top` tools sheet.
- Replaced the old collapse-based mobile toolbar logic in `chat-mobile-toolbar.js` with offcanvas-based state management and dismiss-on-action behavior for the mobile tools sheet.
- Updated responsive toolbar styling in `chats.css` so the mobile tools sheet presents action buttons in a readable grid while desktop continues to render the same controls inline.

Impact analysis:

- Desktop top-nav pages and chat shells now share a consistent fixed-header spacing contract.
- Mobile chat and top-nav drawers open below the header instead of clipping behind it.
- Mobile top-nav chat users regain direct workspace and global navigation without leaving the chat shell.
- The chat toolbar no longer compresses low-frequency actions into a narrow inline strip on mobile.

## Validation

Test coverage: `functional_tests/test_chat_navigation_unified_shell.py`, `functional_tests/test_chat_searchable_selectors.py`, `ui_tests/test_chat_sidebar_toggle_controls.py`, `ui_tests/test_chat_mobile_toolbar_compaction.py`

Test results:

- `functional_tests/test_chat_navigation_unified_shell.py`: passed `4/4` checks.
- `functional_tests/test_chat_searchable_selectors.py`: passed `8/8` checks.
- `ui_tests/test_chat_sidebar_toggle_controls.py`: updated for the new mobile drawer content and offset behavior.
- `ui_tests/test_chat_mobile_toolbar_compaction.py`: updated for the mobile tools-sheet behavior.

Before/after comparison:

- Before: Header offsets were inconsistent, the mobile chat drawer clipped behind the fixed header, the mobile chat drawer omitted workspace navigation, and mobile toolbar actions stayed inline.
- After: Header offsets are shared, mobile drawers open below the header, the chat drawer exposes workspace routes directly, and the low-frequency mobile chat actions open in a dedicated tools sheet.

Related config.py version update: `VERSION = "0.241.023"`