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

