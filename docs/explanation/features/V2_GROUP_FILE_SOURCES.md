# V2 Group File Sources

## Overview

Implemented in version: **0.261.147**, tracked in
`application/single_app/config.py`.

File sources are the connections a group syncs documents from: an SMB share, an
Azure Files share, or an Azure Blob Storage container. The documents they bring
in are processed like uploads and appear in the group's documents. The native V2
group workspace now manages them in its **File sources** section, at
`/v2/groups/<group_id>/sync`. Before this release, the section was marked
Classic.

The section talks only to the group's immutable-target routes, described in
[Group File Source APIs](GROUP_FILE_SOURCE_APIS.md). Every request names the
group in its path.

## Who can do what

| | Owner, Admin, DocumentManager | Ordinary member |
|---|---|---|
| See the section, list sources, read run history | yes | no |
| Create, edit, delete, sync now, test, browse, ignore a path | yes, in an `active` group | no |

These are the server's rules, and the same ones the classic group workspace
applies. The section is offered when File Sync is enabled for the group.
Managers in a `locked` or `upload_disabled` group get a read-only list.

## The section

The list shows each source's name, path and type, whether it's enabled or
paused, and the identity it uses, if any. Each row can expand its last ten runs,
with their status and times, from the source's own runs route.

Every control comes from the server:

- **New file source** appears only when the group's `file_source_management`
  hint, in the workspace context, includes `create`.
- **Sync now, Edit and Delete** appear on a row only when the row's own
  `source_actions` include them.
- A missing or malformed hint hides the control; there is no fallback.

A list the section can't trust is a load error, not an empty list. That covers a
response with no `file_sources` array, and a row without an `id`, a string
`config_revision`, or a `source_actions` array.

The overview's File sources card links to the native section.

## The editor

Creating or editing opens a dialog with:

- **Name** and **Source type**. The types are the ones the editor options offer
  for this group.
- **Connection**: the network path, or the service URL and share or container,
  with the folder, directory or prefix to sync. **Browse** lists the remote
  location from the draft, before anything is saved.
- **Authentication**: a reusable group **Identity**, or credentials entered
  directly. Only identities whose uses include File Sync and whose type suits
  the source are offered, which is the same rule the server applies when saving.
  A stored password or secret is never shown. Leaving it blank keeps it, and a
  new value replaces it.
- **Test connection**, which runs against the draft. Success shows what was
  checked, for example "Connected. Checked 25 entries: 3 folders, 22 files." A
  failure shows the server's message as returned.
- **Schedule and scope**: enabled, include subfolders where the type supports
  it, and a sync interval in minutes within the server's limits.
- **Filters** (optional): include patterns, exclude patterns, and allowed file
  types.

When browsing a saved source, **Ignore** skips a path on the next run, and
**Restore** includes it again. Browse doesn't report which paths are ignored, so
the dialog shows the state the server returned for each path you change during
the session.

### Saving

- Create sends the connection's fields. An edit sends them with the source's
  `expected_config_revision`.
- **Changed elsewhere** (`config_conflict`): the dialog keeps your changes and
  offers a reload. From version **0.261.152**, the reload merges the stored
  source into your draft: the other person's changes fill the fields you didn't
  touch, your edits stay, and a field you both changed is named. If the source
  was deleted meanwhile, the dialog says so and saves nothing.
- **Kept changing** (`write_conflict`): nothing your draft depends on changed,
  so the dialog keeps your changes and you can save again as they are.
- **Invalid details:** the server's reviewed message is shown as returned, with
  the draft kept.

## Syncing and deleting

**Sync now** queues a run. If a sync is already queued or running, or the
tenant's concurrent-run limit is reached, the server's message is shown instead.

**Delete** asks what to do with the documents the source brought in:

- **Keep documents** removes the connection and leaves the documents.
- **Delete documents too** also removes every document the source produced,
  including every version, and reports the counts.

When a delete is refused, the section says what actually happened:

- **A sync is running** (`source_busy`): wait for it to finish, then delete.
- **Changed elsewhere** (`config_conflict`): reload, then delete again.
- **Some documents couldn't be deleted** (`delete_incomplete`): the source is
  kept, the counts are shown, and you can try again.
- **The documents were deleted, but the source wasn't removed** (a partial
  refusal): the section says the documents were deleted, with the counts, and
  reloads to show the true state.

## Known limitations

- **Saving after a conflict kept your whole draft until 0.261.152.** It re-sent
  every field, which could undo the other person's changes. The reload now
  merges instead; see the
  [conflict rebase fix](../fixes/GROUP_EDITOR_CONFLICT_REBASE_FIX.md).
- **Personal file sources are unchanged.** My Workspace keeps its existing list
  and run history, without the native editor.

## Testing and validation

`ui_tests/test_v2_group_file_sources.py` (36 cases) drives the production V2 build against
a closed fixture, `ui_tests/fixtures/group_file_sources.py` on the shared group
harness. The fixture serves only the group routes and records any personal File
Sync or personal identity request as unexpected. It covers:

- the layout in both themes at desktop and mobile sizes, and the overview card;
- reads going only to the group's routes, and a malformed row failing loudly;
- per-row gating from `source_actions`, beside an editable control;
- create, a conditional edit that keeps the stored secret, and both conflicts;
- delete with and without the documents, `delete_incomplete`, a partial
  refusal, and a busy source;
- Sync now, with both reviewed refusals, and the run history;
- test connection success and failure, browsing into a folder by `type`, and
  ignore then restore from the returned item;
- identity filtering by use and source type;
- a manager in a locked group getting a read-only section, with no write, test,
  browse or ignore request;
- a member getting no native section, in both themes at both sizes;
- the adapter seam (`ui_tests/test_v2_group_file_sources.ts`, bundled with the
  local esbuild): the personal adapter calls exactly the personal routes, and
  the group adapter never does.

The fixture enforces the server's rules: `source_actions` computed from the
policy, the `test` operation for test and browse, `edit` for ignore, reads
refused outside the browsable statuses, and the server's exact messages and
shapes.

`functional_tests/test_group_file_source_fixture_parity.py` (21 cases) runs the same
requests against the real Flask routes and the fixture, and compares the
response shape of every route the section calls: list, create, update and
delete, including each conflict and partial refusal; sync and its two refusals;
runs; saved and unsaved test and browse; ignore; options; and a reviewed 400.
The backend harness it shares with the API suite is
`functional_tests/test_support/group_file_source_harness.py`.

## Related

- [Group File Source APIs](GROUP_FILE_SOURCE_APIS.md)
- [V2 Group Identities](V2_GROUP_IDENTITIES.md)
- [V2 Group Workflows](V2_GROUP_WORKFLOWS.md)
