# Chat document metadata and notification alignment fix

Fixed in version: **0.261.327**

The application version is recorded in `application/single_app/config.py`.

## Issue and root causes

The V2 chat Documents pane could show document GUIDs instead of recognizable
names after an Orchestrate Analyze or Compare answer. Those answers can derive
document references from retained-result lineage rather than search chunks.
Lineage carries the document and workspace identity, but not the title or
filename. Finalization checked current source authorization without copying the
authorized source's readable metadata into the published references.

The drawer then fell back to the document ID, always displayed a generic file
icon, and did not render a distinct filename. Its first-record-wins merge could
also discard complementary metadata supplied by another existing record.

The desktop notification bell had a separate cause: responsive navigation work
added an auto-margin to the collapse arrow while the bell already had one.
The two margins divided the available header space, separating the controls.

## Changes

New orchestration publications copy title, filename and file type from the
already-authorized source manifest before saving the run, assistant message and
conversation used-document list. This reuses the existing authorization read;
there is no extra lookup per document. The last pre-publication authorization
check remains in place. Document identity, citation IDs, page/sheet locations and
strict retained-result descriptors are unchanged. Recovery delivery uses the
same publication path.

`ConversationDrawer.tsx` uses `conversationDocuments.ts` to merge complementary
display metadata from its existing used, legacy and linked document records.
It displays a title, a distinct filename, and the existing document explorer's
file-family icon. Personal sources say **Personal workspace** rather than the
owner's name. Group/public sources use the matching saved workspace name or the
authorized bootstrap catalog. Missing names use a readable type label, not an ID.
Missing document titles and filenames use **Untitled document**.

The desktop bell keeps the only auto-margin in the expanded desktop header.
The collapse button retains its own auto-margin only in mobile navigation.
Collapsed navigation, the mobile header bell and notification behavior remain
unchanged.

### Files

- `application/single_app/functions_orchestration_execution.py`
- `application/single_app/functions_citation_tracking.py`
- `application/v2_ui/src/lib/conversationDocuments.ts` and `types.ts`
- `application/v2_ui/src/components/chat/ConversationDrawer.tsx`
- `application/v2_ui/src/components/documents/documentPresentation.tsx`
- `application/v2_ui/src/components/layout/Sidebar.tsx`

## Scope and compatibility

This is a forward-looking persistence fix. No migration, historical rebuild,
backfill, or drawer-opening metadata lookup was added. Existing saved records
remain unchanged. The presentation can use complementary metadata that is
already present, but does not fetch missing historical data.

Generated files, media, Microsoft 365 items, citation indicators and document
access controls retain their existing behavior. No new routes, settings,
dependencies or externally hosted browser assets are introduced.

## Validation

- `functional_tests/test_orchestration_harness_execution.py` verifies real
  publication and recovery delivery: both search citations and lineage-only
  references retain readable metadata in the message, completion event and
  used-document cache. Source-free answers stay source-free; unavailable sources
  and storage uncertainty retain their existing failure behavior.
- `functional_tests/test_chat_cited_source_tracking.py` and
  `test_orchestration_citation_persistence.py` cover citation identity and
  location preservation.
- `functional_tests/test_v2_conversation_documents.mjs` covers metadata merging,
  stable document counts, filename fallback, matching workspace names and
  nonmutation of input records.
- `ui_tests/test_v2_chat_document_metadata.py` exercises real cards at desktop
  and mobile widths, file-family SVGs, personal/group/public source labels,
  long filenames, literal markup-like text and absence of historical hydration.
- `ui_tests/test_v2_mobile_navigation.py` measures an 8px desktop bell/arrow gap
  across custom branding and preserves collapsed/mobile navigation behavior.
- Existing generated-file drawer and mobile chat layout regressions pass.
- The production TypeScript check and Vite build pass. The build reports the
  existing large-bundle warning.

The initial backend run was blocked by incompatible packages in the machine's
shared Python environment. Publication and SDK-shaped storage regressions passed
using an isolated test environment; application dependency manifests were not
changed.

The final browser batch passed **29 tests**. The offline Cosmos boundary gate
passed **693 tests and 231 subtests**, with **0 review gaps**, using the pinned
Cosmos SDK and compatible Flask/Werkzeug versions:

```powershell
python scripts\check_cosmos_response_boundaries.py --run-contracts
```

Documentation surface coverage passed all **7 checks** and site quality passed
all **6 checks**. Existing dependency deprecation warnings remain.
