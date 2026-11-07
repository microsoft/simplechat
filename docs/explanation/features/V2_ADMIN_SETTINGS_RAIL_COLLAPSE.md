# V2 Admin Settings Rail Collapse

## Overview

The V2 workspace pages let people collapse their section rail to icons to give the
content more room. V2 Admin Settings now does the same for its **Settings categories**
rail. A control at the top of the rail shrinks it from 14rem to a 4rem strip of category
icons, the settings cards take the freed width, and the choice is remembered per
administrator.

The admin page shares its width with up to three navigation columns: the application
shell's rail, the categories rail, and, on wide screens, the **On this page** index. The
categories rail is sized in `rem`, so it grows with the text size and reaches 448px at
the largest size. Collapsing it returns that room to the cards, and on mid-sized screens
can make room for the index, whose container query responds to the wider pane on its own.

## Implemented in version: **0.261.267**

The application version is maintained in `application/single_app/config.py`.

**Dependencies:** the React/TypeScript V2 UI, local `lucide-react` icons
(`PanelLeftClose`, `PanelLeftOpen`), and the `/api/user/settings` preference store. No new
packages, routes, admin settings, or browser asset sources are required.

## Technical specifications

### Behaviour

| State | Rail | Category entries | Control |
| --- | --- | --- | --- |
| Expanded (default) | `w-56` | Icon and label | `PanelLeftClose` with **Collapse** |
| Collapsed | `w-16` | Icon only; the label stays as screen-reader text and a `title` tooltip | `PanelLeftOpen` |

- The control is named "Collapse settings categories" or "Expand settings categories",
  and carries `aria-expanded` and `aria-controls="admin-settings-category-list"`.
- Category entries keep `aria-pressed` on the active category and stay locked while Call
  agent changes are unsaved. The collapse control is not locked, because it does not
  change the category.
- The width change animates, except when the browser asks for reduced motion.
- The rail is still drawn only at the `lg` breakpoint and above. Narrower windows use the
  existing **Settings category** select whatever the preference says.

### Persistence

| Key | Contents |
| --- | --- |
| `v2AdminRailCollapsed` | `true` when the categories rail shows icons only. Absent, or any other value, means expanded. |

The key is whitelisted in `allowed_keys` in `route_backend_users.py` and declared in
`WRITABLE_USER_SETTING_KEYS` in `userSettings.ts`. The route drops an unlisted key without
reporting it, so both are required. Writes go through `useUserSettingsStore.update`, which
debounces them and rolls the value back if the save fails.

The key is deliberately separate from `v2WorkspaceRailCollapsed`, the workspace section
rail, and `v2RailCollapsed`, the application shell's rail. Making room on the admin page
should not rearrange the workspace pages or the shell.

### File structure

| File | Change |
| --- | --- |
| `application/v2_ui/src/pages/AdminSettingsPage.tsx` | Collapse control, collapsed rail and entries. |
| `application/v2_ui/src/lib/userSettings.ts` | `v2AdminRailCollapsed` type and writable key. |
| `application/single_app/route_backend_users.py` | `v2AdminRailCollapsed` added to `allowed_keys`. |
| `ui_tests/fixtures/v2_admin_settings.py` | `open(preferences=...)` seeds saved user preferences. |

## Usage

Open **Admin Settings** in V2 and select **Collapse** at the top of the category list.
Select the expand icon in the same place to bring the labels back. Hover an icon to see
its category name. See the
[administration guide](../../admin/index.md#collapsing-the-category-list).

## Testing and validation

- `functional_tests/test_v2_admin_settings_rail_collapse.py` pins the contracts: the page
  reads and writes `v2AdminRailCollapsed`, and neither other rail key, before its
  non-admin return; the control's accessibility attributes; screen-reader labels and
  tooltips on collapsed entries; the control staying usable while categories are locked;
  and the key being in both the route whitelist and the client's writable keys.
- `ui_tests/test_v2_admin_settings_rail_collapse.py` drives the built SPA with intercepted
  APIs: the rail goes from 224px to 64px and the cards gain the width, the save carries
  only the admin rail key, the choice survives a reload and can be undone, collapsed icons
  still switch categories, the control works from the keyboard and keeps focus, the
  collapsed rail fits at 200% text, and the select replaces the rail on narrow screens, in
  light and dark.
- `functional_tests/test_v2_settings_and_workspace_tags.py` keeps checking that every key
  the client writes is whitelisted.

### Known limitations

- Until the user's preferences load, the rail draws expanded, the same as the workspace
  rail.
- The classic Admin Settings page is unchanged.

Related: [V2 Admin Settings Layout and Hierarchy](V2_ADMIN_SETTINGS_LAYOUT_AND_HIERARCHY.md),
and [V2 Documents Explorer](V2_DOCUMENTS_EXPLORER.md), which introduced the collapsible
workspace rail.
