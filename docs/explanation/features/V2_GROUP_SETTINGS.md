# V2 Group Settings, Activity and Statistics

## Overview

Group owners and admins can now manage a group's profile, logo, download policy
and retention in V2, read its recent activity, and chart and export its
statistics, without leaving for the classic manage page. The three views sit
with **Members** in the **Manage** part of the group workspace navigation.
Deleting a group is still done on the classic page, which V2 hands off to from
a danger zone in Settings.

Implemented in version **0.261.165**.

Dependencies:
- the native group settings, activity and statistics routes from version
  0.261.154 ([Group Settings APIs](GROUP_SETTINGS_APIS.md));
- the shared V2 group workspace shell and its **Manage** section group
  ([V2 Group Members](V2_GROUP_MEMBERS.md));
- the personal statistics charts and export dialog, which Statistics reuses.

## Who sees what

The server decides, and V2 follows it. The selected-group context lists
Settings, Activity and Statistics as sections of the **Manage** group.

- **Settings, Activity and Statistics** are open to the group's Owner and Admins
  while the group can be viewed. Other members see them as locked, with the
  reason "Only the group owner or an admin can do this."
- In an **inactive** group, or one whose status isn't recognized, all three are
  locked with the status's own explanation.
- Which controls work comes from the server's `settings_management` hint, never
  from a guess in the browser. The hint in the context is replaced by the
  fresher one each settings read and save returns, so a control locks as soon
  as the server stops allowing it.
  - The name, description, colour and logo belong to the owner. When group
    creation is restricted to the CreateGroups role, the profile also needs
    that role.
  - Downloads and retention are for the Owner and Admins, and appear only when
    an administrator has turned on group downloads or group retention.
  - A locked control says why.

The header's **Manage group (classic)** button now appears only for an inactive
group or one whose status isn't recognized, since everything else it offered is
native.

## Settings

- **Profile:** the name (at most 80 characters), the description (at most 500)
  and the colour, with a live preview of the group header. Only changed fields
  are sent.
- **Logo:** upload a PNG or JPEG image, or remove the logo. The server checks
  the image itself. An upload that isn't a readable image shows the server's
  message, and the chosen file stays selected so the owner can retry.
- **File downloads:** the group's own switch, **Turn off file downloads for this
  group**. Members can still use the documents in chat.
- **Retention:** conversation and document retention offer the classic choices:
  **Using organization default**, **No automatic deletion**, and the day
  options within the limits the server reports. A stored value outside today's
  limits stays selectable, even after you pick another option, so opening the
  editor never changes it, and only the period you change is sent.
- **Delete this group:** shown only to the owner. It shows how many documents
  the group holds, explains that they have to be removed first, and **Delete
  group (classic)** opens the classic page after a confirmation, once the group
  is confirmed as the active one.

### Unsaved edits and conflicts

- Profile and retention edits count as unsaved. Leaving the section or
  switching groups asks first, and refocusing the browser tab never discards
  them. While an edit is unsaved, the downloads switch waits, so a stray
  toggle can't throw the edit away.
- **Discard changes** puts the profile or retention editor back to the saved
  settings.
- If the group is locked, or you lose the role, while an edit is open, the
  edit can no longer be saved. It stops holding you on the page and stops
  holding the downloads switch, and **Discard changes** stays available to
  clear it.
- If the settings changed since they were opened, the section reloads and keeps
  your edits on top of the new values, and says which fields changed under you.
- If the group kept changing while a save was being written, the edits are kept
  and the same save can be retried.
- A refused or failed save keeps the edits and shows the server's message:
  a validation error, a server error or a network failure. Only a refusal that
  means your access changed, or that the group is gone, re-reads the workspace.
- A saved profile or logo updates the header and the group picker straight
  away. A saved download policy refreshes the workspace too, so document
  downloads follow it at once.

## Activity

The group's recent events, most recent first, as the server's projection
writes them: a short summary, who did it, and when.

- **Who:** a current member's display name, **Former member**, or **System**
  for work with no person behind it.
- **When:** the viewer's local date and time, with the relative time beside it.
- Show the last **10**, **20** or **50** events. The choice is kept in the page
  address.
- There's an empty state for a group with no recent activity. If the feed can't
  be read, the section says so and offers a retry, rather than showing an empty
  feed.

Membership changes aren't in this feed, as in classic, and the empty state
doesn't suggest they are.

## Statistics

- **Windows:** the last **7**, **30** or **90** days, or a custom range of at
  most 366 days between 2000-01-01 and 9998-12-31. A range the server would
  refuse is caught with the server's own message before the request.
- **What's shown:** the group's totals, and charts of document activity, token
  usage and storage, drawn with the same charts as personal statistics.
- **Export** uses the personal statistics export dialog. It writes the classic
  group CSV column for column, as `group_stats_export_<date>.csv`.
- If the statistics can't be read, the section says so and offers a retry,
  rather than drawing empty charts.

## How it's built

| Piece | File |
| --- | --- |
| Section availability, in the selected-group context | `application/single_app/functions_workspace_context.py` |
| The scoped settings, activity and statistics client | `application/v2_ui/src/lib/groupSettings.ts` |
| The group statistics adapter and CSV | `application/v2_ui/src/lib/groupStats.ts` |
| The three sections | `application/v2_ui/src/pages/workspace/GroupSettingsSection.tsx`, `GroupActivitySection.tsx`, `GroupStatisticsSection.tsx` |
| Wiring into the group workspace | `application/v2_ui/src/pages/GroupWorkspacePage.tsx`, `pages/workspace/groupManageSections.ts`, `lib/workspaceContext.ts` |
| The personal statistics seam | `components/settings/StatsExportDialog.tsx` and `lib/userStats.ts`. With no group adapter passed, the personal path is unchanged. |

The client is created once per group, so a routine revalidation of the
workspace, such as refocusing the tab, doesn't rebuild it or reload the
section.

## Testing and validation

- **Browser, `ui_tests/test_v2_group_settings.py`:** the three views for every
  role and status, and every control and its refusal. It also covers the
  refocus, validation, server-error and network-failure cases that keep drafts;
  a lock after load re-gating the controls, freeing the page and offering
  Discard; a download policy save refreshing the workspace; a status change
  keeping an earlier settings save; the retention choices; and a bad logo
  image.
- **The journeys (`test_v2_group_journeys.py`):**
  - J4 checks the classic button for active, inactive and unknown-status
    groups;
  - J8 opens classic from the danger zone, confirming the active group first;
  - J9's unsaved-editor sweep includes the Settings editor.
- **Fixture parity:**
  - `functional_tests/test_group_settings_fixture_parity.py` holds the browser
    fixture to the real routes, including the refusal texts, the conflict text
    and the statistics window's bounds and messages;
  - `test_group_settings_refusal_text_parity.py` holds the browser's refusal
    texts to the server's;
  - `test_group_context_fixture_parity.py` and
    `test_group_settings_context_seam.py` hold the three sections to the policy
    the routes enforce.
- **Statistics export:**
  - `functional_tests/test_v2_stats_export_contracts.py` pins the unchanged
    personal export and the group CSV format;
  - `test_v2_group_stats_formatter_parity.mjs` runs the V2 and classic byte
    formatters side by side, so the "Formatted" storage column matches the
    classic export.

## Known limitations

- Deleting a group is still done on the classic page. V2 shows the prerequisite
  and hands off to classic.
- An administrator's own tools for managing any group are unchanged and remain
  in Control Center.

## Related

- [Group Settings APIs](GROUP_SETTINGS_APIS.md)
- [V2 Group Members](V2_GROUP_MEMBERS.md)
- [V2 Group Workspace Journeys](V2_GROUP_WORKSPACE_JOURNEYS.md)
- [Classic Group Stats Export Fix](../fixes/CLASSIC_GROUP_STATS_EXPORT_FIX.md)
