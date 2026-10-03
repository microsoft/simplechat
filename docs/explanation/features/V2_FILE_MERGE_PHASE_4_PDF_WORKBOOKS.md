# V2 File Merge — Phase 4: PDF and Workbook Merges

Version: **0.261.221**

Implemented in version: **0.261.221**, recorded in `application/single_app/config.py`.

GitHub issue: [#1619](https://github.com/microsoft/simplechat/issues/1619). Umbrella document:
[V2 File Merge](V2_FILE_MERGE.md). Builds on
[Phase 3](V2_FILE_MERGE_PHASE_3_WORKFLOWS.md).

Dependencies: no new packages. PDFs are assembled with the existing `pypdf`; workbooks with
the existing `openpyxl` and `xlrd`.

## Overview

Phases 1–3 append the rows of spreadsheets. Two other merges come up just as often:

- **PDFs.** A board pack, a set of signed forms or a month of statements should be one PDF.
- **Workbooks.** Several files should stay separate tables but travel together: one Excel
  workbook with each file on its own sheet, rather than one stacked table.

Phase 4 adds both as kinds of the workflow **Merge files** task. A task's **Merge type** can
now be **Combine rows (CSV/Excel)**, the Phase 3 merge; **One workbook, a sheet per file**;
or **Combine PDFs**. Every kind takes its files the same four ways (selected files in
order, every matching file, recent files, or the files File Sync changed), authorizes them
again, runs with code and no model, and attaches one file to the run.

Chat can propose a workflow with any of these kinds. Merging PDFs and workbooks directly in
a chat turn, without a workflow, was scheduled for Phase 7 together with Word and
PowerPoint, so that every document kind reaches chat through one shared Render path; it
arrived in **0.261.224** ([Phase 7](V2_FILE_MERGE_PHASE_7_CHAT_DOCUMENTS.md)).

## Technical specifications

### Document merge engine

`functions_document_merge.py` is a pure engine: it receives authorized byte loaders, never
resolves documents or settings, and performs no model work.

| Piece | Responsibility |
| --- | --- |
| `merge_documents(kind, parts, options, limits, cancel_requested, on_progress, min_parts)` | Validates the parts, runs the kind's assembler, and returns a `DocumentMergeResult`: the file in a bounded spooled temporary file, its size and media type, and the merge report. |
| `DocumentMergePart` | One authorized source: id, file name, byte loader, and optional page ranges. |
| `DocumentMergeOptions` | `bookmarks` (PDF), `sheets` and `sheet` (workbook), and the Word and PowerPoint options of later phases. |
| `DocumentMergeLimits` | Files, bytes per file and in total, output bytes, pages, slides, sheets, rows, cells, and package expansion. |
| `guard_ooxml_package` | Refuses encrypted, damaged or oversized Office packages before they are parsed. |
| `document-merge-report-v1` | Kind, options, one entry per file (status, pages or sheets, sheet names, warnings), totals, warnings, and limitations. |

`min_parts` is 1 only for a workflow merge of files found at run time, so one PDF that
arrived with a sync is still delivered.

#### PDF (`functions_document_merge_pdf.py`)

- Pages are copied with `pypdf`, so text, images, links and fonts stay exactly as they were.
- With **Add bookmarks** on (the default), each file starts with a top-level bookmark named
  after it, and the file's own bookmarks are kept beneath it.
- Encrypted PDFs are refused rather than decrypted, so a merge never removes protection.
- Actions that could run code, open files or programs, or submit forms are removed
  wherever they appear: open actions, document, page, link and form-field scripts, and XFA
  form logic. Only navigation is kept: links to a page in the merged file, the standard
  next, previous, first and last page commands, and `http`, `https` and `mailto`
  addresses. Links to other files, network paths or other address types are removed, as is
  any link with a script chained after it. The report says when anything was removed.
- Fillable form fields are kept; fields with the same name in different files share one
  value, and the report warns about it.
- `pypdf` keeps every source in memory until the merged file is written, so memory grows
  with the total input; callers bound it with `max_total_input_bytes`.

#### Workbook (`functions_document_merge_workbook.py`)

- Each file becomes a sheet named after the file, or, with every sheet, one sheet per source
  sheet named "file - sheet". Names are made unique and kept within Excel's 31 characters.
- Excel sources keep their cell types and number formats, so numbers stay numbers and dates
  stay dates. CSV values are copied as text, so codes keep their leading zeros.
- Formulas contribute their last calculated values. Text that looks like a formula is
  written as text and never evaluated.
- Control characters, which Excel can't store, such as the end-of-file mark some older
  exports leave, are removed, and the report says how many for each file.
- Styles, column widths, merged cells, charts and images are not copied; the report says so.
- **Sheets** chooses the first visible sheet of each file (the default), every visible sheet,
  or one named sheet. A file without the named sheet fails the merge with its name.
- The workbook is written with fixed dates and package metadata, so the same files always
  give the same bytes.

### Workflow tasks

The Phase 3 contract gains two values of `merge_kind`:

| `merge_kind` | Accepted files | `output_format` | `merge_options` |
| --- | --- | --- | --- |
| `tabular` | `.csv`, `.xlsx`, `.xlsm`, `.xls` | `csv` (default) or `xlsx` | The chat merge settings |
| `workbook` | `.csv`, `.xlsx`, `.xlsm`, `.xls` | `xlsx` | `sheets`, `sheet` |
| `pdf` | `.pdf` | `pdf` | `bookmarks` |

`MERGE_KINDS_AVAILABLE` (Python) and `WORKFLOW_MERGE_KINDS_AVAILABLE` (V2) list the kinds a
save accepts; Word and PowerPoint stay refused until Phases 5 and 6. Options from another
kind are refused with "Some merge options don't apply to PDF merges. Remove them."

`execute_workflow_merge` shares discovery, authorization and skipping between kinds, then
hands spreadsheet rows to the tabular engine and every other kind to `merge_documents`.
Files are read through `build_document_merge_parts`, which uses the same screening-aware
byte reader as row merges. A workflow run allows more than a chat turn would:

| Limit | Workflow value |
| --- | --- |
| Files | The Merge workflow file limit, 100 by default |
| Output file | The generated-file size limit, 500 MB by default |
| Input bytes in total, PDF | 300 MB, because every PDF stays in memory until the file is written |
| Input bytes in total, workbook | Twice the output limit, at least 300 MB; files are copied one at a time |
| Bytes per file | 100 MB |
| Pages (PDF) | 10,000 |
| Sheets (workbook) | 500 |

The assembled file is hashed and uploaded under the same `workflow-merge:{run}:{task}:{sha256}`
idempotency key as a row merge. Because the same files always give the same bytes, a task
that is replayed or retried after uploading finds the file it already attached rather than
adding a second one. The task's answer says how many files were merged into
which file and how many pages or sheets it has, lists the files in order, and repeats the
engine's warnings and limitations, such as scripts that were removed or styles that weren't
copied. Run activity reports pages or sheets per file.

Failures name the owner's file: "broken.pdf couldn't be read as a PDF.",
"Report.pdf is password-protected or encrypted, so it can't be merged.",
'east.xlsx has no sheet named "Totals".', or for a selected file of the wrong type,
"notes.docx isn't a PDF file (.pdf), so it can't be merged." An unexpected error inside
`pypdf`, `openpyxl` or `xlrd` is reported the same way, for example "east.csv couldn't be
copied into the workbook.", never with the library's own message, which can quote cell
text. Like row merges, they're shown on the task and not retried. A failing cancellation
check, such as an unavailable run store, and storage errors, such as a full temporary
disk, aren't blamed on a file: they pass through unchanged so the run can retry.

### Workflows proposed from chat

The blueprint `merge` field gains `kind`: `tabular` (the default), `workbook` or `pdf`.
`output_format` defaults to the kind's own format, and the options schema adds `bookmarks`.
The draft service checks each merge with the same normalizer a save uses, so options from
another kind are reported as `merge_options_invalid`, and an output format the kind can't
create as the new `merge_format_invalid`. The proposal summary carries `kind`, and the card
reads, for example, "Merges every PDF in your personal workspace into one PDF with code. No
model runs." or "... into one Excel workbook, a sheet per file, with code."

### Components

| File | Change |
| --- | --- |
| `functions_document_merge.py`, `functions_document_merge_pdf.py`, `functions_document_merge_workbook.py` | New. The engine and its PDF and workbook assemblers; `min_parts` and `open_stream()` for workflow use. |
| `functions_orchestration_merge.py` | `build_document_merge_parts`. |
| `functions_document_actions.py` | `workbook` and `pdf` in `MERGE_KINDS_AVAILABLE`. |
| `functions_workflow_merge.py` | Document kinds, workflow document limits, `build_document_merge_reply`, and kind-specific wrong-type messages. |
| `functions_workflow_runner.py` | Progress detail in rows, pages, slides or sheets. |
| `functions_workflow_drafts.py`, `functions_orchestration_workflows.py`, `functions_orchestration_workflow_proposals.py`, `functions_orchestration_planner.py` | Blueprint merge kinds, `merge_format_invalid`, the summary's `kind`, and the planner's merge task instructions. |
| `application/v2_ui/src/lib/workflowEditor.ts` | The two kinds enabled in the editor. |
| `application/v2_ui/src/lib/workflowProposals.ts` | The proposal's merge `kind` and its wording. |

## Usage

In the V2 workflow editor, add a task, choose **Merge files**, then choose **Merge type**:
**Combine PDFs** or **One workbook, a sheet per file**. **More merge options** holds **Add
bookmarks** for PDFs and **Sheets** for workbooks. See
[Create a workflow](../../guides/create-a-workflow.md#merge-files-in-a-workflow).

## Testing and validation

| Test | Covers |
| --- | --- |
| `functional_tests/test_document_merge_pdf_workbook.py` | The PDF and workbook assemblers: order, bookmarks, page ranges, encrypted, damaged and mislabeled files, removed scripts, form actions and file or program links with page, web and email links kept, the same bytes for the same files, removed control characters, library failures that name only the file, cancellation-check and storage failures that pass through, progress, sheet naming, typed sheets, named, every-sheet and hidden-sheet modes, limits, and cancellation. |
| `functional_tests/test_workflow_merge_pdf_workbook.py` | The task contract for both kinds, a PDF with a bookmark per file, a workbook with a sheet per file, run-time skipping and a single file, failure messages, cancellation, a repeated merge reusing its file, the PDF input limit, the runner's upload and progress, and chat-proposed PDF and workbook merges. |
| `functional_tests/test_v2_workflow_merge_task.mjs`, `ui_tests/test_v2_workflow_merge_task.py` | The kinds the editor allows, and authoring a PDF merge in a browser. |
| `functional_tests/test_v2_workflow_proposal_merge.mjs`, `ui_tests/test_v2_orchestration_workflow_proposal_card.py` | The proposal's merge kind and wording. |

## Known limitations

- In this phase PDF and workbook merges ran only in workflows, and chat proposed a workflow
  that did it. Since **0.261.224** a chat turn merges them directly
  ([Phase 7](V2_FILE_MERGE_PHASE_7_CHAT_DOCUMENTS.md)).
- Page ranges are supported by the engine but not yet offered in the workflow editor.
- A workbook merge copies values and number formats, not styles, charts or images.
- A PDF merge reads at most 300 MB of PDFs in total, whatever the generated-file limit,
  because every source stays in memory until the merged PDF is written.
- A merge-only workflow still asks for a runner, which its merge tasks don't use.
