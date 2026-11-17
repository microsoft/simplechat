# V2 Public Settings, Activity and Statistics

## Overview

From version **0.261.185**, a public workspace's Owner and Admins manage its
profile, logo, file downloads and retention in V2, read its recent activity,
and chart and export its statistics, in the **Settings**, **Activity** and
**Statistics** sections beside **Members** under **Manage**. From version
**0.261.448** the Owner also deletes an empty workspace from a danger zone in
Settings, natively, so V2 no longer hands off to the classic page for it.

Also from version **0.261.448**, the sections stay available in a locked,
inactive or unrecognized-status workspace, as they do on the classic manage
page: the Owner and Admins keep Settings and Activity, and every stored role
(including a DocumentManager) keeps Statistics. Before, V2 closed all three
there, so a workspace that had been made inactive could be managed only in
classic. See *Locked, inactive and unrecognized-status workspaces* below.

These are the group sections, shared through one set of components with a
public scope; see [V2 Group Settings](V2_GROUP_SETTINGS.md). The routes are in
[Public Settings APIs](PUBLIC_SETTINGS_APIS.md).

## Who sees what

The server decides, and V2 follows its `settings_management` hint:

- **Settings** and **Activity** are open to the Owner and Admins, and
  **Statistics** also to DocumentManagers, in every status of the workspace.
  Anyone else sees them locked, with the reason: the role's, or, while the
  workspace can't be viewed (inactive, or a status this version doesn't
  recognize), the status's.
- Only the Owner changes the name, description, color and logo, and only in an
  active or upload-disabled workspace. In any other status they are read-only,
  with the reason shown.
- The Owner and Admins change file downloads, when the administrator allows
  downloads for the workspace, and retention, when public retention policies are
  on. Each appears only when it applies, and neither depends on the status.
- A locked control says why.

## Locked, inactive and unrecognized-status workspaces

Version **0.261.448**. The routes behind Settings, Activity and Statistics check
no status except for the profile and logo, and the classic manage page shows an
inactive workspace to its Owner and Admins with only a status alert, so V2 keeps
the sections for them. The workspace context reports `settings`, `activity` and
`statistics` as available whatever the status, for the people above; the
content sections (Documents, Tags, Prompts, Identities, File sources) stay
closed with the status as the reason, because the workspace can't be viewed.

| Caller | Settings | Activity | Statistics |
|---|---|---|---|
| Owner, Admin | Open | Open | Open |
| DocumentManager | Closed, with the status's reason | Closed, with the status's reason | Open |
| Reader (no stored role) | Closed, with the status's reason | Closed, with the status's reason | Closed, with the status's reason |

In an inactive, locked or unrecognized-status workspace the Owner's profile and
logo are read-only: the name, description and colour fields are disabled, the
logo can't be replaced or removed, and Settings says why ("This workspace is
locked or inactive, so its name, description, color and logo can't be changed.",
or the server's own sentence when the status isn't recognized). An Admin is told
that only the Owner edits them, as in an active workspace. File downloads,
retention and the Owner's danger zone work as they do in an active workspace.

If a workspace becomes inactive while Settings is open, the section stays: the
save is refused with the status, the profile re-gates read-only with your draft
kept, and **Discard changes** clears it. Before this change the whole section
closed on the next refresh and the draft went with it.

Two things differ from the classic manage page. Classic lets the Owner edit the
profile and logo whatever the status, and V2 keeps them read-only because the V2
settings routes refuse them; to edit them, make the workspace active again in
Control Center first. And classic keeps the Identities and Sync tabs of an
inactive workspace (when File Sync is on), while the V2 identity and file-source
routes refuse an inactive or unrecognized-status workspace, so those two
sections stay closed.

## Settings

The editor is the group's: only changed profile fields are sent, a logo upload
that isn't a readable image keeps the file selected for a retry, retention
offers the classic choices within the server's limits, and a save that loses to
someone else's change reloads that section and keeps your edit over it. A
successful save refreshes the workspace context.

**Delete this workspace** is shown only to the Owner. It says how many current
documents the workspace holds, counted as the V2 document list counts them, and
explains that deleting removes only the workspace record, leaving its prompts,
identities and file sources behind, and that its documents have to be removed
first. It uses the configured workspace label throughout, so an administrator's
"knowledge hub" reads "Delete knowledge hub".

The delete is native, with the same
`DELETE /api/public_workspaces/<workspace_id>` route the classic manage page
calls. The route removes the workspace record at once and creates no approval
request. The flow is the group's (see [V2 Group Settings](V2_GROUP_SETTINGS.md),
*Deleting a group*):

1. The count is read when the section opens and again at the click. A workspace
   that still holds documents isn't deleted, and the zone says so; a count that
   can't be read doesn't delete either.
2. A confirmation names the workspace, says everyone loses access right away
   and that it can't be undone, and names what is left behind.
3. Confirming reads the count once more, then sends the delete once; the
   confirmation can't be dismissed or confirmed again while it is in flight.
4. On success V2 reads the workspaces again, so the picker and the saved active
   workspace drop it, shows "<name> was deleted.", and returns to the list.
5. A refusal stays in the dialog so it can be retried: a 403 shows the server's
   "Only owner can delete", a 404 means it is already gone and V2 leaves as
   after a delete, another 4xx shows the server's message, and a 5xx or a
   dropped connection shows a plain sentence, never a raw error.

Unsaved profile or retention edits hold the **Delete** button, with a hint,
instead of being discarded.

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
- The delete route removes only the workspace record and checks neither the
  workspace's status, its documents nor its prompts; the document gate is the
  page's. The count the page gates on is the workspace's current documents. The
  classic page counts every stored document record, earlier versions included,
  so in the unusual case of a workspace holding only earlier versions classic
  would still refuse where V2 would not.
- A workspace's profile and logo are read-only in V2 in a locked, inactive or
  unrecognized-status workspace, although the classic manage page lets the
  Owner edit them there. The V2 settings routes refuse them, so the Owner makes
  the workspace active again in Control Center first. Downloads, retention, the
  activity feed and the statistics are not restricted by status, in V2 or in
  classic.
- Identities and File sources stay closed in an inactive or unrecognized-status
  workspace, because their V2 routes refuse it; see
  [V2 Public Connections](V2_PUBLIC_CONNECTIONS.md). Classic keeps their tabs.

## Testing and validation

- `ui_tests/test_v2_public_settings.py`: who sees what, the profile, logo,
  downloads and retention editors, conflicts, activity, statistics and the
  export, and the danger zone -- the count gate, the confirmation, every refusal
  and its retry, a dropped connection, an already deleted workspace, a second
  click, unsaved edits and the administrator's workspace label -- on desktop and
  mobile. From version **0.261.448** it also covers an inactive and an
  unrecognized-status workspace: the Owner and Admins keep the three sections
  with a read-only profile and logo, working downloads, retention and danger
  zone, a document manager keeps only Statistics, a reader keeps none, a
  workspace that goes inactive while Settings is open keeps the section and the
  draft, and the section fits both themes at both breakpoints.
- `ui_tests/test_v2_public_journeys.py`: the rail for every role and status,
  including the Manage sections an inactive or unrecognized-status workspace
  keeps for its managers, written out independently of the fixture, on desktop
  and at 390 px wide.
- `functional_tests/test_v2_workspace_delete_fixture_parity.py`: the real delete
  route bodies beside the browser fixture's answers, and the premise that the
  route checks no status and no documents and creates no approval request.
- The group suites `ui_tests/test_v2_group_settings.py`,
  `test_v2_group_journeys.py`, `test_v2_group_members.py` and
  `test_v2_group_workspace_shell.py` pass unchanged; the group sections are
  wrappers over the same components.
- `functional_tests/test_v2_public_stats_formatter_parity.mjs` and
  `test_classic_public_stats_export_fix.py`: the CSV's byte formatting against
  classic.
- `functional_tests/test_public_context_fixture_parity.py`: the four Manage
  sections and `settings_management` for every role and status, including an
  inactive and an unrecognized status, with the download and retention
  switches. `test_public_settings_policy.py` holds the settings decision, and
  the native routes behind it, to the classic routes for every status.

## Related

- [Public Settings APIs](PUBLIC_SETTINGS_APIS.md)
- [V2 Group Settings](V2_GROUP_SETTINGS.md)
- [V2 Public Members](V2_PUBLIC_MEMBERS.md)
