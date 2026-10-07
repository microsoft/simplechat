# V2 User Settings Redesign

**Implemented in version: 0.261.277** (layout); **0.261.278** (voice, audio and retention);
**0.261.279** (fact memory and Microsoft 365)

## Overview

V2 User Settings now uses the same design language as V2 Admin Settings, so personal
settings are laid out like the admin ones: a collapsible section rail, full-width settings
cards, and an **On this page** index. It is being brought to parity with the classic
Profile page in stages:

1. Layout (0.261.277).
2. Completion sounds, spoken replies (voice, speed and auto-play), microphone permission,
   and personal retention (0.261.278).
3. Fact memory workbench and Microsoft 365 sharing and workflows (0.261.279).
4. Later: tutorials and Latest Features.

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
| Preferences | Grouped: Appearance (Text size, Conversation list), Chat (Conversation navigation), Voice and audio (Completion sounds, Spoken replies, Microphone), Notifications and alerts (Desktop notifications, Workflow alerts on this device), Memory and data (Fact memory, Retention), Connected accounts (Microsoft 365 sharing, Chat connection, Workflow connection, Workflow authorizations), Diagrams and charts (Diagrams, Charts) |
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
- Related fixes: [Feedback My Routes Filter Unpack Fix](../fixes/FEEDBACK_MY_FILTER_UNPACK_FIX.md)
  and [Personal Retention Default Value Fix](../fixes/PERSONAL_RETENTION_DEFAULT_VALUE_FIX.md).

### Known limitations

The index appears only when a tab has more than one card, so the Groups and Public
workspaces tabs do not show it.

The Microsoft 365 workflow sign-in returns to the classic Profile page
(`/profile?m365_connection=connected`), because the callback route redirects there.
