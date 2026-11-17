# V2 Admin File Sync Targets

## Overview

File Sync sources normally belong to whoever owns the workspace. An administrator sometimes has
to set one up for someone else: a user who cannot reach their file share from their own machine,
a group whose owner has left, a public workspace nobody manages yet. The classic File Sync card
has a block for each kind of workspace for that: search for a user, a group or a public
workspace, or paste an ID, then open **Manage Sources** for that target.

The V2 File Sync card now has the same three blocks under **Manage sources for someone else**.
Choosing a target opens the file sources workbench that a workspace's own manager uses, over the
administrator routes that name the target, so the editor, connection test, folder browsing, Sync
now, run history and deletion behave as they do there. The V2 File Sync page used to say the
classic page's administrator-managed source search had no V2 equivalent yet; it now has one.

**Implemented in version:** **0.261.445** (`application/single_app/config.py`)

**Dependencies:** `route_backend_file_sync.py` (the administrator routes),
`route_backend_workspace_identities.py` (identities of a target), `functions_file_sync.py`, the
shared file sources workbench (`pages/workspace/GroupFileSourcesSection.tsx`,
`lib/fileSourceWorkbench.ts`, `components/fileSources/FileSourceEditorDialog.tsx`), and the V2
Admin Settings File Sync card. No new packages or browser assets.

## Technical specifications

### Where it sits

`admin_settings_fields.py` declares one component field, `file-sync-target-manager`, at the end of
`file-sync-section`, with `depends_on: enable_file_sync` so it folds away with the rest of the card
when File Sync is off. `AdminSettingsPage.tsx` draws it with `FileSyncTargetManager`.

### Finding a target

Each block is a labelled region (**User sources**, **Group sources**, **Public workspace
sources**) with a search box, a matches list, an ID box and **Manage sources**.

| Kind | Search route | Result shown |
| --- | --- | --- |
| User | `GET /api/admin/file-sync/users/search?q=` | Display name and email |
| Group | `GET /api/admin/file-sync/groups/search?q=` | Name and description |
| Public workspace | `GET /api/admin/file-sync/public-workspaces/search?q=` | Name and description |

The server answers a query shorter than two characters with nothing, so V2 does not send one and
says "Type at least 2 characters to search." A newer search replaces an older one still in flight.
Choosing a match fills the ID box and the selection line ("Selected: Finance (Finance team)");
typing in the ID box clears the name and shows "Target ID: ...". A pasted ID is checked before it
can name a route: it cannot contain slashes, question marks, `#` or control characters. A search
that fails shows the server's message; a changed response shape is an error, not "no matches".

### Which kinds are offered

The server decides from the **saved** settings. `_require_admin_target_context` refuses a target
unless File Sync, the kind's workspace switch and Redis Cache (File Sync is effectively off
without it) are all on. The blocks therefore read the saved switches, not the unsaved draft, and
a kind that is off says why and disables its controls:

- "File Sync is not on in the saved settings. Turn on Enable File Sync and save ..."
- "Redis Cache is off in the saved settings, and the server treats File Sync as off without it ..."
- "Group workspaces is off in the saved settings. Turn it on and save ..."

The Redis URL and key are not visible to the page, so a deployment whose Redis is switched on but
not configured still gets the server's refusal, shown as the server words it.

The assignment lists and the administrators-only and app-role rules in each kind's Access panel do
not apply to an administrator managing sources on a target's behalf (`admin_management=True` in
`functions_file_sync.py`).

### The manager

**Manage sources** opens a dialog (**Manage user / group / public workspace sync sources**, with
the target's name and ID) holding the shared workbench with an adapter over these routes
(`lib/adminFileSyncTargets.ts`, `createAdminFileSourceWorkbench`):

| Operation | Route |
| --- | --- |
| List | `GET /api/admin/file-sync/<kind>/<id>/sources` |
| Add | `POST .../sources` |
| Edit | `PATCH .../sources/<source>` |
| Delete (with or without its documents) | `DELETE .../sources/<source>` |
| Sync now, run history | `POST .../sources/<source>/sync`, `GET .../sources/<source>/runs` |
| Test, browse (new or saved) | `POST .../sources/test-connection`, `.../sources/<source>/test-connection`, `POST /api/admin/file-sync/<kind>/<id>/sources/browse`, `.../<source>/browse` |
| Editor options | `GET /api/admin/file-sync/<kind>/<id>/source-options` (new) |
| Identities of the target | `GET /api/admin/workspace-identities/<kind>/<id>/identities` |

`<kind>` is `personal`, `group` or `public`. The administrator routes differ from a workspace's own
in ways the adapter absorbs: lists and records are wrapped as `sources` and `source`, rows carry no
per-row operation hints (every row is offered every operation), writes are unconditional (there is
no config revision to send or conflict on), and there is no single-source read, ignore-a-path route
or tag read, so a row is re-read from the list and those two controls are left out. The documents
link is left out too: the sources belong to the target, and the workspace documents page that link
would open is the administrator's own.

**New route.** `GET /api/admin/file-sync/<scope_type>/<scope_id>/source-options` is the one route
added. It is `@login_required`, `@admin_required` and `@enabled_required("enable_file_sync")`,
refuses a query string or body, resolves the target with `_require_admin_target_context`, and
returns `build_file_sync_source_options` for it: the source types the target may be offered, the
target's identities that the server would accept for each, the schedule and source limits and the
recursive and remote-delete defaults. It carries no secrets.

### Who can change what

Adding and listing a target's sources do not need a role in the target. Changing, syncing, testing
or deleting a **saved** source, and reading its run history, go through
`get_authorized_sync_source`, which applies the workspace's own role check to the administrator:
for a group or public workspace that is a manager role (Owner, Admin or DocumentManager) in it,
and for a user's personal sources the lookup is keyed on the administrator's own id. The server
therefore refuses those operations for a workspace the administrator does not manage and for
another user's personal sources, with "You do not have permission to perform this File Sync
operation." or "The requested File Sync resource was not found.". The dialog says this once, and
the refusal is shown in the editor or the list with what was typed kept. This is the behaviour the
classic **Manage Sources** modal has; it is not changed here. (Verified by reading
`get_authorized_sync_source`, `update_file_sync_source` and `delete_file_sync_source`; not run
against a deployment.)

### Not ported

The classic manager modal also lets the administrator create, edit and delete the target's
reusable **identities**. V2 lists them in the credential picker but does not manage them: group
and public identities are managed in the workspace's own Identities section, and a user's in
their own workspace. A source can instead hold its credentials directly.

## Usage

1. Open **Admin Settings > Knowledge > File Sync**. Make sure **Enable File Sync**, Redis Cache and
   the kind of workspace are on and saved.
2. Under **Manage sources for someone else**, find the user, group or public workspace by name, or
   paste its ID.
3. Choose **Manage sources**. Add a source, test its connection, browse for folders, sync it, or
   read its run history.
4. Close the dialog; focus returns to **Manage sources**.

## Testing and validation

| Test | Covers |
| --- | --- |
| `functional_tests/test_v2_admin_parity.py` | Every request the adapter can send has a route in all three kinds; the options route's decorators and body; the schema declares the component behind File Sync and the page reads the saved switches |
| `functional_tests/test_v2_admin_parity_logic.ts` | Query and ID checks, result parsing, availability reasons, the envelopes, and each adapter operation's request, body, and error mapping against a stubbed fetch |
| `functional_tests/route_tests/` | The options route is under the File Sync blueprint policy and pinned as login, admin and enabled |
| `ui_tests/test_v2_admin_file_sync_targets.py` | The built card: three blocks at 1440px and 390px, the saved-settings gating, a short query not sent, a search and a pick, the manager listing, adding and syncing, a refused edit with the draft kept, a failed search, a malformed pasted ID, and focus returning |
| `ui_tests/test_v2_admin_file_sync_single_card.py` | The card's layout and overflow with the manager present |

### Known limitations

- Changing, syncing and deleting saved sources, and run history, are refused for a workspace the
  administrator does not manage and for another user's personal sources (see above). Creating a
  source works for any target.
- Ignoring a path while browsing and fixed-tag suggestions are not available for a target.
- Not run against a live deployment: the tests intercept the administrator routes.
