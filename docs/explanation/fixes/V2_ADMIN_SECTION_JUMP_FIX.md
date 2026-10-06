# V2 Admin Section Jump Fix

## Issue

In V2 Admin Settings, links from one setting to another did not scroll to their
target. **Go to setting** in the App Role Requirements roster and **Configure
Enhanced Citations** in Content Screening cleared the search and the selected category,
then left the page where it was.

## Root cause

`goToSection` looked up the element `admin-section-<id>`. When section rendering moved
into `SettingsSection`, each card took the bare section id instead, so the lookup found
nothing and the scroll never ran. Clearing every filter on each jump also threw away the
category the administrator was working in.

## Fixed in version: **0.261.258**

The application version is maintained in `application/single_app/config.py`.

## Technical details

### Files modified

| File | Change |
| --- | --- |
| `application/v2_ui/src/pages/AdminSettingsPage.tsx` | `goToSection` and its scroll effect. |
| `application/v2_ui/src/components/admin/SettingsSection.tsx` | Cards add `scroll-mt-4`, and the title can take focus. |

### Code changes

- The scroll looks up the card by the section id it renders.
- A filter changes only when it hides the target: a search that leaves the target out
  is cleared, and a different category switches to the target's own category instead of
  to **All settings**. While Call agent edits are unsaved, a jump that would change
  category is refused with the same message the category rail uses.
- The jump scrolls smoothly unless the browser asks for reduced motion, then focuses the
  section heading so keyboard and screen reader users land where the page shows.

The Model Catalog's **Open in AI Connections** uses the same path.

## Validation

- `functional_tests/test_v2_admin_settings_layout.py` fails if the page looks up the old
  `admin-section-` id again, and checks the reduced-motion handling.
- `ui_tests/test_v2_admin_settings_wide_layout.py` checks that a jump moves the pane and
  focuses the section heading.
- `ui_tests/test_v2_admin_model_catalog_workbench.py` checks that a jump clears a search
  that hid AI Connections and brings the section into view.

Before: the link cleared filters and the page did not move. After: the target section
scrolls into view with its heading focused, and the current category is kept when it
already shows the target.

Related: [V2 Admin Settings Layout and Hierarchy](../features/V2_ADMIN_SETTINGS_LAYOUT_AND_HIERARCHY.md).
