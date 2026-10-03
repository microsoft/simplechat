# V2 File Merge — Phase 6: PowerPoint Merges

Version: **0.261.223**

Implemented in version: **0.261.223**, recorded in `application/single_app/config.py`.

GitHub issue: [#1619](https://github.com/microsoft/simplechat/issues/1619). Umbrella document:
[V2 File Merge](V2_FILE_MERGE.md). Builds on [Phase 5](V2_FILE_MERGE_PHASE_5_WORD.md).

Dependencies: no new packages. Decks are assembled at the package level with the standard
library and the already pinned `lxml`; `python-pptx` re-opens the result to check it.

## Overview

Quarterly reviews, training modules and conference talks are often built as separate decks
by different people and presented as one. Copying slides between decks by hand loses their
layouts and themes, and re-creating them with a model changes them.

Phase 6 adds **Combine PowerPoint decks** as a **Merge type** of the workflow **Merge files**
task. It appends the slides of PowerPoint decks, in order, into one `.pptx` with code and no
model, and takes its files the same four ways as every merge: selected files in order, every
matching file, recent files, or the files File Sync changed. Chat can propose a workflow
that does it, for example "after each sync, combine the team decks into one deck". With
this phase every merge type is available in workflows.

## Technical specifications

### PowerPoint assembler (`functions_document_merge_pptx.py`)

- The merge works on the Office Open XML package itself, so every slide is copied with
  everything it relates to: pictures, media, charts with their embedded workbooks, diagrams
  and speaker notes, exactly as they were.
- **Formatting** decides how slides look. **Keep source formatting** (the default) brings
  each deck's slide layouts, masters and themes along, so slides keep their original look;
  identical masters and layouts are reused rather than copied twice. **Use the first deck's
  theme** places each slide on the first deck's matching layout, by name and then by type,
  so every slide takes the first deck's theme. A slide with no matching layout uses a blank
  layout, and the report says how many did.
- **Create one section per deck** (on by default) groups each deck's slides in a section
  named after the file.
- The first deck decides the slide size; a deck with a different size is reported, because
  its slides may look stretched or cropped. Fonts embedded in later decks and slide
  comments are not carried over, and the report says so for each deck.
- Hyperlinks are copied as they are. Content linked from other files or the web, such as
  linked pictures, media or objects, stays linked, and the report says which decks have it.
  When only some slides are merged, links to slides that weren't merged are removed.
- Master, layout and slide IDs stay unique, every part keeps a content type, and slides that
  weren't selected leave no orphaned parts. `python-pptx` re-opens the result and checks that
  every selected slide is there before it is delivered.
- Encrypted, damaged, oversized and macro-enabled decks are refused.
- ZIP entries carry fixed dates and section IDs are derived rather than random, so the same
  decks always give the same bytes and a replayed task reuses the file it attached.
- An error inside the assembler or its XML parser is reported by file name only, for
  example "Beta.pptx couldn't be combined with the other decks.", never with the library's
  own message, which can quote slide text. A failing cancellation check or a storage error,
  such as a full temporary disk, passes through unchanged so the run can retry.

### Workflow task contract

| `merge_kind` | Accepted files | `output_format` | `merge_options` |
| --- | --- | --- | --- |
| `pptx` | `.pptx` | `pptx` | `formatting` (`keep_source` or `use_first`), `sections` |

`MERGE_KINDS_AVAILABLE` (Python) and `WORKFLOW_MERGE_KINDS_AVAILABLE` (V2) now include every
kind. The list stays, so withholding a kind again still refuses it in the editor, at save
and when a run starts. A PowerPoint merge assembles up to 2,000 slides and reads at most
300 MB of decks in total, because the merged package is built in memory until it is written.
Files and the output size follow the Merge workflow file limit and the generated-file size
limit.

The task's answer says how many slides the merged deck has, lists the files in order, and
repeats the report's warnings and limitations. Run activity reports the slides of each deck.

### Workflows proposed from chat

The blueprint `merge` field accepts `kind` `pptx`, and its options schema adds `sections`.
The planner's merge guidance describes PowerPoint merges and their options, and the
`merge_options_invalid` repair hint includes "pptx takes formatting, sections". The proposal
card reads, for example, "Merges every PowerPoint deck in your personal workspace into one
PowerPoint deck with code. No model runs."

### Components

| File | Change |
| --- | --- |
| `functions_document_merge_pptx.py` | New. The PowerPoint assembler. |
| `functions_document_merge.py` | `pptx` in `DOCUMENT_MERGE_KINDS` and its assembler; `fixed_zip_entry`, shared with `normalized_package`. |
| `functions_document_actions.py` | Every kind in `MERGE_KINDS_AVAILABLE`. |
| `functions_workflow_drafts.py` | The `pptx` kind and `sections` in the blueprint schema. |
| `functions_orchestration_planner.py` | PowerPoint merges in the planner's merge task guidance. |
| `application/v2_ui/src/lib/workflowEditor.ts` | PowerPoint enabled in the editor; its options were already in **More merge options**. |
| `application/v2_ui/src/lib/workflowProposals.ts` | The `pptx` kind and its wording on the proposal card. |

## Usage

In the V2 workflow editor, add a task, choose **Merge files** as its **Document action**,
then choose **Combine PowerPoint decks** as the **Merge type**. Choose the files, then open
**More merge options** to set **PowerPoint formatting** and **Create one section per deck**.
See [Create a workflow](../../guides/create-a-workflow.md#merge-files-in-a-workflow).

## Testing and validation

| Test | Covers |
| --- | --- |
| `functional_tests/test_document_merge_pptx.py` | Kept and first-deck formatting, reused masters, charts, pictures, tables and notes, sections, slide selection and order, removed slide links, slide size and external link reports, a consistent package, damaged, encrypted, macro-enabled and oversized decks, the same bytes for the same decks, library failures that name only the file, and host failures that pass through. |
| `functional_tests/test_workflow_merge_powerpoint.py` | The task contract, appending in order with a section per deck, run-time skipping, failure messages, a repeated merge reusing its file, the runner's upload and slide progress, and a chat-proposed PowerPoint merge with its repair hint. |
| `functional_tests/test_workflow_merge_task.py`, `functional_tests/test_v2_workflow_merge_task.mjs` | A withheld kind refused by the contract, the merge and the editor. |
| `functional_tests/test_v2_workflow_proposal_merge.mjs`, `ui_tests/test_v2_orchestration_workflow_proposal_card.py` | The proposal's PowerPoint kind and wording. |
| `ui_tests/test_v2_workflow_merge_task.py` | Authoring a PowerPoint merge with its options in a browser. |

## Known limitations

- The first deck decides the slide size.
- Fonts embedded in later decks and slide comments are not carried over.
- Links, linked media, embedded objects and actions that start a program are copied as they
  are. PowerPoint opens downloaded files in Protected View and asks before it runs a program
  from a link; Phase 7 reviews active content in Word and PowerPoint merges.
- Slide ranges are supported by the engine but not yet offered in the workflow editor.
- Merging decks directly in a chat turn, without a workflow, arrives in Phase 7.
