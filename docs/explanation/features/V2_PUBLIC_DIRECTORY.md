# V2 Public Workspace Directory

## Overview

The V2 public workspace directory lists every public workspace you can
discover and lets you open one or chat across available public knowledge.
It replaces the placeholder that linked to the classic
directory, and the V2 public workspace picker now reads the same list.

Implemented in version **0.261.175**.
Updated in version: **0.261.372** (`application/single_app/config.py`).

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
- **Chat with all public:** starts a public-only V2 chat across currently available
  public workspaces. Ordinary chat can mix selected public sources with personal
  and group sources.

Unlike the group directory there's nothing to join here; public workspaces are
readable by every signed-in user. From version **0.261.179** the directory also
offers **Create**, when the server's `public_directory` hint says the caller may
create a public workspace; see [V2 Public Members](V2_PUBLIC_MEMBERS.md).

From version **0.261.184**, a workspace's row offers **Ask to manage documents**
to someone who doesn't manage it yet, then marks it **Requested** with a
**Cancel request** button until the Owner or an Admin decides in Members. The
row's `membership` from the server decides which appears, never the browser.

### Public source availability

From **0.261.372**, V2 does not offer Visible for chat switches, show/hide
actions or saved visibility lists. Those legacy preferences could otherwise
hide a processed public document from the picker even when the same reader
could open its workspace. They remain available in classic and are not erased.

Every public workspace currently eligible for chat can supply sources to V2,
including one absent from a classic custom list. This applies to ordinary
mixed-source chat, public-only chat, source references and workflow choices.
Explicitly selected documents and workspace locks still narrow retrieval.
Inactive or invalid-status workspaces, unavailable capabilities, screening holds
and pending publication remain restricted.

Old V2 links using the Visible aggregate mode open as All. See
[Aggregate public chat](V2_AGGREGATE_PUBLIC_CHAT.md).

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
| V2 public-source policy | `application/single_app/public_source_policy.py` |
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
- `test_v2_public_source_discovery_policy.py` checks the V2/V1 policy boundary,
  mixed source admission, worker isolation and retained explicit selections.
- `test_v2_public_workspace_labels_logic.mjs` and
  `test_v2_public_workspace_labels_pin.py` check the label fallbacks and tie
  the defaults to the server's.
- `test_public_context_fixture_parity.py` covers the section list and the
  Documents section's manager rule.
- Browser: `ui_tests/test_v2_public_directory.py`, with
  `test_v2_public_documents.py` unchanged in behaviour.

## Known limitations

- Availability is checked again when a request runs; directory discovery is not
  a permanent permission grant.

## Related

- [Public Directory APIs](PUBLIC_DIRECTORY_APIS.md)
- [V2 Shared Workspace Context](V2_SHARED_WORKSPACE_CONTEXT.md)
- [V2 Public Document Browsing](V2_PUBLIC_DOCUMENT_BROWSING.md)
