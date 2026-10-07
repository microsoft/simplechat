# V2 User Settings Redesign

**Implemented in version: 0.261.277**

## Overview

V2 User Settings now uses the same design language as V2 Admin Settings, so personal
settings are laid out like the admin ones: a collapsible section rail, full-width settings
cards, and an **On this page** index. This is the first stage of bringing V2 User
Settings to parity with the classic Profile page. Later stages add the classic preferences
that V2 does not yet honour: completion audio, voice playback, microphone permission,
retention, fact memory, Microsoft 365 sharing, tutorials, and Latest Features.

Dependencies: the V2 React interface (`application/v2_ui`) and the user settings API
(`/api/user/settings`).

## Technical specifications

### Layout

- `pages/SettingsPage.tsx` renders the shell:
  - The section rail collapses to labelled icons. The choice is saved as the per-user
    setting `v2UserSettingsRailCollapsed`, independent of the admin rail's
    `v2AdminRailCollapsed`.
  - Below the `lg` breakpoint, a select replaces the rail.
  - The content column fills the available width (up to `112rem`). At container widths of
    `76rem` and above, a `15rem` index column sits beside it.
- `components/settings/SettingsCard.tsx` provides:
  - `SettingsCard`, a card with the admin card styling (`admin-settings-distinct`,
    `admin-section-body`), an icon, a description, an optional status chip, and header
    actions.
  - `SettingsGroup`, a labelled group of cards.
  - `SettingsSectionRegistryContext`. Each card registers with it so the page can build
    its index without a hand-maintained list. Entries are ordered by DOM position.
- The page reuses the admin `SettingsIndex` component. Selecting an entry scrolls to the
  card, respecting reduced motion, and moves focus to the card title.

### Tabs

| Tab | Cards |
| --- | --- |
| Preferences | Grouped: Appearance (Text size, Conversation list), Chat (Conversation navigation, Spoken replies), Notifications and alerts (Desktop notifications, Workflow alerts on this device), Diagrams and charts (Diagrams, Charts) |
| Stats | Lifetime totals, four activity charts, Storage used, Account |
| Groups / Public workspaces | Your groups / Your public workspaces |
| Feedback | Summary, Your feedback (with Export CSV) |
| Violations | Summary, Your violations |

Cards for capabilities that are turned off are not shown.

### Violations visibility

The Violations tab is always listed, as on the classic Profile page. When neither
`enable_content_safety` nor `enable_content_screening` is on, the tab shows a single
explanatory card and makes no API calls.

### Configuration

| Setting | Scope | Purpose |
| --- | --- | --- |
| `v2UserSettingsRailCollapsed` | Per user | Remembers whether the User Settings rail is collapsed |

The key is allowed in `route_backend_users.py` and in `WRITABLE_USER_SETTING_KEYS` in
`lib/userSettings.ts`.

## Usage

Open **User Settings** from the account menu. Use the button at the top of the rail to
collapse or expand it, and the **On this page** index to move between cards.

## Testing and validation

- `functional_tests/test_v2_user_settings_layout.py`: rail persistence, index registry,
  card usage on every tab, preference groups, and Violations visibility.
- `functional_tests/test_v2_settings_and_workspace_tags.py`: tab gating, updated for the
  always-listed Violations tab.
- Related fix: [Feedback My Routes Filter Unpack Fix](../fixes/FEEDBACK_MY_FILTER_UNPACK_FIX.md).

### Known limitations

The index appears only when a tab has more than one card, so the Groups and Public
workspaces tabs do not show it.
