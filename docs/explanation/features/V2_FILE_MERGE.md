# V2 File Merge

Version: **0.261.218**

Implemented in version: **0.261.218** (Phase 1, same-structure spreadsheets), recorded in
`application/single_app/config.py`.

GitHub issue: [#1619](https://github.com/microsoft/simplechat/issues/1619)

Related: [#1509](https://github.com/microsoft/simplechat/issues/1509) (Gather / Reason /
Render), [#1071](https://github.com/microsoft/simplechat/issues/1071) (generated file exports).

## Overview

File merge combines several files into one. People receive the same report from many
places — one export per region, month or team — and need a single file. Before this
feature SimpleChat could not do it: native tabular analysis accepts exactly one source,
the tabular stack had no append operation, and asking a model to "write a combined CSV"
is slow, costly and can silently drop or alter rows.

Merge is delivered in phases. Spreadsheets come first because they are the most common
request and the easiest to verify exactly; documents and decks follow.

| Phase | Scope | Status |
| --- | --- | --- |
| 1 | Same-structure CSV and Excel merge in V2 chat (`tabular_merge`), Merge limits, exact-schema CSV/XLSX exports | Implemented in **0.261.218** — see [Phase 1](V2_FILE_MERGE_PHASE_1_SPREADSHEETS.md) |
| 2 | Reconciling different structures: column inspection, union and mapped policies, sheet modes, duplicate removal, AI-suggested column mapping | Planned |
| 3 | Large and recurring merges (100+ files) as V2 workflow tasks | Planned |
| 4 | Document assembly foundation, PDF merge, and workbooks with one tab per file | Planned |
| 5 | Word merge, keeping each document's styles or the first document's | Planned |
| 6 | PowerPoint merge, keeping each deck's look or the first deck's theme | Planned |
| 7 | Scale and security hardening, final documentation | Planned |

## Where merge fits in Gather / Reason / Render

Merge is another capability alongside Analyze and Compare. It does not replace any of
them, and it is reached the same way: the user asks in a V2 chat and the orchestrator
plans the work.

| Purpose | Role in a merge |
| --- | --- |
| Gather (optional) | `document_search` finds the files when the user describes them instead of selecting them. Its `sources` output binds into the merge. |
| Reason | `tabular_merge` reads the authorized files and appends their rows with code into one retained table. No model reads or rewrites rows. |
| Render | `render_file` turns the retained table into a CSV or Excel file. |

Merging is Reason, not Render, because it computes a new dataset from sources; Render only
serializes a prepared result. Keeping the merged table as a retained result also lets one
merge feed several files — a CSV and an Excel copy — without merging twice.

Saved memory does not store or merge files. The planner does read saved preferences, so a
saved instruction such as "always give me Excel" shapes merge requests without extra work.

## Technical specifications

### Components

| File | Responsibility |
| --- | --- |
| `functions_tabular_merge.py` | Pure merge engine: CSV, XLSX/XLSM and XLS readers that keep values as text, header normalization, schema policies, provenance column, limits, cancellation, archive guards, and the merge report. No Flask, settings, storage or model imports. |
| `functions_orchestration_merge.py` | Orchestration glue: Merge limits from settings, the authorized-source manifest check, screening-aware byte loaders, persistence of the retained `records` and `report`, and the engine-to-failure-code map. |
| `functions_orchestration_adapters.py` | `run_tabular_merge`, registered in `ADAPTER_REGISTRY`. |
| `functions_orchestration_registry.py` | The `tabular_merge` capability descriptor and the `merge` document-action gate. |
| `functions_orchestration_schema.py` | Plan rules: explicit document IDs or a bound source set, tabular-only sources, the Merge chat limit, and the merge failure messages. |
| `functions_document_actions.py` | The `merge` document action: enablement, file limits and row limits for chat and workflows. |
| `functions_generated_export_registry.py`, `functions_structured_file_renderers.py`, `functions_generated_office_adapters.py` | The `exact_tabular_records_v1` (CSV) and `exact_tabular_workbook_v1` (XLSX) profiles. |

### Result contract

`tabular_merge` retains two outputs under contract `tabular-merge-v1`:

- `records` (`records-v1`): one string column per merged column, in output order, with
  every row. At most 256 columns, because retained record schemas allow 256.
- `report` (`structured-v1`): `tabular-merge-report-v1`, holding the policy, the output
  columns, the provenance column name, totals, one entry per source (file name, format,
  sheet, encoding, delimiter, rows, skipped blank rows, padded short rows, column
  differences, warnings) and limitations.

Coverage counts sources. The result is complete only when every source merged; a merge
either finishes or produces nothing.

### Limits

| Limit | Default | Where |
| --- | --- | --- |
| Files per chat merge | 10 (2–300) | `document_action_capabilities.merge.chat_max_documents` |
| Files per workflow merge | 100 (2–1000) | `document_action_capabilities.merge.workflow_max_documents` |
| Rows per chat merge | 250,000 (1,000–1,000,000) | `document_action_capabilities.merge.chat_max_rows` |
| Rows per workflow merge | 1,000,000 (1,000–1,000,000) | `document_action_capabilities.merge.workflow_max_rows` |
| Bytes per source file | 100 MB | Engine constant |
| Columns | 256 | Retained record schema limit |
| Header name | 256 UTF-8 bytes | Retained column name limit |
| Cell | 32,767 characters | Excel's cell limit |
| Workbook expansion | 512 MB uncompressed, 10,000 parts | Engine guard |

Rendering keeps its own limits: CSV exports hold at most 1,000,000 records, and XLSX at
most 1,048,575 rows, 5,000,000 cells and 32 MiB. CSV suits the largest merges.

### Security

- Every source is authorized again when the run starts and when its bytes are read, through
  `content_screening.access.read_available_document_bytes`, which enforces document
  access, screening holds and the source revision the plan approved.
- Workbooks are opened read-only with external links disabled; `defusedxml` protects XML
  parsing. Encrypted workbooks are refused, and archive size is checked before parsing.
- Values stay text and are never evaluated. CSV output neutralizes formula-like cells;
  XLSX output writes them as literal text.
- Failure messages are application-owned text. File names and header text from users'
  files never appear in a failure message.

## Usage

Users ask in a V2 chat, for example "merge these three regional CSVs into one Excel file".
See [Merge files in chat](../../guides/merge-files.md). Administrators control the feature
under [Document Action Capabilities](../../admin/agents-actions.md#document-action-capabilities-card)
and the orchestration Capabilities list
([orchestration settings](../../admin/orchestration.md)).

## Testing and validation

| Test | Covers |
| --- | --- |
| `functional_tests/test_tabular_merge_engine.py` | Readers, encodings, delimiters, Excel values, sheet selection, legacy XLS conversion, policies, mismatch reporting, provenance, limits, guards, cancellation, spill to disk at 120,000 rows. |
| `functional_tests/test_orchestration_tabular_merge_capability.py` | Registry and gating, plan validation, real executor runs without model calls, search-bound sources, failure messages, revoked access, and CSV/XLSX rendering of the retained result. |
| `functional_tests/test_v2_admin_actions_parity.py`, `functional_tests/test_admin_settings_pane_variable_scope.py` | Admin field paths, bounds and defaults, and the admin card rendering with and without stored Merge settings. |

## Known limitations

- Merge appends rows. It does not match rows across files on a key column.
- Phase 1 requires the same columns in every file; Phase 2 reconciles different ones.
- Excel formulas contribute their last calculated values; a workbook saved without them
  merges those cells as blanks.
- Workflows cannot run merges until Phase 3.
