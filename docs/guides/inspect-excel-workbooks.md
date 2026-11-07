---
layout: page
title: "Inspect Excel data, comments, and structure"
description: "Read workbook feedback and metadata without confusing them with saved values or table calculations."
section: "Guides"
audience: user
version: "0.261.417"
---

Implemented in version: **0.261.408**, tracked in
`application/single_app/config.py`.

## Ask about the file and its data separately

Select the intended workspace workbook. To review feedback, ask:

> List the genuine cell notes and threaded comments. Include worksheet/cell,
> saved value, author, text, replies, and available timestamps/status.
> Separate requested changes from the workbook's actual values.

To compute business results, name the worksheet and table or range:

> Describe the tables on Budget, then calculate total Amount for the Costs
> table. Do not combine other tables on that worksheet.

An Excel cell can contain a saved formula without a cached result. SimpleChat
can report the formula, but it does not calculate Excel formulas or treat that
missing cache as zero. Recalculate/save in Excel when those results are needed.

## Choose the actual table and headers

A worksheet may contain title rows, five separate tables, or repeated printed
headers. Named Excel tables provide saved boundaries. Ordinary blocks have
detected boundaries and labelled inferred headers. When a header is ambiguous,
clarify the actual worksheet header row or that the range has no header.

A schema preview is a sample. Use tabular analysis for exact counts, filters,
totals, and grouped results over all intended records.

## Inspect a citation

Fixed/Implemented in version: **0.261.417**, recorded in
`application/single_app/config.py`.

A native note or threaded-comment citation opens the exact retained reviewer
text first. Its evidence view identifies the worksheet/cell, author, available
timestamp, reply relationship, resolution status, and saved cell value.
Reviewer suggestions are not worksheet values; unavailable fields remain
unavailable and formulas are not recalculated.

Use **Open workbook preview (separate from annotation evidence)** to inspect
the workbook independently. A table preview is not proof of the cited comment.
Replies and separate comments at the same cell keep distinct retained identities.
Inventory-coverage references describe inspected records, including zero comments;
they do not invent a worksheet cell or reviewer quotation.

Opening native evidence requires access to both the original conversation/run
and the exact workbook version/revision that was inspected. A changed, held,
deleted, or inaccessible source can make the citation unavailable. Older
references work only when retained metadata identifies their exact evidence;
SimpleChat does not choose between same-cell comments or rerun an inventory
to guess what an old answer meant.

Open the workbook citation. The viewer identifies the selected worksheet,
table/range, and header row. Choose another **Table** when several regions are
present. Use **Previous records**, **Next records**, or **Go to record** for
large data. Record positions count data records; the left-hand row labels are
the original worksheet row numbers.

**Cited workbook evidence** remains the passage supporting the answer. Switching
the preview does not rewrite it. Two different sheets may contain identical
values; use the visible worksheet identity and their metadata/comments rather
than assuming identical values mean the tab did not switch.

## Large comment and metadata inventories

An agent with Document Search can use
`get_document_accessibility_report(native_section="comments")` and follow each
`next_cursor` until `has_more` is false. Other sections include tables, objects,
properties, links, validation, and available image-analysis records. Direct cell
inspection accepts a worksheet and bounded A1 range.

Returned pages, shortened parent previews, and explicit long-record fragments
are not exhaustive results. Check coverage and continuations before claiming
every comment or metadata record has been read.

## Existing files and limitations

Re-uploading is usually unnecessary when the active workbook is already stored.
Native inspection can generate new details from that retained original.
Configured image analysis may need reprocessing; ordinary metadata reads do not
silently run new vision analysis. If neither source bytes nor the needed
inventory remain, re-upload the file through the normal authorized workflow.

Held/revoked sources require the appropriate access or review resolution.
Inspection never runs macros, ActiveX, embedded programs, or external refreshes,
and saved formatting is not a reproduction of Excel's rendered appearance.
Legacy `.xls` has narrower native coverage.
