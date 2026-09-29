# V2 Workflow Unsupported Schedule Fix (v0.261.197)

**Fixed in version: 0.261.197**

The application version is tracked in `application/single_app/config.py`.

Refs #1545 and #1544. This is a follow-up from the reviews of the calendar
schedules change (#1561) and of the workflow draft service change (#1566).

## Issue

A workflow's stored schedule is either an interval schedule or, from version
0.261.193, a calendar schedule. The save routes refuse or canonicalize every
schedule they store, but a newer server, a direct write, or a record saved
before a rule existed can leave a schedule the V2 workflow editor has no fields
for. The editor didn't expect one, and put a schedule of its own in its place:

- A schedule of another kind, such as `cron`, was shown as **At an interval**,
  every 15 minutes.
- A calendar schedule with a frequency the server doesn't define, such as
  `fortnightly` or a newer server's `hourly`, was shown as **Daily**.
- An interval schedule with a unit the server doesn't define was shown in
  minutes, so `{unit: 'days', value: 2}` became every 2 minutes, 1,440 times as
  often. A unit stored as `HOURS`, which the server reads as hours, became
  minutes too.
- An interval value that couldn't be read as a number became 15, and a value of
  0 or less became 1.
- A weekly day the server doesn't define was dropped without a word.

Saving the workflow for any reason, such as editing its description, stored the
substitute. The server accepted it, because it was a valid schedule, and the
general minimum interval defaults to 1 second, so nothing stopped the workflow
then running on a cadence nobody chose.

## Root cause

`normalizeWorkflowSchedule` in `application/v2_ui/src/lib/workflowEditor.ts`
built the editor's schedule from whatever it could read and filled each gap
with a default. Any kind but `calendar` was an interval, an unknown frequency
was `daily`, unknown weekly days were dropped, any unit but exactly `seconds`,
`minutes` or `hours` was `minutes`, and `numberInRange` turned a value it
couldn't read as a number into 15 and raised any value below 1 to 1.
`normalizeWorkflowDefinition` used it for every stored workflow, so the
editor's draft, and the payload `workflowForSave` built from it, carried the
substitute.

## Fix

The editor now reads a stored schedule exactly as the server's
`normalize_workflow_schedule` does, and changes only what that save would
canonicalize anyway. A scheduled workflow whose schedule it can't show exactly
opens read-only, with its schedule kept exactly as stored.

### Schedules the editor can't show

`workflowScheduleForEditor` in `lib/workflowSettings.ts` returns the schedule
the editor shows and saves, or nothing when it can't show the stored one
exactly. `workflowScheduleSupported` reports which. The editor can't show:

- a kind other than `interval` or `calendar`. A missing or empty kind is
  interval, and the text is trimmed and lower-cased, as on the server.
- a calendar frequency other than `daily`, `weekdays`, `weekly` or `monthly`
  once trimmed and lower-cased, including a missing frequency.
- weekly days that aren't a list, or that name anything but a day of the week.
- an interval unit other than `seconds`, `minutes` or `hours` once trimmed and
  lower-cased, including a missing unit.
- a `seconds` or `minutes` unit stored other than exactly, such as ` Minutes `
  or `SECONDS`. The scheduler (`_build_schedule_delta`) compares the stored
  unit exactly and runs any other unit as hours, so
  `{unit: ' Minutes ', value: 2}` runs every 2 hours today, and saving it as
  `minutes` would make it run every 2 minutes. An `hours` unit in any case or
  padding already runs as hours, so it opens editable and saves as `hours`.
- an interval value that isn't a JSON whole number: text, a fraction, a
  boolean, `null`, or no value. The scheduler runs a fraction as stored while a
  save truncates it, and it can't run text or a missing value at all, so any
  value the editor showed would be one it chose.

### Values kept for validation to name

A whole-number value the save refuses isn't replaced either. The editor shows
it as stored, validation names it with the save route's message, and the save
stays blocked until the author corrects it:

- a whole-number interval value outside its range, such as 0, 90 minutes, or
  -3 hours;
- an empty weekly day list;
- a time or time zone the save refuses;
- a monthly day that isn't a whole number, which shows as empty while
  validation asks for a day.

### What a save canonicalizes

A schedule that differs only in what the server's save canonicalizes opens
editable and shows the schedule the save stores. That covers the case and
surrounding whitespace of the kind, an `hours` unit, the frequency, the days,
the time and the time zone; the order and repeats of the weekly days; a
whole-number float such as `5.0`; and fields a kind or frequency doesn't use.
The calendar scheduler normalizes a schedule before it computes a run, so none
of this changes when a calendar workflow runs.

### Read-only behaviour

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
  so a leftover schedule there doesn't make the workflow read-only. Switching
  such a workflow to **Schedule** starts from the usual 15-minute interval,
  which `normalizeWorkflowSchedule` still returns for a schedule the editor
  can't show.

### Related change

The V2 **Trigger** option for scheduled workflows is now labelled **Schedule**
instead of **Interval**, because it offers calendar schedules as well as fixed
intervals. The stored `trigger_type` is still `interval`. The classic editor
keeps **Interval Schedule**.

### Files modified

| File | Change |
| --- | --- |
| `application/v2_ui/src/lib/workflowSettings.ts` | `workflowScheduleForEditor` and `workflowScheduleSupported`, which read a stored schedule as the server does, and the shared kind and weekly-day readings |
| `application/v2_ui/src/lib/workflowEditor.ts` | `WORKFLOW_UNSUPPORTED_SCHEDULE_REASON`, the read-only reading in `normalizeWorkflowDefinition`, and `normalizeWorkflowSchedule`, which now reads through `workflowScheduleForEditor` |
| `application/v2_ui/src/components/workflows/WorkflowScheduleFields.tsx` | Hides the schedule fields and shows the note for an unsupported schedule |
| `application/v2_ui/src/components/workflows/WorkflowEditorDialog.tsx` | The **Schedule** trigger label |
| `functional_tests/test_v2_workflow_unsupported_schedule_readonly.py` | New functional test |
| `ui_tests/test_v2_group_workflow_file_sync.py` | The trigger label in its option lists |
| `ui_tests/test_v2_workflow_calendar_schedules.py` | The read-only dialog in both scopes, for an unknown kind, frequency and unit |

## Testing

`functional_tests/test_v2_workflow_unsupported_schedule_readonly.py` runs the
production TypeScript in Node against records saved by the real personal and
group save routes, whose schedules were then replaced as a newer server or a
direct write would:

- personal and group interval workflows, a group File Sync monitor, and a
  personal File Sync workflow open read-only with the schedule kept as stored,
  for 15 schedules: an unknown kind; an unknown, newer or missing frequency;
  weekly days with an unknown name or that aren't a list; an unknown or missing
  unit; padded and upper-case `minutes` and `seconds` units; and a text,
  fractional, boolean, `null` or missing value. `workflowForSave` refuses each
  one, and no label is shown;
- sending each stored record back as it is through the real save route is
  refused, or stores a different schedule, which is why read-only is the only
  safe reading;
- for 8 stored units, the editor opens an interval schedule editable only when
  the real `compute_next_run_at` runs it as the editor would save it;
- 5 schedules that differ only in what a save canonicalizes, including `HOURS`
  and ` Hours `, open editable, show the canonical schedule, and save it through
  the real route in both scopes;
- 5 values the save refuses (whole-number values of 0, 90 minutes and -3 hours,
  an empty weekly day list, and a text monthly day) stay editable, validation
  names each with the route's message, and the route refuses them;
- `workflowScheduleSupported` agrees with an independent reading of the
  server's rules for every schedule in the calendar parity cases, 20 kind
  values, and all the cases above, and for each supported schedule the editor
  saves exactly what the server reads from the stored one;
- a manual workflow with a leftover schedule stays editable, and its save
  through the real route stores no schedule;
- supported interval and calendar schedules are never read-only;
- the unsupported task schema reason still takes precedence.

The V2 UI test `test_v2_workflow_calendar_schedules.py` opens a workflow with an
unknown kind (`cron`), an unknown frequency (`fortnightly`) and an unknown unit
(`days`) in both scopes, and checks the read-only reason, the note, that
**Repeats** and **Save workflow** are absent, and that nothing is written.

## Validation

- The functional test passes all 463 cases, and the V2 UI test passes all six
  read-only cases.
- Each rule is load-bearing. Removing the frequency guard, the unit guard, the
  exact `seconds` and `minutes` rule, the whole-number rule, or the weekly day
  check fails the functional test. Restoring the old frequency and unit
  substitution in the built bundle fails the frequency and unit UI cases in both
  scopes.

| | Before | After |
| --- | --- | --- |
| Open a workflow with an unsupported kind, frequency, unit, weekly day or value | Shown as another schedule | Read-only, with the reason and a note |
| Edit and save it | The stored schedule is replaced by the substitute | No save is possible; the schedule is kept |
| `{unit: 'days', value: 2}` | Saved as every 2 minutes | Read-only; kept |
| `{unit: 'HOURS', value: 2}` | Saved as every 2 minutes | Editable; saved as every 2 hours |
| `{unit: ' Minutes ', value: 2}`, which runs every 2 hours | Saved as every 2 minutes | Read-only; kept |
| A calendar frequency of `fortnightly` | Saved as daily | Read-only; kept |
| An interval value of 0 | Saved as 1 | Shown as 0; validation names the range and blocks the save |
| Manual workflow with a leftover schedule | Editable | Editable; the save stores no schedule, as before |
| Interval and calendar workflows | Editable | Editable, unchanged |
