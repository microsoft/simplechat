# V2 Documents Explorer

## Overview

The personal workspace **Documents** section in the V2 interface is a file-explorer-style
surface: a command bar, a navigation rail, a content pane with two views, a details pane and a
status bar. It replaces a single flat list that offered upload, delete and one tag filter.

A companion **Tags** section owns the tag vocabulary itself — renaming, recolouring, merging
and deleting — so that browsing by tag and administering tags are no longer competing for the
same toolbar.

**Implemented in version:** `0.261.048`
**Dependencies**

| Requirement | Why |
|---|---|
| `enable_user_workspace` | Gates every personal document route |
| `enable_document_classification` *(optional)* | Adds the Classification rail group, column and metadata field |
| `enable_extract_meta_data` *(optional)* | Adds the Extract action |
| `enable_file_sharing` *(optional)* | Adds the Share action and the sharing details |
| `max_file_size_mb` | Enforced client-side before an upload is attempted |

## Why it was rebuilt

The V2 documents page called four endpoints. The backend already supported far more, and the
classic interface had accumulated four view modes, a multi-select *mode*, seven filter
controls and five modals in one band above the list.

| Capability | Backend | Classic UI | V2 before | V2 now |
|---|---|---|---|---|
| Server-side pagination | yes | yes | no (`page_size=1000`) | yes |
| Server-side search | yes | yes | no (client filter) | yes |
| Server-side sorting | yes | 3 fields | no | 8 fields |
| Tag filtering | yes | yes | one tag | many, combined with AND |
| Bulk tag | yes | yes | no | yes, including drag-to-tag |
| Bulk delete | **no** | no (looped) | no | yes (new endpoint) |
| Download | yes | yes | no | single and ZIP |
| Metadata editing | yes | yes | no | yes |
| Re-extraction | yes | yes | no | yes |
| Sharing | yes | yes | no | yes |

## Architecture

### Layout

```
┌───────────────────────────────────────────────────────────────────────────────┐
│ Upload │ Download  Tag  Chat  Extract  Delete │ search  columns  ▤▦  details  │
├─────────────┬─────────────────────────────────────────────┬───────────────────┤
│ PLACES      │  Tags: alpha ✕   Search: "budget" ✕   Clear │                   │
│ SAVED VIEWS │ ─────────────────────────────────────────── │   Details pane    │
│ TAGS        │  Name · Tags · Status · Modified · Size     │   (0 / 1 / N)     │
│ CLASSIF.    │                                             │                   │
├─────────────┴─────────────────────────────────────────────┴───────────────────┤
│ 1–50 of 142 · 3 selected                    ‹ 1 … 9 10 11 … 20 ›   50 / page  │
└───────────────────────────────────────────────────────────────────────────────┘
```

### File structure

```
application/v2_ui/src/
  lib/
    documentExplorer.ts          Query state, selection algebra, formatting, facets
    documentSavedViews.ts        Saved view shape, validation, serialisation
  components/documents/
    DocumentExplorer.tsx         The shell; owns query, selection and loading
    ExplorerRail.tsx             Places, saved views, tags, classification; drop target
    ExplorerCommandBar.tsx       Command bar, filter chips, status bar
    DocumentTable.tsx            Details view and its column definitions
    DocumentTiles.tsx            Tiles view
    DocumentDetailsPane.tsx      Details pane, three selection states
    DocumentDialogs.tsx          Tag, metadata, delete and share dialogs
    documentPresentation.tsx     File icons, tag chips, status badges
  pages/workspace/
    DocumentsSection.tsx         Thin host
    TagsSection.tsx              Tag vocabulary management
```

`documentExplorer.ts` and `documentSavedViews.ts` are deliberately free of React so their
rules can be executed directly in a test.

### API

Three server changes were made. Everything else already existed.

#### `GET /api/documents` — new `place` parameter

| Value | Meaning |
|---|---|
| `all` *(default)* | No narrowing |
| `recent` | Uploaded in the last 30 days |
| `shared` | Owned by someone else and shared with the caller |
| `processing` | Still being indexed |
| `errors` | Processing failed |
| `untagged` | Carries no tag |

These describe the *state* of a document rather than its content, so they cannot be expressed
in the Cosmos query: processing state is derived from free-text `status` and
`percentage_complete`, "untagged" is the absence of a value, and ownership is only meaningful
relative to the caller. The route already materialises and paginates in Python, so the filter
is applied there, before the count.

`sort_by` also accepts more fields. The allow-list moved to `functions_documents.py` as
`ALLOWED_DOCUMENT_SORT_FIELDS`, split into `NUMERIC_DOCUMENT_SORT_FIELDS` and
`TEXT_DOCUMENT_SORT_FIELDS`:

| Field | Compared as |
|---|---|
| `_ts`, `file_size`, `number_of_pages`, `version` | number |
| `file_name`, `title`, `upload_date`, `document_classification` | text |

The split is what makes the sort safe. `sort_documents` previously mapped a missing value to
`""` while leaving a present numeric value an `int`, and Python 3 raises `TypeError` comparing
the two — invisible while the allow-list held only strings, a live crash the moment
`file_size` became sortable.

#### `GET /api/documents/facets`

```json
{ "total": 142, "untagged": 14, "processing": 2, "errors": 1, "recent": 23,
  "shared_with_me": 5, "by_tag": {"alpha": 12}, "by_classification": {"Internal": 30} }
```

Counted over the caller's whole workspace and deliberately **ignoring** the current filters.
These drive the navigation rail, and a rail that re-counted itself against the active filter
would collapse to zeroes as soon as anything in it was selected.

#### `POST /api/documents/bulk-delete`

```json
{ "document_ids": ["..."], "delete_mode": "all_versions",
  "conversation_linked_delete_confirmed": false, "file_sync_delete_action": null }
```

Answers with `deleted`, `errors`, `deleted_count` and `error_count`. It reports per document
rather than failing the batch, because the two delete guards apply individually: one document
uploaded through chat would otherwise block the deletion of everything selected alongside it.
A guarded document returns in `errors` with `needs_confirmation: true` and the same payload
the single delete answers `409` with, so the client can ask about exactly those documents and
resubmit.

Both delete routes now share `_personal_document_delete_guard`, so a guard added to one cannot
become a way around it in the other.

### Settings

Three new keys, whitelisted in `route_backend_users.py` and declared in
`WRITABLE_USER_SETTING_KEYS`:

| Key | Contents |
|---|---|
| `v2DocumentsPrefs` | View mode, visible columns, page size, details pane state, sort |
| `v2DocumentSavedViews` | The saved views pinned in the rail |
| `v2WorkspaceRailCollapsed` | Whether the workspace section rail shows icons only |

Namespaced rather than shared with the classic interface, which stores its own view mode in
`localStorage` under `personalWorkspaceViewPreference` and offers four modes to this
interface's two. `v2WorkspaceRailCollapsed` is likewise separate from `v2RailCollapsed`, which
belongs to the application shell — the two rails sit side by side, and collapsing one to make
room should not collapse the other.

### The Tags section

Registered in `functions_workspace_sections.py` (`WORKSPACE_SECTION_IDS`,
`WORKSPACE_SECTION_GROUPS`) and in the SPA registry. `resolveWorkspaceSections` fails closed,
so a section the server does not report is treated as unavailable — registering it in only one
place produces a section that never renders.

The classic interface is unaffected: `route_frontend_workspace.py` reads only
`file_sync_enabled` and `governance` from the availability payload and never iterates
`sections`.

## Usage

### Browsing

The rail replaces the classic interface's folder view modes. Places appear only once they
describe something, so a workspace with nothing in flight carries no permanent "Processing 0".
Clicking a tag filters to it; **Ctrl+click** adds a second tag, combined with AND.

Active filters render as removable chips above the list with a Clear all — a flat, tagged
workspace has no path to put in a breadcrumb, and saying what is currently narrowing the list
is the honest equivalent.

### Selecting

Selection is not a mode. There is no button to press first.

| Gesture | Result |
|---|---|
| Click | Select one |
| Ctrl/Cmd+click | Add or remove one |
| Shift+click | Select the range from the anchor |
| Ctrl+A | Select the page |
| Escape | Clear |
| ↑ / ↓ | Move; Shift extends |
| Double click | Open the details pane |

A range follows the order currently *displayed*, so re-sorting the table changes which
documents lie between the anchor and the click — matching what is on screen. Selecting after
paging prunes ids that are no longer visible, so a bulk action can never reach a document the
user cannot see.

### Views

Two: **Details** (a sortable table) and **Tiles** (cards). The classic interface's `grid` and
`folders-cards` modes are deliberately not carried over; the rail lists tags permanently,
which is what those modes were reaching for.

The Name column shows the **title** on the first line and the **file name** dimmed beneath it,
because a file name is frequently something like `MSA_v2_FINAL(3).docx`. When there is no
title the file name is promoted rather than captioned with "Untitled".

Columns beyond the default five — Classification, Pages, Version — are available from the
column chooser. Only columns the server will actually sort by have clickable headers.

### Tagging

Three routes to the same operation:

1. **Drag** a selection onto a tag in the rail. The confirmation toast carries an **Undo**,
   which is why the gesture needs no confirmation beforehand — confirming would interrupt
   every correct use of it to guard against the rare wrong one.
2. **Tag** in the command bar, which opens the tag dialog. A tag carried by only some of the
   selected documents shows as partial rather than present or absent.
3. The details pane, which adds and removes tags for the current selection.

### Saved views

A named combination of place, search, tags and classification, pinned in the rail. This is the
replacement for folders in a workspace that files by tag — the same idea as Windows saved
searches and macOS smart folders. Sort order and page number are deliberately not saved: they
describe how the list is being read at one moment, and a saved page number would land
somewhere arbitrary later.

Save with **Save view** in the command bar, which appears once anything is narrowing the list.
Right-click a view in the rail to remove it.

### Reclaiming width

The workspace section rail collapses to icons with the control at its top, remembered per
user in `v2WorkspaceRailCollapsed`. Collapsed entries keep their labels as tooltips and as
screen-reader text. This is separate from the application shell's own rail, so the two can be
collapsed independently.

### Searching

The box searches shortly after you stop typing, or immediately on **Enter**. **Escape**
clears it.

The input is bound to what you have typed rather than to the debounced query value. Binding a
controlled input to the debounced value reverts every keystroke until the debounce catches up,
which drops characters when typing at speed.

### Bulk operations and progress

Tagging and deleting are sent in batches of `BULK_BATCH_SIZE` documents, and a determinate
progress bar reports how far through the selection the work is.

This is not cosmetic. Server-side, tagging one document costs a cross-partition query, a
document write, and an update to every one of its search-index chunks; deleting likewise
removes index chunks as well as the record. A single request covering a large selection
therefore runs for a long time, and behind an indeterminate spinner that is indistinguishable
from a hang. Batching makes the progress real and each request short.

The progress task is cleared in a `finally` on every path, so a failed batch reports itself
and the bar comes down rather than staying up forever.

### Re-extraction

The pane states the mode the selection is currently on, marks that option as **(current)**,
and offers the other one as *Switch to …*. Previously it showed Standard and Enhanced as two
equal buttons with nothing indicating which was already in effect, so changing it meant
guessing and then checking.

- Only PDFs and images go through Document Intelligence. For any other file the control is not
  shown, and in a mixed selection the documents it does not apply to are named and left alone.
- A selection spanning both modes reports **Mixed**; one where no mode was ever recorded
  reports **Not recorded**. Those are different situations and are not conflated.
- Enhanced is disabled with a reason when `enable_enhanced_extraction` is off, because the
  reprocess route rejects a request for `layout` outright in that case.

### Deleting

Bulk delete reports per document. When the server refuses one — because it was uploaded
through chat, or is managed by file sync — the dialog stays open, names those documents, gives
the reason, and offers to go ahead anyway.

## Testing and validation

| Test | Covers |
|---|---|
| `functional_tests/test_v2_documents_explorer.py` | Route guards, shared delete guard, settings whitelist, section registration on both sides, V1 non-regression, endpoint coverage, composition, selection model, view modes, search binding, batched progress, the re-extract control, the collapsible rail, no CDN assets |
| `functional_tests/test_v2_documents_explorer_logic.ts` | 67 behavioural checks over the query builder, selection algebra, filter chips, status derivation, formatting, pagination, facets, saved views, batching and extraction-mode summarisation |

The Python test additionally *executes* the new server helpers — `sort_documents`,
`filter_documents_by_place`, `build_personal_document_facets` — by extracting them from source
with `ast`, because `route_backend_documents.py` imports `config`, which builds Azure clients
at import time.

Run them with:

```powershell
python .\functional_tests\test_v2_documents_explorer.py
python .\functional_tests\route_tests\test_route_blueprint_policy_inventory.py
cd .\application\v2_ui; npm run typecheck; npm run build
```

## Known limitations

- **Personal workspace only.** Group and public workspace pages do not exist in the V2
  interface yet. The components take their data as props rather than reading a scope, so the
  same explorer can serve them without a rewrite.
- **Details, not preview.** There is no general document-preview endpoint — enhanced citations
  serve blobs only in citation context — so the right-hand pane presents metadata rather than
  rendering the file.
- **Facet counts are a snapshot.** They are refreshed after any mutation and when processing
  finishes, not continuously.
- **Tags are flat, by design.** A document carries as many as it needs and none of them nest,
  which is what lets one document belong to several groupings at once.
