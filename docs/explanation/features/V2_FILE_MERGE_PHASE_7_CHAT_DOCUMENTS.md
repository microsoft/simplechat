# V2 File Merge — Phase 7: Document Merges in Chat and Hardening

Version: **0.261.224**

Implemented in version: **0.261.224**, recorded in `application/single_app/config.py`.

GitHub issue: [#1619](https://github.com/microsoft/simplechat/issues/1619). Umbrella document:
[V2 File Merge](V2_FILE_MERGE.md). Builds on [Phase 4](V2_FILE_MERGE_PHASE_4_PDF_WORKBOOKS.md),
[Phase 5](V2_FILE_MERGE_PHASE_5_WORD.md) and [Phase 6](V2_FILE_MERGE_PHASE_6_POWERPOINT.md).

Dependencies: no new packages.

## Overview

Until this phase, a PDF, Word, PowerPoint or workbook merge needed a workflow, even for two
files a user wanted right now. Phase 7 brings every document kind into the V2 chat:
"combine these three contracts into one PDF" plans a **Merge documents** step and a file to
create, and the answer links the merged file. The same deterministic engine that workflow
merges use does the work with code. No model reads or rewrites the files.

Phase 7 also hardens every merge against hostile files and confirms the engines at scale:

- Word documents whose fields start other programs (DDE) are refused.
- The first Word document's link to its template is removed, so Word never fetches it.
- PowerPoint click and hover actions that start programs or run macros are removed.
- Office files whose XML declares a document type, the way an XML part asks a parser to
  read server files, or isn't UTF-8 or UTF-16, are refused before any library parses them.
- Word merges whose later documents have lists now give the same bytes every time, so a
  chat merge of them can be delivered and a repeated workflow merge reuses its file.
- 100 files of 1,000 rows merge in one workflow run, and merged CSV and Excel files never
  carry a live formula.

## Technical specifications

### Where a chat document merge fits in Gather / Reason / Render

| Purpose | Capability | What it does |
| --- | --- | --- |
| Gather (optional) | `document_search` | Finds the files when the user describes them. Its `sources` output binds into the merge. |
| Reason | `document_merge` | Authorizes the files, assembles them once to check them and measure the result, and retains a description of the merge and its report. It creates no file. |
| Render | `render_file` with profile `assembled_document_v1` | Reads the same files again, assembles them again, and delivers the file only if it is byte-for-byte the one the merge step checked. |

Render normally serializes a prepared result. A merged file is different: retaining the
merged bytes would store a second copy of every file in the result store. Instead, Reason
retains a description and Render assembles the file from the originals, under a strict
contract:

- Only the merge result's own lineage is read. The rendering service opens the result with
  current source checks, takes its lineage sources, and gives the renderer a reader that
  refuses any other document. It rechecks access after every read. A storage fault while a
  file is read again stays retryable, the same as for any other source Render reads; a file
  that is held for screening or no longer accessible is not.
- The assemblers are deterministic: fixed ZIP dates, derived section IDs, derived Word list
  IDs and fixed document dates mean the same files always give the same bytes, in any
  process. A test re-assembles every kind in fresh processes with different hash seeds.
- The file is delivered only if its size and SHA-256 match the description. A file that
  changed, or no longer opens, fails the render as `output_source_changed`, which can't be
  retried; nothing is uploaded.

### The `document_merge` capability

- Role Reason, label **Merge documents**, gated by **Enable Merge** like `tabular_merge`,
  with the same chat file limit (10 by default). It needs a personal, group or public
  workspace.
- Inputs: `document_ids` (two or more, in merge order) or an `inputs.sources` binding to a
  search's source set, `doc_scope`, and the required `kind`: `pdf`, `docx`, `pptx` or
  `workbook`. Each kind takes only its own settings, with no defaults in the schema, so a
  plan never restates one:

  | `kind` | Accepted files | Settings |
  | --- | --- | --- |
  | `pdf` | `.pdf` | `bookmarks` |
  | `docx` | `.docx` | `formatting` (`keep_source` or `use_first`), `page_breaks`, `source_headings` |
  | `pptx` | `.pptx` | `formatting`, `sections` |
  | `workbook` | `.csv`, `.xlsx`, `.xlsm`, `.xls` | `sheets` (`first` or `all`) or `sheet` |

- Outputs under contract `document-merge-v1`, both `structured-v1`:
  - `assembly` (`document_assembly_v1`): the kind, every option, the files in order (ID
    and file name), and the checked file's format, media type, size and SHA-256. It never
    holds file bytes.
  - `report` (`document-merge-report-v1`): per-file pages, slides or sheets, warnings and
    limitations, the same report workflow merges keep.
- Coverage counts sources. The step summary says what was made, for example "Merged 2
  file(s) into one PDF with 3 page(s)."
- The largest merged file chat creates is the smaller of the generated-file size limit and
  500 MB, the same limit Render applies.

### Plan rules (`functions_orchestration_schema.py`)

- A merge names its files or binds a source set, never both, and takes only its kind's
  settings; a named sheet can't be combined with every sheet (`merge_options_invalid`).
- A workbook merge takes only CSV or Excel files; other kinds refuse them and point to
  `tabular_merge` for appending rows (`source_kind_invalid`).
- A `render_file` step with `assembled_document_v1` must bind the `assembly` output of a
  `document_merge` step, in that merge's format (`pdf`, `docx`, `pptx`, or `xlsx` for a
  workbook) (`result_kind_incompatible`).
- The planner's deliverable recipes describe merge → render, and its workflow guidance now
  proposes workflows only for scheduled, synced or very large merges.

### Failure messages

Chat failures are application-owned text and never name a file:

| Code | Shown when |
| --- | --- |
| `document_merge_sources_invalid` | A file isn't the kind being merged, or fewer than two different files were selected. |
| `document_merge_source_unreadable` | A file is damaged, encrypted, macro-enabled or empty. |
| `document_merge_active_content` | A Word document has fields that start other programs (DDE). |
| `document_merge_limit_exceeded` | Too many files, pages, slides, sheets or rows, or a file or result that is too large. |
| `merge_sheet_not_found`, `merge_options_invalid` | Shared with spreadsheet merges. |
| `document_merge_failed` | Anything else. |

Workflow merges keep naming the file, because the owner needs to know which one to fix.

### Hardening

| Threat | Defense |
| --- | --- |
| Word fields that start programs (`DDE`, `DDEAUTO`) | Every field in the body, headers, footers and notes is checked, including codes split across runs, nested in other fields, in any case, or written with character references. Such a document is refused (`active_content`). Fields and text that merely mention DDE still merge. |
| A Word template fetched from another computer or website | The first document's `attachedTemplate` link is removed and reported; later documents' settings are never carried over. |
| Linked content in Word | External relationships other than hyperlinks are reported as linked content. |
| PowerPoint actions that start programs or macros | `ppaction://program` and `ppaction://macro` click and hover actions are removed from every deck, including the first, with their relationships, and reported. Every part PowerPoint reads as Office XML is checked, chosen by its declared content type whatever its name or encoding, and a deck that can't be checked isn't delivered. Web links are kept. |
| XML external entities and entity expansion | The XML parsers used by every merge have entity resolution and network access turned off. In addition, `functions_ooxml_package_guard.py` checks every part named `.xml`, `.rels` or `.vml` and every part `[Content_Types].xml` declares an Office XML type, matched without regard to case, before any library parses the package. It refuses a document type declaration, which Office Open XML forbids, and XML written or declared in an encoding other than UTF-8 or UTF-16, which Office Open XML requires and which could otherwise hide a declaration. It reads only each part's prolog: at most 4 KiB per part, in growing chunks, and 32 MiB for the whole package, so a package of many long prologs costs about a second; cancellation and Render's own checks run between parts. This applies to Word, PowerPoint and workbook merges and to spreadsheet merges of `.xlsx` and `.xlsm` files. Pictures and web pages, such as SVG images and imported HTML, may declare a document type and aren't affected. |
| ZIP bombs | Declared uncompressed sizes and part counts are checked before parsing; an entry that understates its size fails its checksum when read. |
| Formula injection | CSV output prefixes formula-like cells so spreadsheet apps show them as text; Excel output stores them as text, never as formulas. |
| Scripts in PDFs | Unchanged from Phase 4: scripts, form actions and links that open files or programs are removed. |

### Components

| File | Change |
| --- | --- |
| `functions_document_merge_assembly.py` | New. The `document_assembly_v1` description, its strict validator, kind-specific option parsing, and byte-identical re-assembly. Imports only the merge engine. |
| `functions_orchestration_document_merge.py` | New. Chat glue: limits, the authorized manifest check, persistence of `assembly` and `report`, step summaries and failure codes. |
| `functions_ooxml_package_guard.py` | New. The XML prolog check shared by the document and spreadsheet engines, and the content-type lookup PowerPoint stripping uses. |
| `functions_orchestration_registry.py`, `functions_orchestration_adapters.py`, `functions_orchestration_executor.py`, `functions_orchestration_result_contracts.py` | The `document_merge` descriptor, adapter and named-source handling. |
| `functions_orchestration_schema.py`, `functions_orchestration_deliverables.py`, `functions_orchestration_planner.py` | Plan rules, failure messages, recipes and planner guidance. |
| `functions_generated_export_registry.py`, `functions_generated_office_adapters.py`, `functions_generated_file_exports.py` | The `assembled_document_v1` profile on the PDF, Word, PowerPoint and Excel formats, and the assembled renderer. |
| `functions_orchestration_rendering.py`, `functions_orchestration_services.py`, `functions_orchestration_bootstrap.py`, `functions_orchestration_results.py` | The lineage-bound document reader, `ResultReader.lineage_sources()`, and one shared translation of source read failures for the reader and every other source Render opens. |
| `functions_document_merge.py`, `functions_document_merge_docx.py`, `functions_document_merge_pptx.py`, `functions_document_merge_workbook.py`, `functions_tabular_merge.py` | The hardening above, and derived Word list IDs. |
| `application/v2_ui/src/lib/orchestrationMerge.ts` | The plan card says what a document merge creates and which settings it changes. |

## Usage

Administrators need nothing new: **Merge documents** is on whenever **Enable Merge** is on,
and it appears in the orchestration Capabilities list. A deployment that narrowed that list
must add **Merge documents** to use it.

Users ask in a V2 chat with **Orchestrate** on, for example:

> Combine these three signed contracts into one PDF.

> Put these two Word reports together, using the first one's styles.

> Merge the selected decks into one presentation without sections.

> Keep each of these CSV files as its own sheet in one Excel workbook.

The plan shows **Merge documents** with what it creates and any setting that differs from
the default, followed by the file to create. See
[Merge files](../../guides/merge-files.md#merge-pdfs-word-documents-decks-or-workbooks).

## Testing and validation

| Test | Covers |
| --- | --- |
| `functional_tests/test_orchestration_document_merge_capability.py` | Registry and gating, kind-specific settings, source binding, the chat limit, source kinds, render admission by format, the real executor for every kind without model calls, step summaries, render re-assembly with the checked bytes, changed and unreadable sources, access failures passing through, format and size refusals, and application-owned failure messages. |
| `functional_tests/test_document_merge_assembly.py` | Option parsing, the description contract and its refusals, byte-identical re-assembly for every kind in this process and in fresh processes with different hash seeds, limits checked before any read, caller failures passing through, and cold imports with and without `-O`. |
| `functional_tests/test_orchestration_output_lifecycle.py` | The real rendering service: a merged PDF downloads with the checked SHA-256 after reading only its own files, a changed file is never uploaded, and revoked access or a missing reader fails before any read. |
| `functional_tests/test_file_merge_hardening.py` | DDE refusal and its evasions, template removal, linked content, PowerPoint program actions in UTF-16 slides and slides renamed `.dat`, `.vml` or `.rels`, XML document type declarations and XML written or declared in other encodings, selection by declared content type, the prolog reader and its reading budget, failing checks passing through, and declared and understated ZIP sizes. |
| `functional_tests/test_document_merge_docx.py` | Lists copied from later documents keep restarting and give the same bytes on every run. |
| `functional_tests/test_workflow_merge_task.py` | 100 files of 1,000 rows in one workflow run, and CSV and Excel output without live formulas. |
| `functional_tests/test_v2_orchestration_merge_arguments.mjs`, `ui_tests/test_v2_orchestration_merge_arguments.py` | The plan card's wording for document merges. |

## Known limitations

- A chat document merge assembles the files twice, once to check them and once to deliver
  the file. Large merges take about twice as long as one assembly.
- If a file changes between the merge step and the file being created, nothing is
  delivered. Ask again to merge the current files.
- Page and slide ranges are supported by the engine but not offered in chat or workflows.
- Linked content, such as pictures linked from the web or another computer, stays linked
  and is reported, because removing it would change the documents. Office asks before
  updating most links, and opens downloaded files in Protected View.
