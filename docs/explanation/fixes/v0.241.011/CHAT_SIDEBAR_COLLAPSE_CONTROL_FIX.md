# Chat Sidebar Collapse Control Fix

Fixed/Implemented in version: **0.241.011**

## Issue Description

On mobile chat layouts, the left-navigation collapse control was effectively missing on initial load, which left users without an obvious way to dismiss the sidebar.

On larger screens, the existing collapse button sat on top of the logo and app-title row, and the title was constrained with hard-coded truncation widths that made customized names look cramped or broken.

## Root Cause Analysis

The full sidebar template in `application/single_app/templates/_sidebar_nav.html` rendered the collapse button as an absolutely positioned icon button with the Bootstrap class `d-none d-sm-block`, which hid it below the `sm` breakpoint.

The same template also injected inline title-truncation styles that capped the brand title at `140px` or `80px`, even while `application/single_app/static/css/sidebar.css` forced the brand text to render at `20px`. That created unnecessary overlap pressure in the header row.

The chat-only short sidebar in `application/single_app/templates/_sidebar_short_nav.html` duplicated the collapse logic but did not render a matching primary toggle button, so chats using top navigation and the short sidebar variant were inconsistent with the full left-nav experience.

## Technical Details

Files modified: `application/single_app/templates/_sidebar_nav.html`, `application/single_app/templates/_sidebar_short_nav.html`, `application/single_app/static/css/sidebar.css`, `application/single_app/static/js/sidebar.js`, `application/single_app/config.py`, `ui_tests/test_chat_sidebar_toggle_controls.py`

Code changes summary:

- Moved the primary collapse control out of the full sidebar brand row and into a dedicated full-width control row underneath the logo/title area.
- Added the same full-width collapse control to the short chat sidebar so both sidebar variants expose a consistent primary toggle.
- Centralized the collapse and reopen behavior in `application/single_app/static/js/sidebar.js` and kept `window.toggleSidebar` available for existing integrations such as the chat tutorial.
- Moved the shared collapse-state, floating reopen button, sidebar-header, and title-truncation styling into `application/single_app/static/css/sidebar.css`.
- Added a UI regression that validates the control at both desktop and mobile viewport widths.

Impact analysis:

- Mobile users now see a clear collapse button on initial sidebar load instead of relying on a control that only appeared after collapse.
- Long or branded application titles have more available header space and no longer compete with an overlaid top-right collapse icon.
- Full sidebar and short chat sidebar modes now share one toggle implementation instead of carrying slightly different template-local behavior.

## Validation

Test coverage: `ui_tests/test_chat_sidebar_toggle_controls.py`

Test results:

- Validates that `#sidebar-toggle-btn` is visible when `/chats` loads at desktop and mobile viewport sizes.
- Validates that toggling collapse adds the expected collapsed sidebar state and reveals `#floating-expand-btn`.
- Validates that reopening the sidebar clears the collapsed body state without page or console errors.

Before/after comparison:

- Before: mobile chat users had no primary visible collapse control, and desktop brand rows could show a cramped title next to an overlaid icon button.
- After: both responsive layouts expose a clear primary collapse control, and the full sidebar header separates branding from navigation controls.

Related config.py version update: `VERSION = "0.241.011"`