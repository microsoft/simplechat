# Whole Sidebar Scroll Fix

## Issue

Issue #1098 reported that the Conversations list had its own scrollbar while the navigation sections above it could become difficult to reach on shorter displays or at increased browser zoom.

**Fixed in version: 0.250.002**

## Root cause

The sidebar already had an outer scrollable content region, but the Conversations section also used flex growth, a viewport-based maximum height, and an independently scrollable conversation list. These nested overflow constraints isolated scrolling to the conversation rows instead of allowing the complete navigation body to move.

## Technical details

### Files modified

- `application/single_app/templates/_sidebar_nav.html`
- `application/single_app/templates/_sidebar_short_nav.html`
- `application/single_app/static/css/sidebar.css`
- `application/single_app/config.py`
- `functional_tests/test_sidebar_whole_panel_scroll.py`
- `ui_tests/test_chat_sidebar_whole_panel_scroll.py`

### Code changes

- Made the shared sidebar content region the single vertical scroll container in both navigation layouts.
- Removed the nested height and overflow constraints from the Conversations section and list.
- Moved the existing light and dark scrollbar styling to the whole sidebar content region.
- Kept the Conversations heading pinned at the top after it reaches the visible scroll boundary.
- Preserved the fixed sidebar header and user account footer.

## Testing and impact

The standalone functional regression test protects the shared template and CSS structure. The Azure Playwright regression test uses a constrained-height viewport and a long conversation list in both full-sidebar and top-navigation chat layouts. It verifies that New Chat is visible at the top, the conversation list has no independent scrollbar, later conversations remain reachable, and the Conversations heading remains pinned while scrolling.

The change affects sidebar layout only. Conversation loading, search, selection actions, menu collapse state, workflows, and navigation behavior are unchanged.

## Validation

### Before

Only conversation rows scrolled, leaving the upper sidebar navigation constrained and requiring users to collapse menus to recover space.

### After

The complete navigation body scrolls as one panel. Users can return to Chat or New Chat at the top, and the Conversations heading remains visible while they browse later conversations.
