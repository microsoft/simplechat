# V2 mobile layout fix

Fixed/Implemented in version: **0.261.323**
(`application/single_app/config.py`).

## Issue and root cause

The mobile shell reserved 68px for a permanent global icon rail even when its
drawer was closed. Workspaces retained another 48px section rail plus spacing.
The composer mixed selectors and primary actions in a wrapping row, while the
document table required at least 42rem of width. Together these desktop
assumptions crowded phone input and document browsing.

## Technical changes

`AppShell.tsx`, `MobileNavigation.tsx`, `Sidebar.tsx`, and `PageHeader.tsx`
share mobile navigation/header composition. The drawer consumes no closed
width and retains focus handling, backdrop/Escape dismissal, conversation
history, and mobile state separate from desktop preferences. The same
notification bell is hosted by the mobile header.

`ChatPage.tsx` discloses conversation actions and exposes New chat.
`Composer.tsx` separates a stable primary action row from secondary tools on
phones. Existing state and handlers continue to own selections, gating,
uploads, approval, and generation. `ComposerHighlight.tsx` keeps input and
overlay typography synchronized.

`WorkspaceShell.tsx` discloses permitted sections instead of reserving a
mobile column. Shared workspace pickers disclose search on small phones.
`DocumentTable.tsx` reuses document rows with wrapped names, visible selection,
status/classification/restriction information, and access to full details.
The explorer retains its existing scoped APIs, permission checks, dialogs,
view modes, and desktop column preferences. `ExplorerCommandBar.tsx` discloses
view options on phones so the toolbar leaves room for document rows.

`theme.css` and `index.html` add dynamic viewport sizing, safe-area support,
and scoped mobile touch targets without disabling browser zoom. No separate
mobile routes, new settings, dependencies, or authorization changes are added.

## Validation

### Explicit fixture registration (0.261.324)

The mobile UI tests reuse pytest fixtures that pytest discovers by module-level
name, not by direct calls. PR #1750's unused-import feedback is addressed by
explicit `pytest_plugins` registration, retaining standalone fixture discovery
without unused `from` imports. This test-maintenance follow-up is recorded in
`application/single_app/config.py`; mobile application behavior is unchanged.

Regression coverage is in `functional_tests/test_v2_mobile_layout.py` and
`ui_tests/test_v2_mobile_navigation.py`,
`ui_tests/test_v2_mobile_chat_layout.py`, and
`ui_tests/test_v2_mobile_workspace_documents.py`.

Browser tests use production components and CSS with synthetic HTTP boundaries.
They cover closed navigation width, focus return, drawer scrolling, primary
composer alignment, document selection/details, all three document scopes,
theme variants, and desktop preferences after resizing.

The focused mobile suite passed **23 tests**, including enlarged text and a
classification banner. Existing group/public document layout cases passed
**8 tests**, and shared workspace overview/contextual-action layout cases passed
**12 tests**. The related mobile, account-menu, workspace-section, and document
functional contracts passed **40 tests**. Documentation coverage and site-quality
checks passed **7/7** and **6/6**, respectively. TypeScript and production builds
completed successfully; Vite retains its existing large-bundle warning.

Before: permanent rails narrowed the phone pane and the document table required
horizontal scrolling. After: closed navigation consumes no phone width and the
same document rows adapt without replacing desktop preferences.

Real iPhone Safari keyboard, browser chrome, and home-indicator verification
remain a manual device check; Chromium emulation does not prove those behaviors.
