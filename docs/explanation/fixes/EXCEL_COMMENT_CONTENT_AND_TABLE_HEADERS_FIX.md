# Excel Comment Content and Table Headers Fix

Fixed in version: **0.261.408**.
Application version is maintained in `application/single_app/config.py`.

## Issue and root cause

The Excel extractor could read comment text while the native chat handoff sent
only counts and a few shortened relevance excerpts. A request to list every
comment could therefore report that comment contents were unavailable even
though they had been extracted.

Threaded comments' legacy compatibility copies were also classified as genuine
notes. One investigated specimen contained three threads and one reply plus
three compatibility copies, which appeared as seven independent comments.

Preview/schema readers assumed the first worksheet row was its single header.
That misrepresented title rows and multiple tables. The V2 spreadsheet popup
also reused the image-specific extraction label.

## Changes and impact

Native evidence now prioritizes requested structured records and saved cell
context instead of depending on relevance hits. Compatibility correlation keeps
genuine notes and distinguishes roots, replies, and raw representations.
Long/native inventories remain available through revision-bound pages.
Reviewed publication preserves a native-evidence marker on every search
fragment and caps native search previews at one million characters, including
their markers. Complete inventories remain separately paged; sanitized
publication never republishes original native supplements.

The shared streaming reader discovers named tables and ordinary regions, with
independent ranges and header locations. The preview and analytical selectors
use those boundaries rather than a worksheet-wide first-row header.
Released workbook schemas are generated from the active published bytes with
the same table-aware reader, including sanitized derivatives.

The V2 popup labels workbook evidence accurately, identifies the selected sheet
and table/range, shows physical row coordinates, and pages records. Switching
between source sheets with identical values can legitimately leave the visible
values unchanged; this is not itself a switching defect.

Primary components are `excel_workbook_reader.py`,
`functions_excel_accessibility.py`, `functions_excel_inventory.py`,
`functions_search_service.py`, `functions_documents.py`, the chat/tabular
adapters, and `EnhancedCitationViewer.tsx`.

## Before and after

| Before | After |
| --- | --- |
| Counts could reach the answer without comment text. | Requested comment records and available saved values are supplied together. |
| Compatibility notes inflated user-facing counts. | Genuine notes, threads, replies, and compatibility copies are distinguished. |
| A title could become the header for every worksheet table. | Each table/range has its own declared or explicitly inferred headers. |
| Large native records were lost at preview limits. | Parent previews are bounded; complete records have source-bound continuations. |
| Spreadsheet evidence was labelled as an image. | Workbook/CSV evidence has the appropriate label and stays tied to its citation. |

## Validation

Regression coverage uses real packages and inspects actual record contents and
final handoff text, including no relevance hits, blank cells, missing caches,
late rows, multiple tables, and unchanged original bytes. Private-store tests
cover restart/paging, revocation, source-bound cursors, failures, and cleanup.
UI tests exercise different and identical sheets, five tables, the 50,000th
record, error recovery, keyboard navigation, and desktop/mobile layout.

See [Scalable Excel Native Inspection](../features/EXCEL_NATIVE_INSPECTION.md)
for the storage contract, test suites, and saved-state limitations.
