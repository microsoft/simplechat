# Scalable Excel Native Inspection

Implemented in version: **0.261.407**.
Related application version: `application/single_app/config.py`.

## Overview

Excel inspection separates the workbook's saved data, reviewer feedback, and
document structure. A comment requesting a different value does not change the
saved cell value. A worksheet can contain several independent tables; its first
row is not automatically every table's header.

The implementation uses the existing Open XML, openpyxl, xlrd, private artifact
storage, Document Search, and Tabular Processing dependencies. It introduces no
new cloud service.

## Saved content and structure

Modern `.xlsx` and `.xlsm` packages expose saved cell values and types, formula
text and available caches, genuine legacy notes, threaded messages and replies,
core/extended/custom properties, defined names, table definitions, hyperlinks,
validation expressions, layout, print information, and readable drawing/chart
text and caches. Drawing and comment locations retain worksheet/cell anchors.

Threaded comments can have legacy compatibility representations. An identifiable
same-cell compatibility copy is not counted as another genuine note. Counts
distinguish legacy notes, thread roots, replies, and raw compatibility records.
Missing author/date/resolution fields remain unknown. A blank cell, zero, false,
and a formula without a saved result are different states.

Images use the existing Office embedded-image analysis setting, configured
engine, size limits, and per-document cap during ingestion/reprocessing.
Generated image descriptions are separate from saved native alternative text.
Missing analysis does not prove that the workbook contains no pictures.

## Tables and scale

Named Excel table definitions provide authoritative ranges, columns, and
header/totals information. Ordinary occupied blocks are detected separately,
including horizontally or vertically separated regions, title rows, and
repeated headers. Inferred headers are labelled as inferred; ambiguous headers
require an explicit selection rather than a silent first-row assumption.

Streaming worksheet reads support large workbooks without copying all rows into
metadata. Functional coverage includes 50,000- and 100,000-row workbooks, late-row
reads, and five independent named or ordinary tables on one worksheet. These
are correctness fixtures, not a capacity or performance guarantee for every file.

Analytical operations use the selected table/range and preserve physical source
locations. Counts, filters, and aggregates must come from the underlying records,
not the displayed preview. CSV and ordinary single-table inputs retain their
existing analysis path.

## Storage, access, and lifecycle

The original retained workbook remains authoritative. Its table dataset is
identified by the source revision/hash, worksheet, range, headers, and columns;
worksheet rows are not placed in a large Cosmos metadata object.

Parent Excel metadata remains bounded to 500,000 serialized bytes. Complete
native inventories use immutable, revision-bound pages in the existing private
artifact store, with the ready manifest written last. Long text has explicit
continuations rather than permanent loss at a parent-preview limit. Existing
durable tabular machinery handles large computed outputs.

Every read, cached read, and continuation retains current source authorization
and revision checks. Private artifact references are not public document fields.
Metadata from an original file cannot be presented as the native metadata of a
different sanitized active representation. Revision cleanup removes its derived
private artifacts without deleting another document's artifacts.

## Using existing files

Existing stored comment records can be used without uploading the file again.
When the active original is retained, native inspection can generate the richer
inventory on demand. A retained current inventory can also be read without
downloading the workbook again.

Image-analysis enrichment follows ingestion/reprocessing and its configured
cloud engine; an ordinary native metadata read does not silently run new vision
analysis. A re-upload is necessary only when required source bytes/inventories
are unavailable. A held or inaccessible document requires authorized resolution,
not re-uploading to bypass its policy.

No automatic bulk reprocessing is started by this feature.

## APIs and user workflow

`Document Search.get_document_accessibility_report` preserves its
`accessibility`, `style`, and `issues` sections and adds bounded Excel native
section selection, continuation, and direct saved-cell range reads. Follow
`excel_inspection.page.next_cursor` while `has_more` is true when every record is
required. Explicit JSON record fragments must be continued before treating them
as a complete record.

The V2 citation viewer has worksheet tabs, table selection, record paging, and a
record jump control. Its row headers show physical worksheet row numbers.
**Cited workbook evidence** remains the passage originally cited, independent
of the table currently previewed. Numeric native evidence segments are not
physical Excel print pages.

See the [workbook inspection guide](../../guides/inspect-excel-workbooks.md) and
the [Document Search reference](../../reference/actions/document-search.md).

## Validation and limitations

Coverage includes real OOXML packages, canonical comment counts and contents,
saved/blank/uncached cell distinctions, final chat evidence, private-store
paging and authorization, table-aware previews, image anchors, and styled
desktop/mobile Playwright interaction.

Relevant suites are `functional_tests/test_excel_*`,
`functional_tests/test_document_accessibility_report_action.py`, the tabular
analysis/replay suites, and `ui_tests/test_v2_excel_citation_inspection.py`.

The investigated specimen's native model evidence contained the three threads
and one reply in 4,125 UTF-8 bytes; its metadata occupied 15,914 serialized bytes
and its original SHA-256 remained unchanged. A synthetic 50,000-row,
12-column worksheet expanded to 22,995,689 XML bytes, above the old 16 MiB
materialized-part ceiling. Its structural manifest occupied 1,746 bytes and a
reader-only CPython `tracemalloc` probe reported a 911,165-byte peak while
discovering the table and reading its last record. This measures traced Python
reader allocations, not total process RSS, analytical DataFrames, or a hosting
capacity guarantee.

Inspection never recalculates Excel formulas, executes macros/ActiveX/OLE,
refreshes external links, or claims to reproduce Excel rendering. Conditional
formatting and other saved expressions are evidence, not evaluated appearance.
Legacy `.xls` is best effort for information its BIFF reader exposes. Input,
style-sampling, response-byte, and page limits remain explicit; partial evidence
must not be called an exhaustive whole-workbook result.
