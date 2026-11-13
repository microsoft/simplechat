---
layout: page
title: "Tabular Processing"
description: "Full guide for the Tabular Processing SimpleChat action."
section: "Reference"
audience: user
---

<!-- action-slug: tabular-processing -->

{% include media.html src="reference/actions-tabular-processing-configuration.png" alt="Tabular Processing availability and related document settings." title="Tabular Processing configuration" capture="Capture the relevant citation/document processing settings or a chat with an uploaded CSV/XLSX ready for tabular analysis." %}

## What this action does

Tabular Processing analyzes CSV, XLSX, XLS, and XLSM files stored in workspace or chat-upload blob containers. It can list files, describe schemas and previews, look up values, return distinct values, count rows, aggregate columns, filter/search rows, run pandas query expressions, relate values across sheets, and group by columns or datetime components.

{% include media.html id="slide-tabular-analysis" %}

The slide's rows and chart are illustrative. Inspect the intended sheet and
columns, then compute over the authorized underlying records; a schema
preview or planning sample is not a complete dataset. Check reported coverage
and limits before treating a total or export as complete.

## Why and when to use it

Use Tabular Processing when users ask exact questions about spreadsheets or CSV files: counts, filters, group-bys, lookups, joins between sheets, or chart-ready aggregates. Do not use it for relational databases; use SQL Query, Databricks, or Snowflake. Do not use normal document search for questions that require row-exact computation; search is better for narrative text.

## Before you start

- CSV, XLSX, XLS, or XLSM files uploaded to personal, group, public, or chat document storage.
- Workspace/document access for the current user.
- Sufficient processing limits for the file size; Citation settings include tabular preview controls.
- `enable_tabular_processing_plugin` is derived in `functions_settings.py`; admin UI notes say the action is automatically enabled whenever Enhanced Citations is enabled.

## Configure the action

1. No dedicated Tabular Processing action panel was confirmed in `_plugin_modal.html`.
2. Enable the document processing/citation features that make tabular files available for detailed analysis.
3. Upload the CSV or workbook through Chat or Workspace so it is stored in supported containers.
4. Ask the agent to describe the file first when sheet names or columns are unclear.
5. For large outputs, ask for aggregates, filters, top-N results, or generated exports instead of all rows.

## Example prompts

- "In sales.xlsx, group revenue by region and quarter and show the top five regions."
- "Find rows where RenewalDate is in the next 30 days and Status is not Closed."
- "Compare the Account sheet to the Tickets sheet and count open tickets by account owner."

## Tables, ranges, and saved formulas

Implemented in version: **0.261.408** (`application/single_app/config.py`).
Describe a workbook before choosing a table when a worksheet contains several
regions. Named tables retain their saved definitions; ordinary blocks expose
their detected ranges and labelled inferred headers. A title row is not a
header for every table below it.

Use the analytical operation's table/range/header selectors for the intended
dataset: `table_id` selects a discovered ID or named table; `cell_range`
selects an explicit Excel range and requires `header_row`. Specify the actual
worksheet header row when it is ambiguous; zero means no header. Related-source
operations expose the equivalent `source_` and `target_` selectors. An explicit
`table_id="all"` combines compatible same-schema tables, not unrelated schemas.
Do not silently combine different schemas. Explicit all-table
native jobs retain each selected table's identity through batching and replay.

Physical worksheet/table/row provenance accompanies Excel row results.
Version-pinned exports preserve the selected ranges and headers instead of
reinterpreting the entire sheet on continuation. Large outputs still use the
existing bounded paging and durable export path.

Queued workbook computations with legacy v1 worksheet-header descriptors must
be started again so the intended tables/headers can be pinned explicitly.
Previously completed export files are not rewritten. CSV descriptor compatibility
is retained.

Formula text is inspectable, but analytical values require saved formula
caches. Missing results must not become zero. Recalculate/save the workbook in
Excel if those values are required; SimpleChat does not execute workbook
formulas, macros, or external refreshes.

For reviewer feedback and workbook properties, use
[Document Search](../document-search/) rather than interpreting comments as data.
See [Inspect Excel workbooks]({{ '/guides/inspect-excel-workbooks/' | relative_url }}).

## Orchestrate calculations across files

Implemented in version: **0.261.437** (`application/single_app/config.py`).

Orchestrate also offers a typed, deterministic cross-file operation through
`tabular_analyze`. Select the intended files and specify the relationship and
calculation, such as matching orders to a price list by product code. The plan
reads complete authorized tables and retains computed records, per-row lineage
and coverage before explaining or exporting the result.

This is distinct from the direct Tabular Processing action and from
`tabular_merge`, which appends rows rather than matching keys. The new
`native_operation="relate"` uses explicit join cardinality, date-effective lookup
boundaries and precise decimal rules. Ambiguous matches, missing formula caches
and exceeded bounds fail explicitly; no preview is promoted to a complete table.
Native accessibility/layout inspection remains a separate compatible capability.

From **0.261.439**, the relational `datasets[].columns` selector explicitly means
the complete ordered source header, not a field projection. A known mismatch is
corrected during planning; the actual source is still checked at execution.
Use `project`/`output` to select result fields. Full numerical work still requires
complete native records, while semantic document/comment review keeps its own
compatible readers.

See [Calculate across selected files]({{ '/guides/calculate-across-files/' | relative_url }})
for source selection, relationship rules, inspection coexistence and output limits.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| The agent gives a narrative answer instead of computed rows | The prompt did not make the spreadsheet target clear. | Name the file and ask for counts, filters, or aggregates explicitly. |
| A workbook sheet is misread | The default sheet is not the intended sheet. | Include the sheet name in the prompt. |
| Output is too large | The requested rows exceed safe response limits. | Ask for top N, filters, grouped results, or an export artifact. |

## Related

- [SQL Query](../sql-query/)
- [Chart](../chart/)
- [Citation settings]({{ '/admin/chat/' | relative_url }})
