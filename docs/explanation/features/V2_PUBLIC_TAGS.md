# V2 Public Workspace Tags

## Overview

A public workspace in V2 has a native **Tags** section. Anyone who can view the
workspace can browse its tag vocabulary and see how many documents carry each
tag. An Owner, Admin or DocumentManager of an active workspace can also create,
recolour, rename, merge and delete tags there, so the whole tag vocabulary of a
public workspace is administered without leaving V2.

Tags was the last public content section that still pointed at the classic
page: V2 listed it, but the server's public context kept it closed, so the
vocabulary of a public workspace could only be administered on the classic
public workspace page. From version **0.261.445** it is the group workspace's
tag editor running against the public workspace's own tag routes.

Implemented in version **0.261.445**, tracked in
`application/single_app/config.py`.

Dependencies:
- the public document read and management routes
  ([Public Document Read APIs](PUBLIC_DOCUMENT_READ_APIS.md),
  [Public Document Management APIs](PUBLIC_DOCUMENT_MANAGEMENT_APIS.md));
- the selected-workspace context and its `document_management` hint
  ([V2 Shared Workspace Context](V2_SHARED_WORKSPACE_CONTEXT.md));
- the tag editor the personal and group workspaces already use
  ([V2 Group Document Management](V2_GROUP_DOCUMENT_MANAGEMENT.md)).

## Who can do what

The server decides, and V2 follows its hints:

| Viewer | What the section offers |
|---|---|
| Owner, Admin or DocumentManager of an `active` workspace | Create a tag, recolour, rename (or merge) and delete. |
| The same roles in a `locked` or `upload_disabled` workspace | Browse only. The server grants `manage_tags` only while the workspace is active, so the page offers no control and says "Tag management is not available with this workspace's current permissions. You can still browse its vocabulary." |
| Any other member, including a plain reader | Browse only, with the same explanation. |
| Anyone, in an `inactive` workspace or one whose status isn't recognized | The section is closed with the server's reason, and the vocabulary isn't read. |

The write controls come from the `manage_tags` operation in the context's
`document_management` hint, never from a role check in the browser. The
section's availability comes from `sections.tags`, which the server opens for
any viewable status and marks manageable for an active manager, as it does for
Documents.

Who can *apply* tags to documents is separate: that is `tag_documents` in the
Documents explorer, and the Tags page links there.

## Using it

- **Browse:** each tag shows its colour and how many current documents carry it.
  A search box appears once the vocabulary holds more than six tags. The
  overview's **Tags** card links here and shows the vocabulary's size.
- **Create:** type a name, optionally choose a colour, and press **Create**.
  Names are trimmed and stored in lowercase.
- **Recolour:** pick a colour on the tag, then **Save colour**. A colour is a
  vocabulary write on a shared workspace, so it waits for the explicit save.
- **Rename:** select the tag's name, type the new name and press **Save**.
  Renaming onto an existing tag **merges** the two; the button says **Merge**
  and a line warns that saving merges them. A name containing a slash, such as
  `legacy/review`, is encoded in the request path.
- **Delete:** the trash button asks for confirmation, names the workspace, and
  says only current documents are changed and earlier versions are not
  rewritten. The documents themselves are kept.
- **Chat:** the chat button on a tag takes it to a new conversation as a filter
  on this public workspace's documents, not as a list of them. It's off for a
  tag no document carries, and while the workspace's chat permission is off.
- **Unsaved drafts:** a half-typed new tag, a rename or a colour waiting for its
  save counts as an unsaved change. Leaving the page asks first, and a change
  still being saved can't be discarded.

The wording follows the administrator's label for public workspaces. With the
label "knowledge hub", the page says "this knowledge hub's documents".

### What a change touches

Each change is applied by `change_public_document_tag`, which rewrites only each
document's **current version**. Earlier versions keep their tags, and another
workspace's documents are never touched. The server returns what it confirmed:
- If every document was updated, V2 says the change is confirmed for this
  workspace's current documents.
- If some documents could not be updated, the receipt is partial. The page keeps
  the old tag in the vocabulary, lists each failed document with the server's
  reason, and says how many updates were confirmed, so the change can be retried.
- If the workspace's tags or permissions changed while the change was being
  made, the server answers "The workspace's tags or permissions changed. Refresh
  and retry." and V2 shows that sentence and keeps the draft.

## Technical specifications

### Endpoints

All are immutable-target routes; the workspace is in the path, never in a query
and never the saved active workspace.

| Action | Route |
|---|---|
| Read the vocabulary | `GET /api/public-workspaces/<workspace_id>/documents/tags` |
| Create | `POST /api/public-workspaces/<workspace_id>/documents/tags` with `{tag_name, color}` |
| Recolour or rename | `PATCH /api/public-workspaces/<workspace_id>/documents/tags/<tag_name>` with `{color}` or `{new_name}` |
| Delete | `DELETE /api/public-workspaces/<workspace_id>/documents/tags/<tag_name>` |

Tagging documents in bulk, `POST .../documents/bulk-tag`, is the Documents
explorer's, not this section's.

### Files

| File | Purpose |
|---|---|
| `application/single_app/functions_workspace_context.py` | The public context's `sections.tags`: open for any viewable status, manageable by an active manager. This is the only server change |
| `application/v2_ui/src/pages/workspace/TagsSection.tsx` | `PublicTagsSection`, the shared tag editor with a public reader and operations, and the per-scope wording |
| `application/v2_ui/src/pages/PublicWorkspacePage.tsx` | Renders the section when the viewer can view documents; the classic handoff card is gone |
| `application/v2_ui/src/lib/documentOperations.ts`, `documentReadAdapter.ts` | The public tag adapters the section shares with Documents |
| `ui_tests/test_v2_public_tags.py`, `ui_tests/fixtures/public_workspace.py` | The browser suite and the public context fixture |

## Testing and validation

- `ui_tests/test_v2_public_tags.py` drives the production V2 build against the
  public document management fixture, whose receipts are held to the real
  routes by `functional_tests/test_public_document_fixture_parity.py`. It
  covers the native section and its rail and overview entries, the vocabulary
  with counts, a stray resource segment, the read-only explanation for a reader
  and for managers of a locked or upload-disabled workspace, the closed section
  for an inactive or unrecognized workspace, create (for each manager role),
  recolour, an encoded rename, a merge and a delete that leave earlier versions
  and other workspaces untouched, a partial result, a vocabulary conflict, a
  refused create, a permission that disappears mid-session, the chat button's
  gating, the unsaved-draft guard, the administrator's label in the wording,
  and both themes at both breakpoints.
- `functional_tests/test_public_context_fixture_parity.py` holds the fixture's
  `sections.tags` to the real context builder for every role and status, and
  `test_v2_public_workspace_labels_pin.py` keeps the page's wording on the
  configured label.

## Known limitations

- The chat button's navigation isn't driven end to end in the browser suite;
  its gating is. The hand-off itself is the explorer's own, with this
  workspace's identifier.
- A tag's count is the number of current documents the viewer may see, as the
  Documents section counts them.
- Tags applied to earlier document versions are not edited here; the server
  rewrites current versions only.
