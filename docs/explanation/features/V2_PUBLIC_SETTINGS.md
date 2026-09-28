# V2 Public Settings, Activity and Statistics

## Overview

From version **0.261.185**, a public workspace's Owner and Admins manage its
profile, logo, file downloads and retention in V2, read its recent activity,
and chart and export its statistics, in the **Settings**, **Activity** and
**Statistics** sections beside **Members** under **Manage**. Deleting the
workspace is still done on the classic page, which a danger zone in Settings
hands off to.

These are the group sections, shared through one set of components with a
public scope; see [V2 Group Settings](V2_GROUP_SETTINGS.md). The routes are in
[Public Settings APIs](PUBLIC_SETTINGS_APIS.md).

## Who sees what

The server decides, and V2 follows its `settings_management` hint:

- **Settings** and **Activity** are open to the Owner and Admins, and
  **Statistics** also to DocumentManagers, while the workspace can be viewed.
  Anyone else sees them locked, with the reason.
- Only the Owner changes the name, description, color and logo, and only in an
  active or upload-disabled workspace.
- The Owner and Admins change file downloads, when the administrator allows
  downloads for the workspace, and retention, when public retention policies are
  on. Each appears only when it applies.
- A locked control says why.

## Settings

The editor is the group's: only changed profile fields are sent, a logo upload
that isn't a readable image keeps the file selected for a retry, retention
offers the classic choices within the server's limits, and a save that loses to
someone else's change reloads that section and keeps your edit over it. A
successful save refreshes the workspace context.

**Delete this workspace** is shown only to the Owner. It says how many current
documents the workspace holds, counted as the V2 document list counts them. It
explains that deleting removes only the workspace record, leaving its
documents, prompts, identities and file sources behind, and that the classic
page counts every stored version and won't start while it finds any. Continuing
makes the workspace active and opens the classic page, after the unsaved-changes
prompt if an edit is open.

## Activity

The workspace's recent activity, 10, 20 or 50 at a time, with display names
only. A person with no stored role in the workspace, usually a reader, is shown
as not a member. A failed read shows an error with a retry rather than an empty
feed.

## Statistics

The personal statistics charts, over the workspace's documents, storage,
activity and tokens, for the classic windows or a custom range of up to 366
days. **Export** writes the classic public statistics CSV: the configured
workspace label as the title, the classic sections and columns, and the
classic file name.

## Known limitations

- A profile that's read-only because the workspace's status isn't recognized
  was explained with the "locked or inactive" sentence until version
  0.261.188; it now shows the server's own sentence.
- Deleting a workspace happens on the classic page and removes only the
  workspace record (decision 10).

## Testing and validation

- `ui_tests/test_v2_public_settings.py` (49): who sees what, the profile, logo,
  downloads and retention editors, conflicts, activity, statistics and the
  export, and the danger zone, on desktop and mobile.
- The group suites `ui_tests/test_v2_group_settings.py`,
  `test_v2_group_journeys.py`, `test_v2_group_members.py` and
  `test_v2_group_workspace_shell.py` pass unchanged; the group sections are
  wrappers over the same components.
- `functional_tests/test_v2_public_stats_formatter_parity.mjs` and
  `test_classic_public_stats_export_fix.py`: the CSV's byte formatting against
  classic.
- `functional_tests/test_public_context_fixture_parity.py`: the three sections
  and `settings_management` for every role and status, with the download and
  retention switches.

## Related

- [Public Settings APIs](PUBLIC_SETTINGS_APIS.md)
- [V2 Group Settings](V2_GROUP_SETTINGS.md)
- [V2 Public Members](V2_PUBLIC_MEMBERS.md)
