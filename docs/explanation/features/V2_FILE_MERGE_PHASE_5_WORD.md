# V2 File Merge — Phase 5: Word Merges

Version: **0.261.222**

Implemented in version: **0.261.222**, recorded in `application/single_app/config.py`.

GitHub issue: [#1619](https://github.com/microsoft/simplechat/issues/1619). Umbrella document:
[V2 File Merge](V2_FILE_MERGE.md). Builds on
[Phase 4](V2_FILE_MERGE_PHASE_4_PDF_WORKBOOKS.md).

Dependencies: `docxcompose==2.2.0` (MIT), which brings `Babel` (BSD-3-Clause). It builds on
the `python-docx` and `lxml` versions already pinned in `application/single_app/requirements.txt`.

## Overview

Meeting minutes, contract sections, weekly status notes and chapters written by different
people often need to become one Word document. Copying them together by hand loses styles,
numbering and images, and asking a model to rewrite them changes the text.

Phase 5 adds **Combine Word documents** as a **Merge type** of the workflow **Merge files**
task. It appends Word documents, in order, into one `.docx` with code and no model, and
takes its files the same four ways as every merge: selected files in order, every matching
file, recent files, or the files File Sync changed. Chat can propose a workflow that does
it, for example "every Friday, combine this week's status notes into one Word document".

## Technical specifications

### Word assembler (`functions_document_merge_docx.py`)

- The first document is the base: the merged file uses its page setup, headers, footers
  and document settings. Each later document's body is appended after it with
  `docxcompose`, which carries over its styles, numbering, images, tables, footnotes,
  diagrams and shapes.
- **Formatting** decides what happens when two documents define a style with the same
  name. **Keep source formatting** (the default) copies a style that looks different
  under a new name, so every document keeps its own look. **Use the first document's
  formatting** maps such styles to the first document's definitions, so the merged
  document looks uniform.
- **Page break between documents** (on by default) starts each appended document on a new
  page. **Add source headings** (off by default) puts a heading with the file name before
  each document, using the document's Heading 1 style when it has one.
- Comments are kept in a part that isn't carried over, so their anchors are removed from
  appended documents and the report says which documents had comments.
- The merged file carries a fixed modified date and fixed package metadata, so the same
  documents always give the same bytes and a replayed task reuses the file it attached.
- The result is opened again with `python-docx` before it is delivered, so a malformed
  package fails the task rather than reaching the user's Word.
- Encrypted (password-protected) documents and damaged or oversized packages are refused
  before they are parsed. Only `.docx` files are accepted: `.doc` and macro-enabled `.docm`
  files are refused.
- An error inside `python-docx` or `docxcompose` is reported by file name only, for example
  "Beta.docx couldn't be combined with the other documents.", never with the library's own
  message, which can quote document text. A failing cancellation check or a storage error,
  such as a full temporary disk, passes through unchanged so the run can retry.

### Workflow task contract

| `merge_kind` | Accepted files | `output_format` | `merge_options` |
| --- | --- | --- | --- |
| `docx` | `.docx` | `docx` | `formatting` (`keep_source` or `use_first`), `page_breaks`, `source_headings` |

`MERGE_KINDS_AVAILABLE` (Python) and `WORKFLOW_MERGE_KINDS_AVAILABLE` (V2) now include
`docx`; PowerPoint stays refused until Phase 6. A Word merge reads at most 300 MB of
documents in total, like a PDF merge, because the merged document is built in memory until
it is written. Files and the output size follow the Merge workflow file limit and the
generated-file size limit.

A Word document has no fixed page count, so the task's answer and run activity count
files rather than pages. The answer names the merged file, lists the files in order, and
repeats the report's warnings and limitations, such as removed comments and how styles
were handled.

### Workflows proposed from chat

The blueprint `merge` field accepts `kind` `docx`, and its options schema adds `formatting`,
`page_breaks` and `source_headings`. The planner's merge guidance describes Word merges and
their options. The `merge_options_invalid` repair hint now lists the options each document
kind takes, for example "docx takes formatting, page_breaks, source_headings", so the
planner can fix the option it used for the wrong kind. The proposal card reads, for
example, "Merges every Word document in your personal workspace into one Word document
with code. No model runs."

### Components

| File | Change |
| --- | --- |
| `application/single_app/requirements.txt` | `docxcompose==2.2.0`. |
| `functions_document_merge_docx.py` | New. The Word assembler. |
| `functions_document_merge.py` | `docx` in `DOCUMENT_MERGE_KINDS` and its assembler. |
| `functions_document_actions.py` | `docx` in `MERGE_KINDS_AVAILABLE`. |
| `functions_workflow_drafts.py` | The `docx` kind and Word options in the blueprint schema, and the kind-aware `merge_options_invalid` hint. |
| `functions_orchestration_planner.py` | Word merges in the planner's merge task guidance. |
| `application/v2_ui/src/lib/workflowEditor.ts` | Word enabled in the editor; its options were already in **More merge options**. |
| `application/v2_ui/src/lib/workflowProposals.ts` | The `docx` kind and its wording on the proposal card. |

## Usage

In the V2 workflow editor, add a task, choose **Merge files** as its **Document action**,
then choose **Combine Word documents** as the **Merge type**. Choose the files, then open
**More merge options** to set **Word formatting**, **Page break between documents** and
**Add source headings**. See
[Create a workflow](../../guides/create-a-workflow.md#merge-files-in-a-workflow).

## Testing and validation

| Test | Covers |
| --- | --- |
| `functional_tests/test_document_merge_docx.py` | Order, kept and first-document formatting, page breaks and source headings, tables, numbered lists and images, removed comment anchors, encrypted, damaged and wrong files, the same bytes for the same documents, library failures that name only the file, and host failures that pass through. |
| `functional_tests/test_workflow_merge_word.py` | The task contract, appending in order with headings, run-time skipping, failure messages, a repeated merge reusing its file, the runner's upload and progress, and a chat-proposed Word merge with its repair hint. |
| `functional_tests/test_workflow_merge_task.py`, `functional_tests/test_v2_workflow_merge_task.mjs` | PowerPoint as the kind that isn't available yet, and Word as available. |
| `functional_tests/test_v2_workflow_proposal_merge.mjs`, `ui_tests/test_v2_orchestration_workflow_proposal_card.py` | The proposal's Word kind and wording. |
| `ui_tests/test_v2_workflow_merge_task.py` | Authoring a Word merge with its options in a browser. |

## Known limitations

- The merged document uses the first document's headers, footers and page setup.
- Comments are not carried over.
- Fields, links, embedded objects and a linked template are copied as they are. Word opens
  downloaded files in Protected View and asks before it updates links or fields from other
  sources; Phase 7 reviews active content in Word and PowerPoint merges.
- Merging Word documents directly in a chat turn, without a workflow, arrives in Phase 7.
