# V2 Public Workspace Directory

## Overview

The V2 public workspace directory lists every public workspace you can
discover, lets you open one, and lets you choose which public workspaces appear
in public chat. It replaces the placeholder that linked to the classic
directory, and the V2 public workspace picker now reads the same list.

Implemented in version **0.261.175**.

Dependencies:
- the public workspace feature (`enable_public_workspaces`);
- the V2 public workspace page and its selected-workspace context
  ([V2 Shared Workspace Context](V2_SHARED_WORKSPACE_CONTEXT.md));
- the public workspace labels an administrator configures.

## What it offers

- **Views:** **All**, every public workspace you can discover, or **My
  workspaces**, the ones you own, administer or manage documents in.
- **Search** by name, description or exact id. Matching ignores case.
- **Paging**, 20 at a time. The view, search and page are kept in the page
  address, so back, forward and a shared link reopen the same list.
- **Open** a workspace: this goes to its V2 page, `/v2/public/<id>`.
- **Visible for chat:** a per-workspace switch that decides whether its
  documents appear in public chat.

Unlike the group directory there's nothing to join here; public workspaces are
readable by every signed-in user. From version **0.261.179** the directory also
offers **Create**, when the server's `public_directory` hint says the caller may
create a public workspace; see [V2 Public Members](V2_PUBLIC_MEMBERS.md).

From version **0.261.184**, a workspace's row offers **Ask to manage documents**
to someone who doesn't manage it yet, then marks it **Requested** with a
**Cancel request** button until the Owner or an Admin decides in Members. The
row's `membership` from the server decides which appears, never the browser.

### Visible for chat

- The choice is stored in your user settings as `publicDirectorySettings`, a
  `{workspaceId: true|false}` map, in exactly the shape the classic directory
  uses. So a workspace shown or hidden in one interface stays that way in the
  other.
- With no saved choices, every public workspace is visible. That's the same
  rule the public chat route applies on the server.
- A switch writes only that workspace's entry, so it never rewrites another.
  Opening a workspace doesn't hide the others, unlike classic's **Set active**.
- A workspace whose status doesn't allow reading is shown as unavailable. Its
  switch can be turned off, and from version **0.261.187** it can't be turned
  on.

### Visibility tools

From version **0.261.184**, the directory also offers:
- **Show all in chat** and **Hide all from chat**, which set every workspace in
  the directory at once;
- **Saved lists**: **Save current** stores the workspaces visible now, **Use
  this list** makes exactly a list's workspaces visible and hides the rest, and
  a list can be deleted. They're stored as `publicDirectorySavedLists`, the
  classic directory's shape, so either interface can use them;
- **Chat with visible (classic)**, which saves any pending change and opens
  classic chat over the workspaces visible now. V2 chat can only scope to one
  public workspace (decision 31).

The bulk and saved-list actions cover the whole directory, not the page on
screen, up to 1,000 workspaces; past that they refuse and say how many there
are. Each reports how many workspaces it changed. From version **0.261.187**,
**Show all in chat** and **Use this list** leave an unavailable workspace
hidden, and say how many they skipped: public chat doesn't yet check a
workspace's status itself (decision 32).

### Labels

Public workspaces can be renamed by an administrator, for example to
"Knowledge base". The directory, the public workspace page, the picker, the
sidebar entry and the chat handoffs all use the configured labels. They fall
back to the default wording for any label left blank, as classic does.

## How it's built

| Piece | File |
| --- | --- |
| The directory route | `application/single_app/route_backend_public_directory.py` |
| Its rules: the query, the caller's view, the projected rows, search and paging | `application/single_app/functions_public_directory.py` |
| The page | `application/v2_ui/src/pages/PublicDirectoryPage.tsx`, `components/workspace/PublicDirectoryList.tsx` |
| The directory client | `application/v2_ui/src/lib/publicDirectory.ts` |
| Visible for chat | `application/v2_ui/src/lib/publicVisibility.ts` |
| The labels | `application/v2_ui/src/lib/publicWorkspaceLabels.ts` |
| The picker, now on the directory route | `components/workspace/PublicWorkspacePicker.tsx`, `lib/workspaces.ts` |

The route is described in
[Public Directory APIs](PUBLIC_DIRECTORY_APIS.md). The picker moved to it
from the classic list route because that route returns every owner's email to
any signed-in user (decision 22). The directory's rows carry no owner email or
id.

The selected-workspace context lists only the sections public workspaces have:
documents, tags, prompts, identities and sync, plus a **Manage** group:
**Members** from version **0.261.179** (see [V2 Public Members](V2_PUBLIC_MEMBERS.md)),
and **Settings**, **Activity** and **Statistics** from version **0.261.185** (see
[V2 Public Settings](V2_PUBLIC_SETTINGS.md)).
Agents, actions, endpoints and workflows, which public workspaces will never
have, aren't listed.
The V2 client checks a public context against its own section list, and a link
to a section public workspaces don't have opens "Section not found".

## Testing and validation

- `functional_tests/test_public_directory_apis.py` and
  `test_public_directory_transport.py` run the real route and its rules
  through `test_support/public_directory_harness.py`. They cover:
  - the query rules and paging bounds;
  - both views;
  - rows with no owner email, id or member entry;
  - search that ignores case;
  - the data-free failure answer;
  - that the route answers GET only.
- `test_public_directory_fixture_parity.py` holds the browser fixture to the
  route.
- `test_v2_public_directory_list_route_pin.py` checks the picker reads the
  directory route, never the classic list.
- `test_v2_public_directory_settings_keys.py` checks the user settings keys
  against the server's allowlist.
- `test_v2_public_workspace_labels_logic.mjs` and
  `test_v2_public_workspace_labels_pin.py` check the label fallbacks and tie
  the defaults to the server's.
- `test_public_context_fixture_parity.py` covers the section list and the
  Documents section's manager rule.
- Browser: `ui_tests/test_v2_public_directory.py` (23), with
  `test_v2_public_documents.py` unchanged in behaviour.

## Known limitations

- **Chat with visible** opens classic chat (decision 31).
- The bulk and saved-list actions stop at 1,000 workspaces.

## Related

- [Public Directory APIs](PUBLIC_DIRECTORY_APIS.md)
- [V2 Shared Workspace Context](V2_SHARED_WORKSPACE_CONTEXT.md)
- [V2 Public Document Browsing](V2_PUBLIC_DOCUMENT_BROWSING.md)
