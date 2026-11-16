# V2 Sidebar Navigation And Account Menu Fix

Fixed in version: **0.261.055**

## Issues

Four related problems in the V2 navigation rail.

### 1. Navigation groups did not collapse, and never remembered

Custom Pages and External Links only became a collapsible menu in V2 when the group held
three or more entries, or when an administrator ticked **Force Menu Display** — the rule
reproduced from the classic rail. A deployment with one or two links got a static heading
with no way to put the group away.

Where the menu *did* appear, its state was component state initialised to open
(`useState(true)` in `NavExtras.tsx`). Collapsing a group lasted until the next page load.
The classic interface has always persisted this per user, so the same deployment behaved
differently depending on which interface you were in.

### 2. Admin Settings sat in the primary navigation

`/admin` was a `NAV_ITEMS` entry with an `adminOnly` flag, so an administrator's rail listed
it beside Chats, Agents and the workspaces — mixing the places you work with the place you
administer. The classic interface does not do this: *App Settings* lives under an **Admin**
heading inside the account dropdown.

### 3. The account menu was unreachable when the rail was collapsed

The popover was rendered behind `{open && !collapsed && ...}`. In the 68px icon strip,
clicking the avatar toggled `open` and painted nothing at all. Personal settings, **Back to
classic UI** and **Sign out** were all unreachable without expanding the rail first, and the
button gave no indication that was necessary. The menu also had no outside-click or Escape
handler, unlike every other menu in the interface.

### 4. The stored profile photo was never shown

`get_user_profile_image()` fetches the Microsoft Graph photo and `get_user_settings()`
caches it on the user's settings document as a data URI at `settings.profileImage`. The
classic rail renders it. V2 loads the same document at startup for its preferences and drew
initials regardless.

## Root cause

The first three are all the same underlying mistake: the V2 rail was built to mirror the
classic rail's *markup decisions* rather than its behaviour, and then diverged where the two
layouts differ.

- The three-item menu threshold was copied across without the persistence that makes it
  useful, so V2 inherited the rule and not the capability.
- Admin Settings was placed by category ("it is a page, pages go in the nav list") rather
  than by what it is, and the classic account dropdown's Admin section was not carried over.
- The account popover's positioning was written for the expanded rail only. Rather than
  giving the collapsed rail its own placement, the render was suppressed — which removed the
  symptom of a mispositioned panel by removing the panel.

The fourth is simply that the field was never read: nothing in V2 referenced `profileImage`.

## Changes

### Navigation groups collapse at any count, and are remembered

`NavExtras.tsx` now renders every group's heading as a disclosure button. The entry-count
threshold is gone, along with `shouldRenderAsMenu` and `INLINE_ITEM_LIMIT` in
`lib/navigationGroups.ts`, which had no remaining caller.

The expanded state is stored in the **shared** `sidebarMenuState` user setting under the
classic key names `externalLinks` and `customPages`, so a group collapsed in either
interface is collapsed in the other. A group nobody has touched is open, matching
`sidebar_menu_state.get(key, true)` in the classic templates.

**Force Menu Display no longer changes the V2 rail.** Every group is already a menu there.
It continues to work in the classic interface.

Sharing the setting has one hazard that the new `lib/sidebarMenuState.ts` exists to contain.
`update_user_settings()` merges only the top level of the settings document
(`doc['settings'].update(...)`), so a payload carrying a single key inside `sidebarMenuState`
**replaces the whole object**. Writing `{ externalLinks: false }` on its own would silently
reset the classic interface's `workspaces`, `support`, `conversations`, `adminSettings` and
`controlCenter` menus for that user. `withSidebarMenuExpanded()` therefore always produces
the complete state, exactly as `static/js/sidebar.js` does.

The module also normalises the legacy `"true"` / `"false"` string forms the setting has held,
and drops keys outside the classic whitelist — necessary because the classic normaliser drops
them on its next write, so a key invented here would not survive.

A toggle made before the preferences request resolves takes effect locally but is not
written, since merging into an object that has not arrived would produce exactly the
data-loss case above.

### Admin Settings moved into the account menu

`/admin` is removed from `NAV_ITEMS`; the `adminOnly` flag is removed with it, since nothing
else used it. The account menu gains an **Admin Settings** entry rendered behind the
`is_admin` check. `AdminSettingsPage` already refuses a non-administrator with its own
panel, so the route is unchanged and remains safe for a typed URL.

*Settings* is relabelled **User Settings**, and the page title follows, because "Settings"
one line above "Admin Settings" does not say which one you are choosing.

### The account menu opens in both rail states

The `!collapsed` gate is removed. Collapsed, the menu is positioned `left-full` — beside the
strip rather than above the avatar, where a 68px-wide panel has nowhere to go — and repeats
the account name and administrator label the strip cannot show. The rail sets no `overflow`,
so this escapes the strip without a portal.

Outside-click and Escape dismissal are added, following the pattern in
`components/ui/Dropdown.tsx`. The trigger gains `aria-haspopup="menu"` and an
`aria-label` for the collapsed state, where it has no visible text.

### The profile photo is shown

New `components/layout/UserAvatar.tsx` reads `settings.profileImage` from the preferences
store, falling back to initials when there is no photo **and** when a cached one fails to
decode — the data URI is never re-validated, so a broken copy would otherwise leave an empty
circle with nothing to indicate a picture was intended.

It is used by the rail's account control and by the User Settings page header, which gains a
`leading` slot on `PageHeader`.

The photo is deliberately not added to `/api/v2/bootstrap`. That payload is refetched
whenever an administrator changes a setting, and a base64 photograph would be resent every
time to say something that has not changed. The preferences document that already holds it
is fetched once at startup.

## Files modified

| File | Change |
|---|---|
| `application/v2_ui/src/lib/sidebarMenuState.ts` | New. Pure helpers for the shared menu-state setting: the classic key whitelist, normalisation, the default-open read and the whole-object write. |
| `application/v2_ui/src/lib/navigationGroups.ts` | `shouldRenderAsMenu` and `INLINE_ITEM_LIMIT` removed. |
| `application/v2_ui/src/lib/userSettings.ts` | `sidebarMenuState` added to the interface and to `WRITABLE_USER_SETTING_KEYS`; `profileImage` declared as read-only. |
| `application/v2_ui/src/components/layout/NavExtras.tsx` | Heading is always a disclosure control; state read from and written to `sidebarMenuState`. |
| `application/v2_ui/src/components/layout/UserAvatar.tsx` | New. Shared avatar with an initials fallback. |
| `application/v2_ui/src/components/layout/Sidebar.tsx` | `/admin` removed from `NAV_ITEMS`; account menu reworked for the collapsed rail, given dismissal handling, User Settings and Admin Settings entries and the avatar. |
| `application/v2_ui/src/components/layout/PageHeader.tsx` | Optional `leading` slot. |
| `application/v2_ui/src/pages/SettingsPage.tsx` | Avatar in the header; title is "User Settings". |
| `application/single_app/config.py` | `VERSION` `0.261.054` → `0.261.055`. |

No server code changed. `sidebarMenuState` was already in the route's `allowed_keys`, since
the classic interface writes it.

## Testing

| Test | Covers |
|---|---|
| `functional_tests/test_v2_sidebar_menu_state_logic.mjs` | Executes the shared helpers: the whitelist matching `static/js/sidebar.js`, boolean and legacy string forms, unknown keys and unusable values dropped, an untouched group defaulting to open, the stored object not mutated, and a write carrying the classic interface's other menus through untouched. 16 checks. |
| `functional_tests/test_v2_sidebar_account_menu.py` | Admin Settings absent from `NAV_ITEMS` and present in the account menu behind the `is_admin` check, the menu not gated on `!collapsed` and dismissing on Escape and an outside click, the groups collapsing with no threshold and persisting through the shared helpers, `sidebarMenuState` writable in both the client key list and the route whitelist with key names matching the classic interface, and the photo reaching both the rail and the settings header. 8 tests. |
| `functional_tests/test_v2_navigation_groups_logic.mjs` | Updated: the three menu-threshold checks describe removed behaviour and are gone. 10 checks. |
| `ui_tests/test_v2_appearance_branding_and_nav.py` | Updated: the group toggle is asserted unconditionally rather than only above the old three-item threshold. |

Regression runs: `test_v2_stats_parity.py` (7/7), `test_v2_settings_and_workspace_tags.py`
(9/9), `test_v2_settings_tabs.py` (6/6), `test_v2_documents_explorer.py` (20/20),
`test_v2_reasoning_effort_persistence.py` (7/7). `npm run build` in `application/v2_ui`
typechecks and compiles cleanly.

## Before and after

| Situation | Before | After |
|---|---|---|
| External Links with two entries | Static heading, cannot be collapsed | Collapsible heading |
| Collapsing a group, then reloading | Reopens | Stays collapsed |
| Collapsing a group in V2, then opening the classic UI | Unrelated states | Collapsed in both |
| Administrator's primary navigation | Includes Admin Settings | Places you work only |
| Account menu, rail expanded | Settings, Back to classic UI, Sign out | User Settings, Admin Settings, Back to classic UI, Sign out |
| Clicking the avatar in the collapsed rail | Nothing appears | The menu opens beside the rail |
| Dismissing the account menu | Only by clicking the avatar again | Escape, outside click, or the avatar |
| Account control and settings header | Initials | Profile photo, initials when there is none |
