# V2 File Merge

Version: **0.261.222**

Implemented in version: **0.261.218** (Phase 1, same-structure spreadsheets),
**0.261.219** (Phase 2, reconciling different structures), **0.261.220** (Phase 3,
workflow merges), **0.261.221** (Phase 4, PDF and workbook merges) and **0.261.222**
(Phase 5, Word merges), recorded in `application/single_app/config.py`.

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
| 2 | Reconciling different structures: column inspection (`tabular_inspect`), union and mapped policies, aliases, header rows, every-sheet mode, exclusion, duplicate removal, sorting, AI-prepared column mapping | Implemented in **0.261.219** — see [Phase 2](V2_FILE_MERGE_PHASE_2_RECONCILIATION.md) |
| 3 | Large and recurring merges (100+ files) as V2 workflow tasks: selected files, every matching file, recent files or the files File Sync changed; chat-proposed merge workflows | Implemented in **0.261.220** — see [Phase 3](V2_FILE_MERGE_PHASE_3_WORKFLOWS.md) |
| 4 | Document merge engine; PDF merges (a bookmark per file) and workbooks with one sheet per file, as workflow merge types | Implemented in **0.261.221** — see [Phase 4](V2_FILE_MERGE_PHASE_4_PDF_WORKBOOKS.md) |
| 5 | Word merge, keeping each document's styles or the first document's, as a workflow merge type | Implemented in **0.261.222** — see [Phase 5](V2_FILE_MERGE_PHASE_5_WORD.md) |
| 6 | PowerPoint merge, keeping each deck's look or the first deck's theme, as a workflow merge type | Planned |
| 7 | Document merges directly in chat (`document_merge` with assembled Render profiles) for every document kind; scale and security hardening, final documentation | Planned |

Document merges reach workflows first, kind by kind, so every file type is usable as soon as
its phase lands, including from workflows that chat proposes. Merging documents inline in a
chat turn shares one Render path for all document kinds, so it is built once, in Phase 7.

## Where merge fits in Gather / Reason / Render

Merge is another capability alongside Analyze and Compare. It does not replace any of
them, and it is reached the same way: the user asks in a V2 chat and the orchestrator
plans the work.

| Purpose | Role in a merge |
| --- | --- |
| Gather (optional) | `document_search` finds the files when the user describes them instead of selecting them. Its `sources` output binds into the merge. `tabular_inspect` reads the files' sheets, headers, row counts and samples and reports how their columns line up. |
| Reason | `compose` can prepare a `tabular_column_mapping_v1` column mapping from an inspection. `tabular_merge` reads the authorized files and appends their rows with code into one retained table. No model reads or rewrites rows. |
| Render | `render_file` turns the retained table into a CSV or Excel file. |

Merging is Reason, not Render, because it computes a new dataset from sources; Render only
serializes a prepared result. Keeping the merged table as a retained result also lets one
merge feed several files — a CSV and an Excel copy — without merging twice.

Saved memory does not store or merge files. The planner does read saved preferences, so a
saved instruction such as "always give me Excel" shapes merge requests without extra work.

### Merges in workflows

A chat turn suits a few files. A workflow task merges up to 100 files and 1,000,000 rows by
default, on a schedule or whenever File Sync brings new files, without anyone asking. In
the V2 workflow editor a task's **Document action** can be **Merge files**: the task runs
the same engine with code, no model, and attaches the merged CSV or Excel file to the run.
Since **0.261.221** its **Merge type** can also join PDFs into one PDF or put spreadsheets on
separate sheets of one workbook, and since **0.261.222** append Word documents into one Word
document. Chat can propose such a workflow when a user asks for a recurring merge. See
[Phase 3](V2_FILE_MERGE_PHASE_3_WORKFLOWS.md), [Phase 4](V2_FILE_MERGE_PHASE_4_PDF_WORKBOOKS.md)
and [Phase 5](V2_FILE_MERGE_PHASE_5_WORD.md).

## Technical specifications

### Components

| File | Responsibility |
| --- | --- |
| `functions_tabular_merge.py` | Pure merge and inspection engine: CSV, XLSX/XLSM and XLS readers that keep values as text, header normalization, schema policies and aliases, header rows, sheet modes, provenance columns, exclusion, duplicate removal, bounded sort, limits, cancellation, archive guards, the merge report, the inspection, and the column mapping profile. No Flask, settings, storage or model imports. |
| `functions_orchestration_merge.py` | Orchestration glue: Merge limits from settings, the authorized-source manifest check, screening-aware byte loaders, persistence of the retained `records`, `report` and `inspection`, and the engine-to-failure-code maps. |
| `functions_orchestration_adapters.py` | `run_tabular_inspect` and `run_tabular_merge`, registered in `ADAPTER_REGISTRY`. |
| `functions_orchestration_registry.py` | The `tabular_inspect` and `tabular_merge` capability descriptors and the `merge` document-action gate. |
| `functions_orchestration_schema.py` | Plan rules: explicit document IDs or a bound source set, tabular-only sources, the Merge chat limit, valid option combinations, the mapping producer, and the merge and inspection failure messages. |
| `functions_orchestration_services.py` | The `tabular_column_mapping_v1` prepared-content profile and its validator. |
| `functions_document_actions.py` | The `merge` document action: enablement, file limits and row limits for chat and workflows, and the workflow Merge task contract. |
| `functions_workflow_merge.py`, `functions_workflow_runner.py` | Workflow Merge tasks: finding the files, authorizing them again, merging, rendering and attaching the file to the run. |
| `functions_document_merge.py`, `functions_document_merge_pdf.py`, `functions_document_merge_workbook.py`, `functions_document_merge_docx.py` | The document merge engine and its PDF, workbook and Word assemblers. Word composition uses `docxcompose`. |
| `functions_workflow_drafts.py` | The `merge` field of workflow blueprints proposed from chat. |
| `functions_generated_export_registry.py`, `functions_structured_file_renderers.py`, `functions_generated_office_adapters.py` | The `exact_tabular_records_v1` (CSV) and `exact_tabular_workbook_v1` (XLSX) profiles. |
| `application/v2_ui/src/lib/orchestrationMerge.ts` | The plan review's wording for merge and inspection settings. |
| `application/v2_ui/src/lib/workflowEditor.ts`, `components/workflows/WorkflowTaskFields.tsx` | The workflow editor's **Merge files** document action. |

### Result contract

`tabular_merge` retains two outputs under contract `tabular-merge-v1`:

- `records` (`records-v1`): one string column per merged column, in output order, with
  every row. At most 256 columns, because retained record schemas allow 256. A column is
  nullable when some merged file or sheet doesn't have it.
- `report` (`structured-v1`): `tabular-merge-report-v1`, holding the policy, the output
  columns, nullable columns, the file and sheet name columns, totals, one entry per file
  or sheet (file name, format, sheet, header row, encoding, delimiter, status and reason,
  rows, skipped blank rows, padded short rows, removed duplicates, column differences,
  renamed and left-out columns, warnings), any prepared column mapping, and limitations.

Coverage counts sources. The result is complete only when every source merged or was
left out by request; a merge either finishes or produces nothing.

`tabular_inspect` retains `inspection` (`structured-v1`, `tabular-inspection-v1`) under
contract `tabular-inspect-v1`.

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
| Sheets per workbook (every-sheet mode) | 100 | Engine constant |
| Rows that can be sorted | 250,000 | Engine constant, capped by the row limit |
| Inspection size | 96 KB, samples dropped first | Engine constant |

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

Users ask in a V2 chat, for example "merge these three regional CSVs into one Excel file",
or add a **Merge files** task to a workflow for many files or repeated merges. See
[Merge files](../../guides/merge-files.md) and
[Create a workflow](../../guides/create-a-workflow.md). Administrators control the feature
under [Document Action Capabilities](../../admin/agents-actions.md#document-action-capabilities-card)
and the orchestration Capabilities list
([orchestration settings](../../admin/orchestration.md)).

## Testing and validation

| Test | Covers |
| --- | --- |
| `functional_tests/test_tabular_merge_engine.py` | Readers, encodings, delimiters, Excel values, sheet selection, legacy XLS conversion, policies, mismatch reporting, provenance, limits, guards, cancellation, spill to disk at 120,000 rows. |
| `functional_tests/test_tabular_merge_reconciliation.py` | Union, mapped and alias policies, header rows, every-sheet mode, exclusion, duplicates, sorting and inspection. |
| `functional_tests/test_orchestration_tabular_merge_capability.py` | Registry and gating, plan validation, real executor runs without model calls, search-bound sources, failure messages, revoked access, and CSV/XLSX rendering of the retained result. |
| `functional_tests/test_orchestration_tabular_reconciliation.py` | Inspection, option combinations, the mapping producer, inspect → compose mapping → merge through the real executor, nullable union columns, and the planner recipe. |
| `functional_tests/test_v2_orchestration_merge_arguments.mjs`, `ui_tests/test_v2_orchestration_merge_arguments.py` | The plan review's wording for merge and inspection settings. |
| `functional_tests/test_v2_admin_actions_parity.py`, `functional_tests/test_admin_settings_pane_variable_scope.py` | Admin field paths, bounds and defaults, and the admin card rendering with and without stored Merge settings. |
| `functional_tests/test_workflow_merge_task.py`, `functional_tests/test_v2_workflow_merge_task.mjs`, `functional_tests/test_v2_workflow_proposal_merge.mjs`, `ui_tests/test_v2_workflow_merge_task.py` | Workflow Merge tasks, their editor, and proposed merge tasks (Phase 3). |
| `functional_tests/test_document_merge_pdf_workbook.py`, `functional_tests/test_workflow_merge_pdf_workbook.py` | The PDF and workbook assemblers, and PDF and workbook workflow merges (Phase 4). |
| `functional_tests/test_document_merge_docx.py`, `functional_tests/test_workflow_merge_word.py` | The Word assembler and Word workflow merges (Phase 5). |

## Known limitations

- Merge appends rows. It does not match rows across files on a key column.
- Column aliases apply to every file; a header that means different things in different
  files can't be mapped per file.
- Excel formulas contribute their last calculated values; a workbook saved without them
  merges those cells as blanks.
- A workflow merge that resumes after an interruption starts again from its first file.
