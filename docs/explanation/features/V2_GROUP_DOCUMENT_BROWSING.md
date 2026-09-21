# V2 Group Document Browsing

## Overview

Group Documents now uses the same native explorer as My Workspace. Users can
find shared sources, inspect their metadata and accessible revisions, and pass
eligible documents to chat without leaving V2 or accidentally reading the
workspace selected in another tab.

Implemented in version: **0.261.128**, recorded in
`application/single_app/config.py`.

This is the M2A read-only milestone. Group uploads, edits, tag changes,
sharing/approval, deletion, reprocessing, downloads, and saved-view persistence
remain outside this slice. **Classic** provides the existing management path.
Personal document management remains available.

### Dependencies

- The V2 shared workspace shell and selected-group context.
- Existing group membership, lifecycle, sharing, and Content Screening policy.
- [Explicit group document read APIs](GROUP_DOCUMENT_READ_APIS.md).
- Existing React, TypeScript, Vite, and local browser assets.

No new deployment setting, storage container, or browser dependency is required.

## Shared explorer architecture

`documentReadAdapter.ts` supplies the read boundary used by `DocumentExplorer`.
The personal reader retains the existing personal endpoints; the group reader
names one `group_id` on list, tag, facet, detail/progress, and version requests.
Neither the active-group preference nor personal ownership fields are used to
choose a group resource.

The explorer is keyed by authenticated viewer and scope. Switching groups
resets query, inspection, and selection state and cancels or ignores earlier
reads. Detail and polling revisions prevent a slower response from overwriting
newer metadata. Fresh restricted projections replace prior records rather than
merging them with extracted text that is no longer available.

The group page uses the shell's full-width work-area layout. The explorer shares
the document table/tiles, command bar, filters, details, and status/paging
controls with the personal page. Presentation preferences are deliberately
shared. Personal saved views are not displayed or stored as group views.

### Reads and capabilities

| Surface | Group request |
| --- | --- |
| List and queries | `/api/group_documents?group_id=G` |
| Whole-workspace counts | `/api/group_documents/facets?group_id=G` |
| Tag vocabulary/counts | `/api/group_documents/tags?group_id=G` |
| Metadata and progress | `/api/group_documents/D?group_id=G` |
| Accessible revisions | `/api/group_documents/D/versions?group_id=G` |

The adapter validates list/detail/version scope and response shapes. Controls
follow advertised query capabilities; unsupported sorts, places, or facets are
not presented as functioning features.

Filtering, sorting, total counts, and facets come from the complete authorized
current-revision set on the server. The browser does not filter a page and
pretend it has searched the entire workspace. See the backend API document for
the source-authoritative query strategy and performance limitations.

### Ownership, sharing, and screening

The group reader uses `group_id` as source ownership and
`shared_group_active_id` as the recipient context for incoming shares.
Selection requires an owned document with `shared_approval_status=owner`, or an
explicitly approved incoming share for the displayed group. Missing or
unapproved relationships do not become permissions.

Pending and held documents can be inspected through their safe metadata/status
projection, but cannot be selected for chat. The same eligibility rule applies
to checkboxes, select-all, range selection, keyboard navigation, detail
commands, and chat handoff. Restricted rows do not regain old titles or
abstracts from cached detail/poll responses.

Read-only group mode gates mutations throughout the explorer: toolbar and row
commands, detail controls, tag removal/drop, keyboard shortcuts, file drop,
dialogs, and empty-state actions. It never substitutes personal mutation APIs
for unimplemented group operations. Group screening-policy controls, content
previews, and downloads are not offered by this slice.

## Using the native group Documents section

1. Open Group Workspaces and select the intended group.
2. Choose Documents in the shared navigation.
3. Search by name/title, choose a standing view, or filter by tags and
   classification. Sort and page through the server results.
4. Select or inspect a document to review available metadata, ownership/share
   context, status, and Content Screening information.
5. Use **Version history** to load the revisions the selected group may see.
6. Select eligible sources and choose **Chat**, or use **Classic** for document
   management.

On compact screens, **Filters** and the details toggle open the existing modal
surfaces instead of squeezing three panes into the narrow content area. The
application and workspace navigation remain unchanged.

### Chat handoff

The URL and context chips retain the exact selected group, document IDs, and
active filter tags. Before the composer adopts group context, it revalidates
the group's current view/chat availability and the selected documents'
relationships and screening state. Stale router-state records cannot bypass
these reads.

This is not a new group-only retrieval mode. The existing chat request mapping
(`chat_type=user`, `doc_scope=all`, and the established active-group union)
remains unchanged. Existing conversation scope locks are not cleared or
retargeted; incompatible requests retain the conversation and show its error.

## File structure

| File | Responsibility |
| --- | --- |
| `lib/documentReadAdapter.ts` | Typed personal/group readers and selection eligibility. |
| `components/documents/DocumentExplorer.tsx` | Scoped state, queries, polling, read-only commands, and responsive surfaces. |
| `components/documents/DocumentDetailsPane.tsx` | Safe metadata, relationship display, refresh, and version history. |
| `components/documents/DocumentTable.tsx`, `DocumentTiles.tsx` | Shared eligibility-aware selection and source display. |
| `components/documents/ExplorerCommandBar.tsx`, `ExplorerRail.tsx` | Capability-aware queries and management gates. |
| `pages/workspace/DocumentsSection.tsx` | Personal and group hosts for the shared explorer. |
| `pages/GroupWorkspacePage.tsx` | Native full-width group Documents integration. |
| `lib/chatContextHandoff.ts`, `components/chat/Composer.tsx` | Explicit, freshly authorized group handoff. |

Frontend paths are relative to `application/v2_ui/src/`.

## Validation and limitations

`functional_tests/test_v2_group_documents_logic.mjs` exercises real adapter,
selection, and handoff code, including all 96 supported place/sort/direction
combinations. `ui_tests/test_v2_group_documents.py` and the shared-shell suite
run the production SPA with closed HTTP fixtures, covering queries, details,
versions, delayed responses, polling, restricted records, mutation gates,
scope locks, and desktop/mobile light/dark layouts.

`ui_tests/test_v2_personal_document_scope.py` independently protects personal
reads, filtering, action availability, and metadata writes while an unrelated
group is active. Backend behavioral and route-policy tests are documented in
the API feature page. Polling tests install the clock before application timers
are created and wait for the initial detail response before advancing a poll.

No live Azure deployment, live model execution, or large-workspace latency
benchmark is claimed. Group management operations, downloads/previews,
group-specific saved-view persistence, and public workspace migration remain
later milestones.
