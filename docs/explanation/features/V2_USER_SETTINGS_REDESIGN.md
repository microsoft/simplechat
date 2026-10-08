# V2 User Settings Redesign

**Implemented in version: 0.261.277** (layout); **0.261.278** (voice, audio and retention);
**0.261.279** (fact memory and Microsoft 365); **0.261.280** (guided tours and Latest Features)

## Overview

V2 User Settings now uses the same design language as V2 Admin Settings, so personal
settings are laid out like the admin ones: a collapsible section rail, full-width settings
cards, and an **On this page** index. It is being brought to parity with the classic
Profile page in stages:

1. Layout (0.261.277).
2. Completion sounds, spoken replies (voice, speed and auto-play), microphone permission,
   and personal retention (0.261.278).
3. Fact memory workbench and Microsoft 365 sharing and workflows (0.261.279).
4. Guided tours and the Latest Features shortcut (0.261.280).

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
| Preferences | Grouped: Appearance (Text size, Conversation list), Chat (Conversation navigation), Voice and audio (Completion sounds, Spoken replies, Microphone), Notifications and alerts (Desktop notifications, Workflow alerts on this device), Help and guidance (Latest Features, Guided tours), Memory and data (Fact memory, Retention), Connected accounts (Microsoft 365 sharing, Chat connection, Workflow connection, Workflow authorizations), Diagrams and charts (Diagrams, Charts) |
| Stats | Lifetime totals, four activity charts, Storage used, Account |
| Groups / Public workspaces | Your groups / Your public workspaces |
| Feedback | Summary, Your feedback (with Export CSV) |
| Violations | Summary, Your violations |

Cards for capabilities that are turned off are not shown.

### Voice, audio and retention

Each card appears only when its capability is on.

| Card | Capability | Settings | Behaviour |
| --- | --- | --- | --- |
| Completion sounds | `enable_chat_completion_audio_cues` | `chatCompletionAudioEnabled`, `chatCompletionAudioMuted`, `chatCompletionAudioSound`, `chatCompletionAudioVolume` | Plays the chosen cue from `static/audio/completion-cues/` when a reply finishes and you are not watching that conversation: another conversation, another page, or the window is unfocused. The cue is skipped for blocked replies and while another cue is playing. **Preview** plays the sound at the chosen volume. |
| Spoken replies | `enable_text_to_speech` | `ttsVoice`, `ttsSpeed`, `ttsAutoplay`, `ttsEnabled` | Voices come from `GET /api/chat/tts/voices`, grouped by language. A saved voice the deployment no longer lists stays selectable. Speed (0.5–2.0) is sent with every speech request. With auto-play on, a finished reply in the open conversation is read aloud. A single reader (`lib/speechPlayback.ts`) serves message playback, the sample, and auto-play, so starting one stops the other. |
| Microphone | `enable_speech_to_text_input` | None (browser permission) | Shows this browser's microphone permission from the Permissions API without prompting, and follows changes. **Allow microphone** asks for it once. Revoking it is done in the browser's site settings. |
| Retention | `enable_retention_policy_personal` | `retention_policy` (written by the route) | Organization default (with its label from `/api/retention-policy/defaults/personal`), no automatic deletion, or 1 to 730 days, for conversations and documents separately. Saved with an explicit **Save** through `POST /api/retention-policy/user`, because a shorter period deletes older items at the next run. |

Differences from the classic page:

- Completion sounds listen for replies finished in this browser tab. The classic page also
  polls `/api/notifications/chat-completions` for replies finished in other tabs.
- Auto-play reads a reply once it has finished. The classic page turns streaming off while
  auto-play is on; V2 keeps streaming.

### Fact memory

`components/settings/FactMemoryBench.tsx` replaces the classic Fact Memory card and its
manager dialog with one workbench, using the same routes:

| Action | Route |
| --- | --- |
| List, with the admin state and counts | `GET /api/profile/fact-memory` |
| Add | `POST /api/profile/fact-memory` with `value` and `memory_type` |
| Edit wording or type | `PUT /api/profile/fact-memory/<id>` |
| Delete, after a confirmation dialog | `DELETE /api/profile/fact-memory/<id>` |

- A memory is an **instruction** (applied to every reply) or a **fact** (recalled when
  relevant).
- The list is searchable, filterable by type, and ordered by last change.
- The card is always shown, as on the classic page. The header badge reflects
  `enable_fact_memory_plugin`; while it is off, memories can be managed but are not used.

### Microsoft 365

`components/settings/M365Cards.tsx` mirrors the classic "Microsoft 365 sharing and
workflows" section (`static/js/profile/profile-m365.js`). Like the classic page it is not
gated by a capability flag.

| Card | Routes | Behaviour |
| --- | --- | --- |
| Microsoft 365 sharing | `GET`/`PATCH /api/m365/preferences`, `POST /api/m365/sources/<source>/revoke` | A sharing duration for Calendar, Email, OneDrive and SPO, and an extended-analysis choice for OneDrive and SPO. An unknown value from the server is refused rather than guessed. Saved with **Save**. Shows the browser timezone, which is not stored. |
| Chat connection | `GET /api/m365/chat/connection`, `POST /api/m365/chat/connection/connect` | Status and saved sources. Reconnect uses the existing `connectMicrosoft365` popup flow, then re-reads the status. |
| Workflow connection | `GET /api/m365/connections`, `POST /api/m365/connections/connect`, `POST /api/m365/connections/disconnect` | Account, tenant, cloud, sources and delegated permissions. Connect navigates to the sign-in URL only after `authorizationUrl()` validates it as HTTPS with no credentials. |
| Workflow authorizations | `GET /api/m365/bindings`, `POST /api/m365/bindings/<id>/revoke` | Paged list using the classic Approvals wording. Pending and approved entries can be revoked. Links to Approvals. |

- Every write sends `X-M365-CSRF-Token`. The token comes from the GET responses and is
  refreshed and retried once when the server returns `m365_csrf_invalid`, as the classic
  page does.
- Revocations and disconnect go through one confirmation dialog. It states that history
  already published to conversations is not removed. After a change, all four cards refresh.

### Guided tours and Latest Features

**Guided tours.** V2 has its own tour engine, which replaces the classic floating tutorial
launchers on the Chat and Personal Workspace pages.

- `lib/tours.ts` defines each tour: its page, and the steps that point at `data-tour`
  anchors. The shipped tours are `chat` and `workspace`.
- `components/tour/GuidedTour.tsx` draws the tour:
  - A spotlight over the current control, with a card beside it.
  - **Back**, **Next**, **Skip** and **Done** buttons. Esc ends the tour and the arrow
    keys move between steps.
  - Focus is trapped in the card, then returned when the tour ends. Reduced motion is
    respected.
  - Steps whose control is missing or hidden are skipped.
- `components/tour/TourLauncher.tsx` adds a help button to the Chat header and the
  Workspace page header.
- **Start now** in Preferences opens the tour's page and starts it. It does this through a
  one-time request in session storage (`simplechat.v2.pendingTour`).

Which tours are offered is decided by two settings:

- `showTutorialButtons` is the master switch, shared with the classic tutorial buttons. When
  it is false, every tour is off.
- `tutorialVisibility` holds a per-tour choice, `{ tourId: bool }`. A tour with no entry is
  shown. The route accepts only shipped tour ids (`TUTORIAL_IDS` in
  `route_backend_users.py`) with boolean values.

**Latest Features.** The bootstrap payload now has `navigation.latest_features`, built by
`_build_latest_features_nav` in `route_backend_v2.py`. It contains `available`,
`hidden_by_development`, `url` and `menu_name`.

The shortcut is available when all of these hold:

- The user has the Admin or User role.
- The support menu is on.
- `enable_support_latest_features` is on.
- At least one Latest Features item is visible.

As on the classic interface, the shortcut is hidden for everyone in development mode.
`components/layout/SupportMenu.tsx` draws it in the navigation rail's Support group with a
hide button, and the Preferences card shows its status with **Hide for this version** or
**Show again**. Since **0.261.294** the shortcut and the card's **Open Latest Features** link
open the V2 Latest Features page instead of the classic one; see
[V2 Support Menu](V2_SUPPORT_MENU.md).

Both surfaces write `latestFeaturesHiddenVersion`, shared with the classic page. A hide
applies only to the version it was saved for, so the shortcut comes back after an upgrade.
`lib/latestFeaturesNav.ts` holds the logic both surfaces use.

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
- `functional_tests/test_v2_user_settings_audio_voice_retention.py`: card gating, writable
  keys, the cue catalogue, speed reaching the speech call, the reply listeners, no
  microphone prompt on load, and the retention route accepting `'default'`.
- `functional_tests/test_v2_user_settings_memory_m365.py`: preference grouping, the fact
  memory routes and confirmed delete, CSRF validation on every M365 write the cards make,
  the CSRF retry, the classic choice labels, confirmed revocations, and validated sign-in
  redirects.
- `functional_tests/test_v2_user_settings_tutorials_latest_features.py`: tour ids
  accepted by the route, every tour step's anchor present, launchers and the Help and
  guidance group, the bootstrap navigation entry, and a Node run of the shared tour and
  Latest Features logic.
- Related fixes: [Feedback My Routes Filter Unpack Fix](../fixes/FEEDBACK_MY_FILTER_UNPACK_FIX.md)
  and [Personal Retention Default Value Fix](../fixes/PERSONAL_RETENTION_DEFAULT_VALUE_FIX.md).

### Known limitations

The index appears only when a tab has more than one card, so the Groups and Public
workspaces tabs do not show it.

The Microsoft 365 workflow sign-in returns to the classic Profile page
(`/profile?m365_connection=connected`), because the callback route redirects there.
