# V2 Legacy Document Upgrade

## Overview

Documents uploaded before processing progress was tracked have no `percentage_complete`. They
still list and open, but their metadata display and search stay incomplete until they are
updated. The classic interface offered that update as an "Update Older Documents" notice for
personal and group documents. The V2 Documents explorer now does the same for **personal,
group and public** documents, without leaving V2, and the "Classic tools" button that sent group
and public users to the classic page is gone.

**Implemented in version:** `0.261.448` (`application/single_app/config.py`)

**Dependencies**

| Requirement | Why |
|---|---|
| `enable_user_workspace` | Gates the personal list and the personal upgrade route |
| `enable_group_workspaces` | Gates the group list and the group upgrade route |
| `enable_public_workspaces` | Gates the public list and the public upgrade route |

No new setting is added. The notice appears only when the server says some documents are old.

## What a person sees

When the list the explorer reads says some documents predate progress tracking, a notice sits
above the document list:

| Scope | Heading |
|---|---|
| Personal | Update older documents |
| Group | Update older group documents |
| Public workspace | Update older public workspace documents |

The notice says the documents were uploaded with an older version and that updating them
restores full compatibility, including metadata display and search. It offers two buttons:

- **Update now** runs the update. While it runs the button reads **Updating...**, the notice says
  so in a status message, and the rest of the explorer is held still, as it is for any bulk
  operation, so a selection or filter cannot change underneath the request.
- **Maybe later** hides the notice.

When the update ends, the explorer reads the list again whatever the outcome, so what it shows
is what the server then holds. The result is reported in the status line as well as in a toast,
because a toast alone can be gone before everyone has read it:

| Outcome | What is shown | The notice |
|---|---|---|
| Every document updated | The server's sentence, for example "Upgraded 3 group document(s) to the new format." | Gone, because the list no longer says any are old |
| Some documents could not be updated | An alert with the server's sentence and each failed file's name with the reason | Stays, with "Some older documents still need updating." |
| Stopped at the per-request limit | The server's sentence, which says more remain | Stays, with the same line |
| The request failed | An alert reading "The update did not finish. Some documents may already have been updated." followed by the server's sentence | Stays while the list still says documents are old |

Keyboard focus follows the result. After an update it returns to **Update now** while the notice
stays, and moves to the status line once the notice is gone. **Maybe later** moves focus to the
search box, because the button that had it has just been removed.

### Who is offered the update

| Scope | Offered to | Notes |
|---|---|---|
| Personal | The signed-in user | The route upgrades that user's own documents |
| Group | Owner, Admin and DocumentManager of an **active** group | Hidden for ordinary members and for a locked, upload-disabled or inactive group |
| Public workspace | Owner, Admin and DocumentManager of an **active** public workspace | Hidden for readers and for a locked, upload-disabled or inactive workspace |

The explorer shows the notice only when the workspace's `document_management` block lists
`edit_metadata`, the operation the group and public routes authorize the request as. The block is
an interface hint: the server decides again on every request, and again before each document it
writes.

### What "Maybe later" remembers

Nothing. It hides the notice for this visit of the explorer, as the classic notice does, and the
notice returns when the explorer is opened again, when the workspace changes, or after the page
reloads. Reading the list again, for instance after a search, does not bring it back. Nothing
is stored that could leave older documents silently un-updated for good.

## How V2 knows documents are old

Every document list carries one boolean, `needs_legacy_update_check`, and the explorer treats
only `true` as old: a missing flag, which an older server sends, means nothing is old.

| Scope | List route | When the server sets the flag |
|---|---|---|
| Personal | `GET /api/documents` | The user has a document with no `percentage_complete` (checked in the access index, or in Cosmos DB when the index is not used) |
| Group | `GET /api/group_documents?group_id=` | A current document the group **owns** has no `percentage_complete`; a document shared in from another group never sets it |
| Public workspace | `GET /api/public-workspaces/<workspace_id>/documents` | A current document visible to the viewer has no `percentage_complete` |

These lists already existed and already sent the flag; the V2 explorer simply never read it.

## The upgrade routes

| Scope | Route | Reply |
|---|---|---|
| Personal | `POST /api/documents/upgrade_legacy` | `{"message": "Upgraded N document(s) to the new format."}` |
| Group | `POST /api/groups/<group_id>/documents/upgrade_legacy` | The receipt below, with `group_id` |
| Public workspace | `POST /api/public-workspaces/<workspace_id>/documents/upgrade_legacy` | The receipt below, with `public_workspace_id` |

The personal route is the classic route, unchanged. The group and public routes are new, for
these reasons:

- **The classic group and public routes act on the saved active workspace.** The V2 pages name
  the workspace in every request path and never depend on the saved selection, which another
  browser tab can change. A V2 page that called the classic route could upgrade the wrong
  workspace's documents.
- **The classic public route cannot write a public document.** `upgrade_legacy_documents` sends
  the public scope through its personal branch, which updates a document without its
  `public_workspace_id`, so the update fails for any older public document. The classic
  interface has no public notice, so nothing ever surfaced it. The new public route does not
  use that function.

The classic routes, `POST /api/group_documents/upgrade_legacy` and `POST
/api/public_documents/upgrade_legacy`, are left as they were, and the classic group workspace
still uses its own notice.

### Receipt

```json
{
  "message": "Upgraded 2 group document(s) to the new format. 1 could not be updated.",
  "upgraded_count": 2,
  "remaining": false,
  "errors": [
    {"document_id": "...", "file_name": "notes.pdf",
     "error": "legacy_upgrade_failed", "message": "Unable to update this document."}
  ],
  "group_id": "group-a"
}
```

| Field | Meaning |
|---|---|
| `message` | The sentence the explorer shows. It adds the count of documents that could not be updated, and a sentence when more remain |
| `upgraded_count` | Documents the route confirmed upgraded |
| `remaining` | `true` when the route stopped at its limit with older documents still to do |
| `errors` | Each document that could not be updated, by id and file name, with a fixed message. A provider's own error text is never returned |
| `group_id` / `public_workspace_id` | The workspace the receipt is for. The client refuses a receipt for another workspace |

The status is `200` when every document was upgraded and `207` when any could not be. A
refusal is the usual document-route refusal: `403` for a caller who may not manage the
workspace, or whose workspace is locked, upload-disabled or inactive, `404` for an unknown
workspace and `400` for a malformed workspace id or for a request that carries a body or query
parameters.

### Behaviour of the upgrade

- **It writes what the classic upgrade writes**, so both interfaces leave a document in the same
  state: status "Processing complete", progress 100, the page and chunk counters, enhanced
  citations off, classification "None", and an empty title, authors, organization, publication
  date, keywords and abstract. That means an upgraded document shows its file name until its
  metadata is edited or extracted again.
- **One request upgrades at most 500 documents.** If more remain, the receipt says so and the
  list keeps the notice, so the person chooses **Update now** again.
- **It authorizes as a metadata edit**, and does so again before every document. A role or
  status change part-way through stops the update with the usual refusal rather than finishing
  it. Documents already written stay updated, and the explorer reads the list again to show what
  remains.
- **One bad document never blocks the rest.** A document that fails is named in `errors` and the
  others are still upgraded.
- **Cached searches over the workspace's documents are invalidated** when any document was
  upgraded.

## File structure

| File | Role |
|---|---|
| `application/single_app/functions_legacy_document_upgrade.py` | The scope-explicit upgrade and its receipt |
| `application/single_app/route_backend_group_documents.py` | `POST /api/groups/<group_id>/documents/upgrade_legacy` |
| `application/single_app/route_backend_public_document_management.py` | `POST /api/public-workspaces/<workspace_id>/documents/upgrade_legacy` |
| `application/v2_ui/src/lib/documentLegacyUpgrade.ts` | The flag, the route per scope, the receipt check, the notice's words |
| `application/v2_ui/src/lib/documentOperations.ts` | `canUpgradeLegacy` and `upgradeLegacy` on the scope-aware operations |
| `application/v2_ui/src/components/documents/LegacyUpgradeBanner.tsx` | The notice |
| `application/v2_ui/src/components/documents/DocumentExplorer.tsx` | Reads the flag, runs the update, holds the explorer still, restores focus |
| `application/v2_ui/src/pages/workspace/DocumentsSection.tsx` | The group and public Documents sections, which no longer carry a classic button |

## Testing and validation

| Test | Covers |
|---|---|
| `functional_tests/test_legacy_document_upgrade_scope.py` | The upgrade module: one scope, per-document authorization, per-document failures, the limit, and parity with the classic fields |
| `functional_tests/test_group_legacy_document_upgrade_route.py` | The group route: roles, status, no use of the saved active group, malformed requests, partial results |
| `functional_tests/test_public_legacy_document_upgrade_route.py` | The same for the public route |
| `functional_tests/test_v2_legacy_document_upgrade.py` | Route names and flags derived from the route source, role gating, the explorer wiring and the removal of "Classic tools" |
| `functional_tests/test_v2_legacy_document_upgrade_logic.ts` | The client's flag, paths, receipt checks and the notice's text, run in Node |
| `functional_tests/test_group_document_fixture_parity.py`, `test_public_document_fixture_parity.py` | The browser fixtures' list flag and upgrade receipts equal the real routes' |
| `ui_tests/test_v2_legacy_document_upgrade.py` | The notice for all three scopes in the real SPA: shown and hidden, success, partial, limited and failed updates, the held-still explorer, Maybe later, focus, desktop and 390 px, light and dark |

Run them with:

```powershell
python -m pytest functional_tests\test_legacy_document_upgrade_scope.py functional_tests\test_group_legacy_document_upgrade_route.py functional_tests\test_public_legacy_document_upgrade_route.py functional_tests\test_v2_legacy_document_upgrade.py -q -p no:cacheprovider
cd .\application\v2_ui; npm run typecheck; npx vite build; cd ..\..
$env:PYTHONPATH = "$PWD;$PWD\ui_tests;$PWD\ui_tests\fixtures"
python -m pytest ui_tests\test_v2_legacy_document_upgrade.py -q -p no:cacheprovider
```

The route and module tests run the real routes against the document harnesses' in-memory
stores. The owner-scoped Cosmos DB query is checked there, not against a live account.

## Known limitations

- **The upgrade is not undone.** It rewrites the document's metadata fields to the classic
  defaults, so a title or abstract the document had is not kept.
- **Large workspaces need more than one run.** The 500-document limit per request keeps a request
  short; the notice stays until the list says nothing is old.
- **The classic upgrade function still has its public-workspace defect.** It is left alone
  because nothing in V2 calls it and the classic interface never offered a public update.
- **The personal route reports only a sentence.** It does not say how many documents it
  upgraded or whether any remain, so the explorer relies on the list it reads next.
