# V2 Admin Category Scroll Reset Fix

Fixed/Implemented in version: **0.261.260**

## Issue

In V2 Admin Settings, choosing a category in the left rail kept the scroll offset
the previous category was left at. An administrator who scrolled near the end of
**Knowledge** and then chose **Security** landed near the end of Security, not at
its first section. Choosing the category already shown did nothing, so it could
not be used to get back to the top either.

## Root cause

Every category renders into one shared scroll pane,
`data-testid="admin-settings-scroll"` in `AdminSettingsPage.tsx`. Choosing a
category only changed the `activeGroup` filter. The pane kept its `scrollTop`,
and the browser clamped it to the new content's height, so a long category opened
part-way down.

Scrolling to the top alone would leave one gap: `SettingsIndex` keeps a section
chosen from the **On this page** index pinned as current until the administrator
scrolls by hand. Its listeners are rebuilt only when the listed sections change,
so after choosing the category already shown it would still mark the pinned
section while the page sat at the top.

## Technical changes

### Files modified

| File | Change |
| --- | --- |
| `application/v2_ui/src/pages/AdminSettingsPage.tsx` | `selectCategory` sets the category, scrolls the pane to the top, and counts the visit. The rail buttons and the phone category select both use it, including when the category already shown is chosen again. `SettingsIndex` is keyed by the visit count, so it restarts and marks the category's first section. |
| `application/single_app/config.py` | Version `0.261.259` -> `0.261.260`. |

Cross-references that jump to a section, such as going from the Model Catalog to
AI Connections, still use `goToSection`, which switches category only when the
target is hidden and then scrolls to that section rather than to the top.

### Testing approach

`ui_tests/test_v2_admin_global_agents_actions.py` loads the built SPA with the
real field schema:

- `test_choosing_a_category_starts_at_its_top` scrolls a long category to its
  end, then checks that choosing another category, returning to the first, choosing
  the category already shown, and choosing **All settings** each open at
  `scrollTop` 0, and that the index marks the first section again.
- `test_choosing_a_category_on_a_phone_starts_at_its_top` checks the same through
  the phone's category select.

### Impact

Only rail and category-select choices are affected. Search, index jumps, and
cross-section links behave as before.

## Validation

Both browser tests fail when the scroll reset is removed from `selectCategory`,
timing out while waiting for `scrollTop` 0, and pass with it.

| Before | After |
| --- | --- |
| Choosing a category kept the previous category's offset. | Choosing a category always opens it at its first section. |
| Choosing the category already shown did nothing. | It returns to the category's top, and the index marks the first section. |
