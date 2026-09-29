# V2 Workflow Unsupported Schedule Fix (v0.261.197)

**Fixed in version: 0.261.197**

The application version is tracked in `application/single_app/config.py`.

Refs #1545 and #1544. This is a follow-up from the review of the calendar schedules
change (#1561).

## Issue

A workflow's stored schedule is either an interval schedule or, from version
0.261.193, a calendar schedule. The save routes refuse any other `schedule.kind`,
so only a newer server or a direct write can store one. The V2 workflow editor
didn't expect one.

Opened in V2, a schedule of another kind was shown as **At an interval**, every
15 minutes. Saving the workflow for any reason, such as editing its description,
replaced the stored schedule with that 15-minute interval. The workflow then ran
on a cadence nobody chose.

## Root cause

`normalizeWorkflowSchedule` in `application/v2_ui/src/lib/workflowEditor.ts`
read every schedule whose kind wasn't `calendar` as an interval schedule. It
built `{unit, value}` from the stored fields and fell back to
`{unit: 'minutes', value: 15}` when they were missing. `normalizeWorkflowDefinition`
used it for every stored workflow, so the editor's draft, and the payload
`workflowForSave` built from it, carried the substitute.

## Fix

The editor now reads a schedule's kind exactly as the server's
`normalize_workflow_schedule` does. A scheduled workflow whose stored schedule is
of a kind it doesn't support opens read-only, with its schedule kept exactly as
stored.

- `workflowScheduleKindSupported` in `lib/workflowSettings.ts` reports whether a
  stored schedule is an interval or calendar schedule. It uses the same kind
  reading as `workflowScheduleForSave`: a missing or empty kind is interval, and
  the text is trimmed and lower-cased, as on the server.
- `normalizeWorkflowDefinition` in `lib/workflowEditor.ts` keeps an unsupported
  schedule as stored, for the interval and File Sync triggers, and sets
  `editor_readonly_reason` to "This workflow uses a schedule this editor does not
  support. Its original schedule has been retained and editing is disabled."
  The existing reason for an unsupported task schema takes precedence when both
  apply.
- `flowUnsupportedReason` already returns `editor_readonly_reason` first, so the
  dialog opens read-only and shows the reason, and `workflowForSave` already
  refuses a draft that has one. Nothing is written.
- `WorkflowScheduleFields.tsx` shows neither the interval nor the calendar fields
  for such a schedule, hides **Repeats**, and says "This workflow's schedule
  can't be shown or changed in this editor."
- A manual workflow doesn't use its schedule, and the server stores none for it,
  so a leftover schedule there doesn't make the workflow read-only.
  `normalizeWorkflowSchedule` is unchanged, so switching such a workflow to
  **Schedule** starts from the usual interval.

### Related change

The V2 **Trigger** option for scheduled workflows is now labelled **Schedule**
instead of **Interval**, because it offers calendar schedules as well as fixed
intervals. The stored `trigger_type` is still `interval`. The classic editor
keeps **Interval Schedule**.

### Files modified

| File | Change |
| --- | --- |
| `application/v2_ui/src/lib/workflowSettings.ts` | `workflowScheduleKindSupported`, and the shared kind reading |
| `application/v2_ui/src/lib/workflowEditor.ts` | `WORKFLOW_UNSUPPORTED_SCHEDULE_REASON`, and the read-only reading in `normalizeWorkflowDefinition` |
| `application/v2_ui/src/components/workflows/WorkflowScheduleFields.tsx` | Hides the schedule fields and shows the note for an unsupported schedule |
| `application/v2_ui/src/components/workflows/WorkflowEditorDialog.tsx` | The **Schedule** trigger label |
| `functional_tests/test_v2_workflow_unsupported_schedule_readonly.py` | New functional test |
| `ui_tests/test_v2_group_workflow_file_sync.py` | The trigger label in its option lists |
| `ui_tests/test_v2_workflow_calendar_schedules.py` | The read-only dialog in both scopes |

## Testing

`functional_tests/test_v2_workflow_unsupported_schedule_readonly.py` runs the
production TypeScript in Node against records saved by the real personal and
group save routes, whose schedules were then replaced as a newer server would:

- personal and group interval workflows, a group File Sync monitor, and a
  personal File Sync workflow open read-only with the schedule kept as stored;
  `workflowForSave` refuses them, and no label is shown;
- the real save route refuses the stored record sent back as it is, with the
  schedule kind message and no write, which is why read-only is the only safe
  reading;
- a manual workflow with a leftover schedule stays editable, and its save
  through the real route stores no schedule;
- supported interval and calendar schedules are never read-only;
- `workflowScheduleKindSupported` agrees with `normalize_workflow_schedule` for
  20 kind values, including padded, upper-case, empty, numeric, boolean, list and
  object kinds;
- the unsupported task schema reason still takes precedence.

The V2 UI test `test_v2_workflow_calendar_schedules.py` opens such a workflow in
both scopes and checks the read-only reason, the note, that **Repeats** and
**Save workflow** are absent, and that nothing is written.

## Validation

| | Before | After |
| --- | --- | --- |
| Open a workflow with an unsupported schedule | Shown as every 15 minutes | Read-only, with the reason and a note |
| Edit and save it | The schedule is replaced by a 15-minute interval | No save is possible; the schedule is kept |
| Manual workflow with a leftover schedule | Editable | Editable; the save stores no schedule, as before |
| Interval and calendar workflows | Editable | Editable, unchanged |
