# V2 Public Connections

## Overview

From version **0.261.182**, a public workspace's managers keep its
**identities** and **File Sync sources** in V2, in the **Identities** and
**Sync** sections of the public workspace page. They're the group workspace's
sections, driven by public workspace routes and rules. A public workspace has
no actions, so File Sync is what both sections are for.

Implemented in version: **0.261.182**. The routes are in
[Public Connection APIs](PUBLIC_CONNECTION_APIS.md).

## Who can do what

| | Owner, Admin, DocumentManager | Reader |
|---|---|---|
| See the Identities and Sync sections | yes, when File Sync is enabled for the workspace | no |
| Create, edit and delete identities and sources; test, browse and sync | yes, in an `active` workspace | no |

- In a `locked` or `upload_disabled` workspace, managers can open both
  sections read-only.
- In an `inactive` workspace, or one whose status isn't recognized, the
  sections are unavailable, as the rest of the workspace is.
- When File Sync isn't enabled for the workspace, a manager sees "Identities
  require File Sync." or "File sources require File Sync.". A reader sees that
  their role doesn't permit managing the workspace's connections.

These are the rules the classic manage page applies, plus the status checks
the classic routes never had.

## Identities

The Identities section is the group section:
- **Create** appears only when the workspace context's `identity_management`
  hint includes `create`, and **Edit** and **Delete** only when an identity's
  own `identity_actions` include them.
- The editor offers only the **File Sync** use, since nothing else in a public
  workspace uses an identity.
- Stored secrets are never shown. A stored password or secret appears as kept,
  and a new value replaces it.
- An identity a File Sync source still uses can't be deleted. The refusal names
  the sources.

## File sources

The Sync section and its editor are the group's, with the same fields,
connection tests, browse, **Sync now**, run history, ignored paths, and the
deliberate delete that asks whether to keep the source's documents or delete
them too. See [V2 Group File Sources](V2_GROUP_FILE_SOURCES.md). The public
differences:
- A source binds only to an identity of the same workspace, and the picker says
  "Use a saved workspace identity".
- A source's documents are public documents, so **Delete documents too**
  removes them as public documents, with the counts reported.

Every operation is offered from the server's `file_source_management` hint and
each source's `source_actions`, never from the viewer's role in the browser.
Both sections check that each response names the workspace they asked about.

## Known limitations

- The Identities section's description mentions actions, which a public
  workspace doesn't have.

## Testing and validation

- `ui_tests/test_v2_public_identities.py` (23) and
  `ui_tests/test_v2_public_file_sources.py` (25): roles and statuses, File Sync
  off, create, edit, the conflict reload, secrets kept, deletes (in use, during
  a run, with documents), the File Sync-only capability, the "workspace
  identity" wording, and the scope check on every response, on desktop and
  mobile, light and dark.
- The group suites `ui_tests/test_v2_group_identities.py` and
  `ui_tests/test_v2_group_file_sources.py` pass unchanged.
- The API, transport and fixture parity tests are listed in
  [Public Connection APIs](PUBLIC_CONNECTION_APIS.md).

## Related

- [Public Connection APIs](PUBLIC_CONNECTION_APIS.md)
- [V2 Group Identities](V2_GROUP_IDENTITIES.md)
- [V2 Group File Sources](V2_GROUP_FILE_SOURCES.md)
- [V2 Shared Workspace Context](V2_SHARED_WORKSPACE_CONTEXT.md)
