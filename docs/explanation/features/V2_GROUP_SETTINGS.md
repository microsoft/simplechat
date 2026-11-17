# V2 Group Settings, Activity and Statistics

## Overview

Group owners and admins can now manage a group's profile, logo, download policy
and retention in V2, read its recent activity, and chart and export its
statistics, without leaving for the classic manage page. The three views sit
with **Members** in the **Manage** part of the group workspace navigation.
From version **0.261.445** the owner also deletes an empty group from a danger
zone in Settings, natively, and an inactive, locked or unrecognized-status
group's owner and admins keep all four Manage sections, so V2 no longer hands
off to classic from the group workspace.

Implemented in version **0.261.165**. The native delete and the managers'
access to inactive groups: **0.261.445**.

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
  in every group status. Other members see them as locked, with the reason
  "Only the group owner or an admin can do this." (or the status's own
  explanation when the group can't be viewed).
- In a **locked**, **inactive** or **unrecognized-status** group the owner and
  admins still get all three, as on the classic manage page, but the profile
  and logo are read-only with the status explained: "This group is locked or
  inactive, so its name, description, color and logo can't be changed.", or the
  server's own sentence for a status it doesn't recognize. Downloads, retention
  and the owner's danger zone follow their own rules and are not tied to the
  status.
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

The header no longer has a **Manage group (classic)** button for any status:
there is nothing left that it opened. Before version 0.261.445 it appeared for
an inactive group or one whose status wasn't recognized, because those groups
had no native Manage sections.

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
  the group holds, says what a delete does and doesn't remove, and holds the
  **Delete group** button until the group is empty. See *Deleting a group*
  below.

### Deleting a group

The danger zone deletes the group in V2, with the same
`DELETE /api/groups/<group_id>` route the classic manage page calls. The route
removes the group's own record at once and creates no approval request.

1. **Count.** The section reads how many documents the group holds when it
   opens, and again when you press **Delete group**, as classic does. If the
   group still holds documents nothing opens: the zone says the group "wasn't
   deleted because it still holds documents" and to remove them first. If the
   count can't be read, the group isn't deleted either, and the zone says so.
2. **Confirm.** For an empty group a confirmation names the group, says every
   member loses access right away and that this can't be undone, and says the
   group's conversations, prompts, agents, actions and other saved items are
   left behind, not deleted with it.
3. **Count again, then send.** Confirming reads the count once more, because a
   document can arrive while the confirmation is open and the server doesn't
   check, and then sends the delete once. While it is in flight the
   confirmation can't be dismissed or confirmed a second time.
4. **Leave.** On success V2 reads your groups again, so the picker and your saved
   active group drop the deleted one, shows "<name> was deleted.", and returns
   to the group list. If another group is your active group, that group opens.
5. **If it's refused,** the dialog stays open and shows why, so the same dialog
   can try again:
   - a 403 shows the server's words: "Only the owner can delete the group", or
     "Insufficient permissions (CreateGroups role required)" where the
     deployment restricts group creation to that role, since the same role gate
     protects this route;
   - a 404 means the group is already gone: V2 says so and leaves as it does
     after a delete;
   - any other 4xx shows the server's message;
   - a 5xx or a dropped connection shows "The group couldn't be deleted. Try
     again.", never a raw server error.

Unsaved profile or retention edits hold the **Delete group** button, with a hint,
instead of being thrown away. Only the group's own record is removed; an
administrator's separate group deletion in Control Center is unchanged.

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
| The three sections | `application/v2_ui/src/pages/workspace/GroupSettingsSection.tsx`, `GroupActivitySection.tsx`, `GroupStatisticsSection.tsx`. From version 0.261.185 these are thin wrappers over the shared `WorkspaceSettingsSection.tsx`, `WorkspaceActivitySection.tsx` and `WorkspaceStatisticsSection.tsx`, which public workspaces also use; the group's props, text and behaviour are unchanged |
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
  - J4 checks that an inactive and an unrecognized-status group bar the content
    sections but keep the managers' Manage sections, with no classic button;
  - J8 deletes the group natively while the active group changed elsewhere,
    without visiting classic or re-activating the deleted group;
  - J10 reads the Manage sections for every role and status from the context;
  - J9's unsaved-editor sweep includes the Settings editor.
- **The native delete (`test_v2_group_settings.py`):** the count gate (including
  a document that arrives while the confirmation is open), the confirmation,
  every refusal and its retry, a dropped connection, a group already deleted
  elsewhere, a second click while the delete is in flight, unsaved edits holding
  the button, and the confirmation at both breakpoints in both themes.
  `test_v2_group_classic_handoffs.py` pins that no role or status shows a
  classic button, and that the danger zone never opens classic.
- **Fixture parity:**
  - `functional_tests/test_v2_workspace_delete_fixture_parity.py` runs the real
    delete route bodies, behind the real CreateGroups decorator, beside the
    browser fixture's answers, and pins that the route checks no status and no
    documents and creates no approval request;
  - `functional_tests/test_group_settings_fixture_parity.py` holds the browser
    fixture to the real routes, including the refusal texts, the conflict text
    and the statistics window's bounds and messages;
  - `test_group_settings_refusal_text_parity.py` holds the browser's refusal
    texts to the server's;
  - `test_group_context_fixture_parity.py`,
    `test_v2_group_workspace_context.py` and
    `test_group_settings_context_seam.py` hold the Manage sections, including
    the owner's and admins' access in every status, to the policy the routes
    enforce.
- **Statistics export:**
  - `functional_tests/test_v2_stats_export_contracts.py` pins the unchanged
    personal export and the group CSV format;
  - `test_v2_group_stats_formatter_parity.mjs` runs the V2 and classic byte
    formatters side by side, so the "Formatted" storage column matches the
    classic export.

## Known limitations

- The delete route removes only the group's own record and checks neither the
  group's status nor its documents; the document gate is the page's, as it is
  on the classic page. A script that calls the route directly can delete a
  group that still holds documents, as before.
- The count the gate reads is the group's current documents, the same figure as
  the Documents section and as classic's own check.
- An administrator's own tools for managing any group are unchanged and remain
  in Control Center.

## Related

- [Group Settings APIs](GROUP_SETTINGS_APIS.md)
- [V2 Group Members](V2_GROUP_MEMBERS.md)
- [V2 Group Workspace Journeys](V2_GROUP_WORKSPACE_JOURNEYS.md)
- [Classic Group Stats Export Fix](../fixes/CLASSIC_GROUP_STATS_EXPORT_FIX.md)
