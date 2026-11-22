# V2 Generated File Card

## Overview

When a plan produces files, the modern (V2) chat lists each one under the reply in a **Files**
section. The card used to read like a status record: the file name, a line such as
`Word document · 0 rows · 40.3 KB`, a green **Completed** badge, and a **Download DOCX** button
on a row of its own. The reply text above it repeated the file as
`ready (0 rows, 18,898 characters, 41,274 bytes)`.

The card is now a single compact row: a file-type icon, the file name, one line of details that
fit the file type, and a **Download** button at the end of the row.

Implemented in version **0.261.481**.

### Dependencies

None added. The icons come from `lucide-react`, which V2 already uses, and the colours are the
existing theme tokens, so light and dark themes need no extra rules.

## Technical specifications

### The row

| Part | What it shows |
|---|---|
| Icon | A tinted tile per file type: Word (accent), PDF (danger), PowerPoint (warn), Excel and CSV (ok), JSON, XML and YAML (info), text and Markdown (neutral). An unknown format gets a plain file icon. |
| Name | The file name, wrapping rather than truncating. |
| Details | The type label, then the facts that fit the type (below). |
| Status | **Waiting**, **Rendering**, **Automatic retry scheduled**, **Failed**, **Cancelled** or **Unavailable** as a badge. A finished file shows no badge, because its Download button already says it is ready; the status is still present for assistive technology. |
| Download | **Download**, with the format kept in the accessible name (`Download DOCX`). View buttons and an approval notice appear as before; the notice wraps beneath the row at full width. |

Notes, errors and **Retry file** stay beneath the row. On a narrow screen the badge and the
button wrap under the name.

### Details per file type

| File type | Details |
|---|---|
| CSV, Excel, JSON, XML, YAML | Type · rows · size |
| Word, PDF, PowerPoint, Markdown, text | Type · size |

A row count describes a file of records and nothing else. The server reports zero records for a
document, which is why a finished Word file used to say "0 rows". Zero is still shown for a file
of records, where it is a real count.

Page and slide counts are not shown. The server does not record them for generated files, and a
Word document has no fixed pages until it is laid out.

### Reply text

The **Files** list in the reply text follows the same rule and uses a readable size:
`review.docx: ready (40.3 KB).` and `rows.csv: ready (50 rows, 1006 B).` Character counts are no
longer listed.

### File structure

| File | Change |
|---|---|
| `application/v2_ui/src/components/chat/GeneratedFileIcon.tsx` | New. The icon tile. |
| `application/v2_ui/src/components/chat/OrchestrationOutputs.tsx` | The card is one row; the badge is hidden for a finished file. |
| `application/v2_ui/src/components/chat/GeneratedArtifactCard.tsx` | The embedded controls join the row; the button reads **Download**. |
| `application/v2_ui/src/lib/orchestrationOutputs.ts` | `orchestrationOutputHasRows`, `orchestrationOutputRowLabel`. |
| `application/v2_ui/src/lib/conversationGeneratedFiles.ts` | The drawer's Generated list uses the same row rule. |
| `application/single_app/functions_orchestration_execution.py` | `_delivery_summary` states rows only for files of records, and a readable size. |

## Usage

Nothing to enable. Ask a plan for a file in the modern chat; the card appears under the reply.
The classic chat's file card is unchanged.

## Testing and validation

- `functional_tests/test_v2_generated_file_card_details_logic.mjs` runs the real helpers for the
  row rule and the details line.
- `functional_tests/test_orchestration_harness_execution.py`
  (`test_delivery_summary_states_the_facts_that_fit_each_file_type`) covers the reply text.
- `ui_tests/test_v2_orchestration_outputs.py` mounts the production card and checks the icon,
  the details line, the **Download** label and that the status is still announced.

### Limitations

- Page and slide counts need the renderers to record them; they are not part of this change.
- Only the plan file card and the drawer's Generated list changed. The standalone export and
  analysis cards keep their layout.
