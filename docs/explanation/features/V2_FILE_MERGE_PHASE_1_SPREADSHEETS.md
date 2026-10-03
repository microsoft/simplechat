# V2 File Merge — Phase 1: Same-Structure Spreadsheets

Version: **0.261.218**

Implemented in version: **0.261.218**, recorded in `application/single_app/config.py`.

GitHub issue: [#1619](https://github.com/microsoft/simplechat/issues/1619). Part of
[V2 File Merge](V2_FILE_MERGE.md). [Phase 2](V2_FILE_MERGE_PHASE_2_RECONCILIATION.md)
(0.261.219) builds on this phase to reconcile files whose columns differ.

Dependencies: Chat Orchestration (V2), at least one workspace type, `openpyxl` and
`xlrd` (already in `requirements.txt`).

## Overview

Phase 1 lets a V2 chat merge two or more CSV or Excel files that share the same columns
into one table and deliver it as a CSV or Excel file. The planner chooses the new
`tabular_merge` Reason capability, the user reviews the plan, and code — not a model —
appends the rows.

## Technical specifications

### The capability

| Field | Value |
| --- | --- |
| ID | `tabular_merge` |
| Label | Merge spreadsheets |
| Role | Reason |
| Gate | `document_action_capabilities.merge.enabled` and at least one workspace type |
| Document limit | Merge chat limit, enforced by the plan validator for explicit IDs and by the adapter for bound source sets |
| Inputs | `document_ids` (two or more, in merge order) **or** `inputs.sources` bound to a `source-set-v1`; `doc_scope`; `schema_policy` (`by_name` default, `exact_order`); optional `sheet`; `include_source_column` (default `true`); `source_column_name` (default `Source File`) |
| Outputs | `records` (`records-v1`), `report` (`structured-v1`) |
| Model | None. `tabular_merge` is not in `STEP_TASKS`, so Auto routing binds no model. |
| Cost class | Medium; at most two merge steps per plan |

A plan that names a non-tabular document for a merge is rejected with
`source_kind_invalid` before it runs, and the adapter re-checks that every authorized
source is a `.csv`, `.xlsx`, `.xlsm` or `.xls` tabular document.

### A typical plan

```json
{
  "steps": [
    {
      "step_id": "merge",
      "capability_id": "tabular_merge",
      "arguments": {"document_ids": ["east-doc", "west-doc", "north-doc"]}
    },
    {
      "step_id": "save",
      "capability_id": "render_file",
      "arguments": {
        "file_name": "regional_sales.xlsx",
        "output_format": "xlsx",
        "profile": "exact_tabular_workbook_v1",
        "options": {"sheet_name": "Sales"}
      },
      "inputs": {"source": {"binding": {
        "version": "orchestration-input-binding-v1",
        "step_id": "merge", "output_name": "records", "existing_result": null
      }, "allow_partial": false}},
      "outputs": []
    }
  ]
}
```

When the user describes the files instead of selecting them, a `document_search` step
comes first and the merge binds its `sources` output in place of `document_ids`. The
executor expands that source set into document IDs, applies the Merge chat limit, and
refuses the step if any source's scope or revision changed since the search.

### How files are read

- **CSV**: the encoding is taken from a byte-order mark (UTF-8, UTF-16, UTF-32), or tried
  as strict UTF-8, then Windows-1252, then Latin-1, and recorded in the report. The
  delimiter is the most frequent of comma, semicolon, tab or pipe outside quotes on the
  first nonblank line. Quoted delimiters and line breaks inside quotes are kept. Values
  are copied exactly.
- **XLSX and XLSM**: opened read-only with calculated values and no external links.
  Numbers, booleans, dates and times become canonical text (`3.0` → `3`, `TRUE`, ISO 8601
  dates). Macros are never run.
- **XLS**: read with `xlrd`, with dates converted using the workbook's date system and
  error cells kept as their Excel error text.
- **Sheets**: a named `sheet` must exist in every workbook (matched exactly, then
  ignoring case); otherwise each workbook's first visible sheet is read.

### How rows are combined

- The header is the first nonblank row. Trailing blank header cells are dropped; other
  blank headers are named `Column N` with a warning. Duplicate names in one file stop
  the merge.
- Headers match after Unicode normalization, collapsing whitespace and ignoring case.
  The first file decides the output order and spelling. `exact_order` also requires the
  same order.
- If any file differs, every remaining header is still read so the report lists every
  mismatch, and nothing is merged.
- Completely blank rows are skipped. Short rows are padded with blanks. A row with extra
  nonblank values stops the merge.
- Rows are written to a bounded temporary file during the single read, so the exact row
  count is known before the retained result is saved. Small merges stay in memory.

### Failure messages

Engine errors map to fixed, application-owned messages. User file names and header text
never appear in them.

| Code | Raised when |
| --- | --- |
| `merge_schema_mismatch` | Files do not share the same columns (or order, with `exact_order`). |
| `merge_columns_invalid` | Duplicate or overly long headers, no header row, or too many columns. |
| `merge_rows_invalid` | A row has more values than headers, or a value exceeds 32,767 characters. |
| `merge_source_unreadable` | A file is damaged, password-protected, or not really CSV or Excel. |
| `merge_sheet_not_found` | The requested sheet is missing from a workbook. |
| `merge_sources_invalid` | Fewer than two files, duplicates, or a non-spreadsheet. |
| `merge_limit_exceeded` | More files or rows than the Merge chat limits, or an oversized file. |

### Exact-schema exports

The planner cannot name the columns of a table it has not seen, so the
`render_file` step uses `exact_tabular_records_v1` (CSV) or `exact_tabular_workbook_v1`
(XLSX). Both export every retained column in retained order; XLSX takes an optional
`sheet_name`, defaulting to `Sheet1`. See the
[Generated File Export Framework](GENERATED_FILE_EXPORT_FRAMEWORK.md).

### Configuration

| Setting | Default | Notes |
| --- | --- | --- |
| Enable Merge | On | `document_action_capabilities.merge.enabled` |
| Merge: Chat Document Limit | 10 | `merge.chat_max_documents`, 2–300 |
| Merge: Chat Row Limit | 250,000 | `merge.chat_max_rows`, 1,000–1,000,000 |
| Merge spreadsheets capability | Selected | `chat_orchestration_enabled_capabilities`; an empty list allows it |

Workflow limits are configurable now and take effect with Phase 3.

## Usage

1. Open a V2 chat with **Orchestrate** on and select the files.
2. Ask, for example, "Combine these CSVs into one CSV."
3. Review the **Merge spreadsheets** step and the planned file, then run it.

See [Merge files in chat](../../guides/merge-files.md).

## Testing and validation

```powershell
$env:PYTHONPATH = "$PWD\application\single_app;$PWD\functional_tests"
python -m pytest functional_tests/test_tabular_merge_engine.py functional_tests/test_orchestration_tabular_merge_capability.py -q
python -m pytest functional_tests/test_v2_admin_actions_parity.py functional_tests/test_admin_settings_pane_variable_scope.py -q
```

The planner goldens (`test_orchestration_workflow_*_off_golden.py`) were regenerated for
this change. Their diff adds only the `tabular_merge` descriptor, the new export profiles
and recipe, and one planner sentence about merging.

## Known limitations

- Columns must match; reconciliation arrives in Phase 2.
- Merge appends rows and never joins on a key column.
- Values are text. Excel formulas contribute their last calculated values.
- Large or recurring merges belong in workflows, which arrive in Phase 3.
