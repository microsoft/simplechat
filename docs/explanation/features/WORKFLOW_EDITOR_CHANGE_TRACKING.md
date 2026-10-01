# Workflow Editor Change Tracking (v0.261.203)

## Overview

The V2 workflow editor now shows what changed since you opened a workflow, who changed it,
and what it was before, and lets you revert any single change. Before this release the editor
could undo and redo, but a long editing session left no record of which fields were different
from the saved workflow. You had to remember, or cancel and start again.

Every unsaved change is highlighted where it happened, with a badge naming its author, the
value it had when the editor opened, and its own **Revert**. A removed task or block leaves a
**Removed · Restore** row where it was. A **Changes** panel lists every change with **Jump** and
**Revert**, and lists this session's steps with **Restore to here**.

This is the editor side of the AI workflow assistant. It is useful without AI, and it is also
what makes AI-authored edits reviewable later: each change records whether you or an AI assist
turn made it, and a save that includes AI changes asks you to review them first.

Implemented in version: **0.261.203**, tracked in `application/single_app/config.py`.
Phase 3a of the [chat orchestration workflows roadmap](CHAT_ORCHESTRATION_WORKFLOWS_ROADMAP.md)
(#1548, part of #1543).

Dependencies:

- The editor's authoring session and its Undo and Redo history
  ([Workflow authoring undo and redo](WORKFLOW_AUTHORING_UNDO_REDO.md), 0.261.123). Change
  tracking adds no second undo stack: attribution lives on the history entries, and every revert
  or restore is recorded as a new history entry.
- The V2 workflow editor dialog (`WorkflowEditorDialog.tsx`) and its List and Flow surfaces.

No backend route, no setting, no model call, and no package are added. Diffing is local code;
there is no diff library.

## What you see

### Highlights on changed fields

A changed field is framed in its author's color and gets a text badge, so color is never the
only cue:

- **Edited**, in violet, for your own changes.
- **AI assist**, in blue, for changes an AI assist turn made. From 0.261.211 the **Ask AI** tab
  and **Draft with AI** make them; see [Workflow AI assistant](WORKFLOW_AI_ASSISTANT.md).

Beside the badge, **Previously** opens the value the field had when the editor opened, as plain
text. Values longer than 280 characters are cut short behind **Show more**. **Revert** puts that
one field back and leaves every other change alone.

A task or block that has changes shows its authors in its header. Changes with no single field to
frame, such as a block's position, a block setting edited in its own panel, or the task order,
appear as a compact notice with the same badge, Previously and Revert.

Fields inside a newly added task or block show the author badge but no Revert of their own. The
item's header carries **Added · by you** (or **Added · AI assist**) and one **Revert**, which
removes the whole item.

### Removed items and reordering

A removed task leaves a dashed **Removed task** row where it was on the List surface, with
**Restore**. Restore puts back the version of the task that was saved, in its saved position:
after the nearest earlier task that still exists, or at the start. Undo still returns the version
you had just before removing it.

On the Flow surface, removed blocks are listed in a **Removed blocks** strip above the canvas,
because the canvas has no room for inline rows. Restoring a block puts it back in its saved
region and position, selects it, and moves focus to it. The structured List surface shows the
same rows inline, in each region.

A reorder is one **Task order** change, not an edit to every task, because every change is keyed
by the task's ID rather than its position. Reverting the order puts the saved tasks back in their
saved order; a task you added keeps its slot.

### The Changes panel

**Changes** in the editor footer opens a side panel and shows how many unsaved changes there are.
The panel is built as a tab list, so later phases can add tabs beside **Changes**. From 0.261.211
**Ask AI** is the second tab, on a personal workflow you can edit when the admin has turned the
assistant on.

The Changes tab has two lists:

- **Unsaved changes**: every change, in reading order, with its before and after values as plain
  text, its author, **Jump**, and **Revert** (**Restore** for a removed item). Jump moves focus to
  the changed field, opening collapsed sections as needed. On the Flow surface it selects the
  changed block, and switches to List when the field isn't shown on Flow. On narrow screens it
  closes the panel first, so the field is visible. A jump places focus itself, so it clears any
  block focus that the step it follows requested; otherwise, on Flow, the canvas could take focus
  back from the field after a **Draft with AI** change.
- **This session**: the steps in this editing session, newest first, each marked **Edited**,
  **AI assist** or **Restore**, with its turn when it has one. **Restore to here** applies the
  workflow as it was after that step, as a new step. Nothing is deleted: the steps after it stay
  in the list, and in a structured workflow Undo takes the restore back. The last row,
  **Opened version**, restores the workflow as it was when the editor opened. When the history
  budget has dropped older steps, the list says so.

When a revert or restore records a new step while Redo steps exist, the announcement says the
Redo steps were cleared, rather than dropping them silently. Reverts, restores and Jump are keyboard
operable; the result of each revert and restore is announced politely.

On wide screens (1280 pixels and up at the default text size), the panel sits beside the editor
and the dialog widens to make room. On narrower screens the panel takes the editor's place until
you close it, and a new error closes it so the error is visible. On phone-sized screens the footer
button shows an icon and the count, so Cancel and Save workflow stay on one line. Opening the
panel focuses its tab; Escape inside the panel closes the panel, not the editor, and returns focus
to the Changes button.

### Saving

Saving your own edits is still one click.

When any unsaved change has an AI author, the first **Save workflow** opens the Changes tab with a
**Review before saving** step instead. It lists what saving does: how many changes AI assist made,
whether saving requires re-approving Run as, and that the changes become the saved workflow and
this session's history is cleared. **Confirm and save** saves; **Keep reviewing** closes the step
and moves focus to the list of changes.

### Run as

When the saved workflow runs as a Microsoft 365 account and the draft still does, the top of the
Changes tab shows **Saving requires re-approving Run as** whenever a change touches a field the
server fingerprints. The note is informational and appears whoever made the change. Saving such a
change clears the stored Run as approval, as it always has, so the account holder must approve the
new revision before it runs as them again; the note says so before you save rather than after.

### When nothing is shown

- **Read-only editors** show no highlights, no Revert, no Removed rows, and no Changes button.
  That covers viewers without edit rights, a workflow with an active run, and a workflow that
  uses something this editor can't change, such as an unsupported flow feature or a stored
  schedule it can't show exactly. Change tracking follows the editor's read-only state, so any
  later reason to open read-only is covered too.
- **New workflows** point out only AI assist changes. Everything in a workflow that has never
  been saved is new, so highlighting all of it would point out nothing. The session list still
  works, and its first row reads **New workflow**.
- **After converting a classic workflow** to the structured format in the same session, changes
  are still listed and highlighted, but Revert and Restore to here are unavailable, because the
  conversion can only be discarded as a whole. The panel explains this; Cancel discards it.

Group workflows are tracked the same way as personal ones.

## How it works

### One history, three origins

Each history entry's action now records its origin, `user`, `ai` or `restore`, and for assist
entries a turn ID (`lib/workflowAuthoringHistory.ts`). A missing origin means `user`, so existing
entries keep their retained size. The action copier validates both: the origin must be one of the
three, and a turn ID must be a nonempty string of at most 256 characters with no control
characters. Typing that coalesces into one entry never merges entries with a different origin or
turn ID, so an assist never folds into your typing, or yours into it.

History was already recorded for every definition version, so classic workflows get attribution,
the session list, Restore to here and turn reverts. Undo and Redo stay limited to structured
drafts, as before.

### Stable-ID change keys

`lib/workflowChangeTracking.ts` keys every change by a stable ID, never by an array position:

| Key | What it covers |
|---|---|
| `name`, `description`, `runner_type`, `selected_agent`, `error_handling`, `is_enabled`, `chat_capabilities_enabled`, `durable_execution`, `file_sync`, `limits`, `m365_run_as_user_id` | The workflow field of the same name |
| `model` | `model_endpoint_id` and `model_id` |
| `schedule` | `trigger_type` and `schedule`, shown as one "Trigger and schedule" change |
| `alerts` | The four alert fields |
| `definition_version` | A format conversion; listed, but not revertable on its own |
| `tasks:order`, `references:order` | The order of classic tasks, or of shared references |
| `task:<id>`, `task:<id>:<field>` | An added or removed task, or one task field (including `placement` and `run_when` in a structured flow) |
| `node:<id>`, `node:<id>:<field>` | An added or removed flow block, or one block setting, including blocks nested in regions |
| `region:<id>:order`, `region:<id>:outputs` | The order of blocks in a flow region, or its outputs |
| `reference:<id>`, `reference:<id>:name`, `reference:<id>:document` | An added or removed shared reference, or one of its fields |

IDs are escaped so a colon inside an ID can't be read as a separator. A removed block is reported
once, and carries the tasks inside it. In a structured workflow the flow owns execution order, so
the task array's order is not a change.

### Diff against the opened version

`diffWorkflowChanges(baseline, draft)` compares the draft with the opened baseline: the saved
definition when the editor opened, the saved version after each save, or a new workflow's initial
draft. Each change has a kind (`field`, `added`, `removed`, `order`, `placement` or `version`),
plain-text before and after summaries, the item it belongs to, where a removed item was, and what
Jump should focus.

### Attribution

Attribution is a map from change key to its last author and turn, stored on every history
checkpoint and computed when an entry is recorded. Each key that differs from the baseline takes
the entry's author; a key back at its baseline value loses its author. Because it is computed
against the start of a coalesced group, typing that ends where it started leaves no author.

Undo and Redo take the target checkpoint's attribution, so the highlights always agree with the
history. The current attribution survives eviction, the oversized-edit prompt, and cleared
history, so an evicted step's author is still shown. Saving resets it.

A restore keeps the author of the value it brings back: reverting to the baseline removes the
author, Restore to here takes the author the key had at that step, and a turn revert takes the
author from before the turn. A restored AI value is still AI-authored, so it still needs review
before saving. When there is no earlier author to keep, the restored value counts as your edit.

### Revert, restore, and turn revert

Every operation below is a new, undoable history entry with origin `restore`. Nothing is deleted.
Each one goes through the session's normal path, so a revert that removes blocks or affects other
references asks for confirmation exactly as Undo does.

- `revertChange(keys)` takes change keys back to their baseline values. A removed item returns in
  its saved version and position, and an added item is removed. When the revert restores exactly
  one block, the editor selects it again.
- `restoreTo(step)` applies the workflow as it was after a retained step, or `'opened'` for the
  baseline. An undone step, or one no longer retained, can't be restored to.
- `revertTurn(turnId)` reverts the keys one AI assist turn changed. A key is reverted only when
  its value is still what the turn left; a key changed afterwards is skipped. The result reports
  `reverted` and `skipped` counts, with each key's label and, for skipped keys, why. An unknown or
  evicted turn returns `unavailable`, and a turn with nothing left to revert returns `noop`.

### The assist seam

`WorkflowAuthoringSession.applyAssist(candidate, { turnId, label })` applies an AI assist
candidate as one history entry with origin `ai`. It rejects a candidate that:

- changes a field in `ASSIST_FORBIDDEN_FIELDS`: `is_enabled`, `m365_run_as_user_id`,
  `definition_version`, `id`, `user_id`, `group_id`, `url_access_enabled`
- changes any field outside `WORKFLOW_AUTHORED_FIELDS`
- adds, changes, or removes a task approval (`ASSIST_FORBIDDEN_TASK_FIELDS`)
- changes what an ID it keeps refers to

An accepted candidate takes the normal edit path: eligibility, impact confirmation, and the
history budget's oversized-edit prompt. From 0.261.211 the **Ask AI** tab calls it with each
answer, and **Draft with AI** calls it with drafted task instructions.

### The Run as consequence

`lib/workflowRunAsFingerprint.ts` mirrors the fields the server hashes in
`workflow_execution_fingerprint` (`functions_m365_workflow_binding.py`): `M365_WORKFLOW_FIELDS`,
the optional structured fields, and the Run as account itself. `workflowRunAsConsequence` is true
when the saved workflow and the draft both have a Run as account and a change covers one of those
fields. `test_workflow_run_as_fingerprint_parity.py` fails when the two lists drift.

### Performance

The diff never runs on the whole definition per keystroke. Indexes are cached per task list, flow
and definition object, and the diff and key deltas are memoized per pair of definitions. The
editor keeps every task object it did not change, so typing into one task compares only that
task. The panel reads the diff one deferred render later, so a keystroke never waits for it. The
highlights render in that deferred pass too, so every tracked field also carries its field key
(`data-workflow-field-key`) from its first render, changed or not. Jump looks for the highlighted
field, then the field key, then the changed item, so a jump made as a change lands, such as Draft
with AI's, still reaches the field on a slow device. With 100 tasks, a keystroke through the
session measured 0.17 ms in the logic tests.

## Seams for later phases

- **The assist endpoint (3b)** returns candidates; `applyAssist` is where they enter the editor.
  It already enforces the forbidden fields and approvals client-side.
- **The Ask AI tab (3c)** shipped in 0.261.211 as the second entry in `WorkflowEditorSidePanel`'s
  tab list, beside Changes. Each turn's **Undo this change** calls `revertTurn` and reports the
  reverted and skipped counts it returns. Ask AI is personal-only; change tracking itself also
  covers group workflows.
- The Confirm and save step now appears when a save includes changes from Ask AI or Draft with AI.

## Files

| File | Change |
|---|---|
| `application/v2_ui/src/lib/workflowAuthoringHistory.ts` | History origin and turn ID, validated and never coalesced across |
| `application/v2_ui/src/lib/workflowChangeTracking.ts` | New: keys, diff, attribution, labels, revert and turn-revert candidates, save predicate |
| `application/v2_ui/src/lib/workflowRunAsFingerprint.ts` | New: the client mirror of the server's fingerprint fields |
| `application/v2_ui/src/components/workflows/WorkflowAuthoringHistory.tsx` | Attribution on checkpoints; `revertChange`, `restoreTo`, `revertTurn`, `applyAssist`; the authored-fields fix |
| `application/v2_ui/src/components/workflows/WorkflowChangeTracking.tsx` | New: the context, highlights, item badges, Removed rows, side panel, toggle and Changes tab |
| `application/v2_ui/src/components/workflows/WorkflowEditorDialog.tsx` | Wires the scope, panel, Jump and the save step; frames the workflow fields |
| `WorkflowTaskFields.tsx`, `WorkflowScheduleFields.tsx`, `WorkflowStructuredFields.tsx`, `WorkflowStructuredList.tsx`, `WorkflowFlowAuthoring.tsx` | Opt-in wrappers and Removed rows, without restructuring the field blocks |
| `application/v2_ui/src/components/ui/Modal.tsx` | A `2xl` size for the editor with the panel open |
| `application/v2_ui/src/styles/theme.css` | Change colors for light and dark themes |

## Known limitations

- Long text changes show the previous value; there is no word-level inline diff yet.
- File Sync has no inline highlight. Its changes are listed in the Changes tab, and Jump goes to
  its section.
- Flow blocks have no inline Removed rows on the canvas; they are listed in the Removed blocks
  strip and the Changes tab.
- A new workflow points out only AI assist changes, so your own edits are highlighted only after
  the first save.
- Change tracking lasts for one editing session. Saving, cancelling or reopening starts fresh.

## Testing and validation

- `functional_tests/test_workflow_authoring_history.js`, `test_workflow_authoring_session.js`
  and `test_workflow_flow_authoring_commands.js` (`node --test`): origin and turn validation,
  coalescing, attribution through undo, redo and eviction, reverts and restores through the
  session, and restoring removed blocks and nested regions in place.
- `functional_tests/test_v2_workflow_change_tracking.py` with `_logic.ts` (esbuild, then node):
  stable-ID diffing where a reorder is one change, attribution through undo, redo, coalescing
  and eviction, `revertChange`, `revertTurn` and item restore, `applyAssist` accepted, rejected
  and through the oversized-edit prompt, the save predicate, the Run as consequence, and the
  100-task performance check.
- `functional_tests/test_workflow_run_as_fingerprint_parity.py`: the mirror matches the fields
  the server's fingerprint actually changes on.
- `ui_tests/test_v2_workflow_change_tracking.py` (Playwright with stubbed routes): badges,
  Previously, Revert, and Removed · Restore on List and Flow; the Changes tab's Jump, Revert and
  Restore to here; highlights following Undo and Redo; structured alert edits; one-click save;
  the Run as note; read-only editors, including one opened read-only for a stored schedule it
  can't show; a group workflow; light and dark themes; a narrow viewport;
  a new workflow; and keyboard focus staying in a schedule, Run when, output contract or final
  outputs control, with every typed character kept, while its highlight appears or clears.
- From 0.261.211, `ui_tests/test_v2_workflow_ask_ai.py` reaches the Review before saving step
  in a browser: an **Ask AI** answer is applied, and the save goes through **Confirm and save**.

## Related

- [Structured workflow alert and File Sync edits fix](../fixes/STRUCTURED_WORKFLOW_ALERT_FILE_SYNC_EDITS_FIX.md)
- [Create a workflow guide](../../guides/create-a-workflow.md), "Review your changes"
- [Chat orchestration workflows roadmap](CHAT_ORCHESTRATION_WORKFLOWS_ROADMAP.md), §5
