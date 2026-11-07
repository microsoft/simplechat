# Workflow calendar schedules

Implemented in version: **0.261.193**.

Application version tracking: `application\single_app\config.py`.

Related issue: #1544, part of #1543.

## Overview and dependencies

A scheduled workflow could only repeat at a fixed interval: every so many seconds,
minutes or hours. That can't express "every Monday at 08:00 in New York", and an
interval drifts against the local clock whenever daylight saving time starts or
ends. Calendar schedules add a second kind of schedule that runs at a local
wall-clock time in an IANA time zone:

- **daily**;
- on **weekdays**, Monday to Friday;
- **weekly**, on one or more chosen days;
- **monthly**, on a day of the month from 1 to 31.

The server works out each run's UTC instant from the local time, so a calendar
schedule keeps its local time through daylight saving changes.

This version also adds an administrator setting, **Workflow Minimum Schedule
Interval (seconds)**. It sets the shortest interval a new or changed interval
schedule may use, so authors can no longer create a workflow that runs every
second. Saved schedules are never re-checked against it.

Calendar schedules work in personal and group workflows, for both the
**Schedule** trigger (labelled **Interval** before version 0.261.202) and the
group **Monitor File Sync changes** trigger.

Dependencies:

- Python's standard `zoneinfo` module. It reads the system time zone database
  when the server has one, and the already pinned `tzdata` package
  (`tzdata==2026.3` in `application/single_app/requirements.txt`) otherwise. No
  new package is added.
- The existing workflow scheduler in `background_tasks.py`, which is unchanged.
- The native V2 workflow editor, which reads the browser's time zone with the
  standard `Intl` API. No browser dependency is added.

There's no new route, database container or setting other than the minimum
interval.

## Technical specifications

### Stored schedule shapes

An interval schedule keeps its original stored shape exactly, with no `kind`
field:

```json
{"unit": "minutes", "value": 15}
```

The interval rules are unchanged. `unit` is `seconds`, `minutes` or `hours`, and
`value` is a whole number from 1 to 59 for seconds and minutes, or 1 to 24 for
hours. A payload with `kind: "interval"` is stored in the same shape, without
`kind`.

A calendar schedule stores every calendar field:

```json
{
  "kind": "calendar",
  "frequency": "weekly",
  "days_of_week": ["monday"],
  "day_of_month": null,
  "time_of_day": "08:00",
  "timezone": "America/New_York"
}
```

| Field | Rule |
| --- | --- |
| `kind` | `calendar`. Any kind other than `interval` or `calendar` is refused. |
| `frequency` | `daily`, `weekdays`, `weekly` or `monthly`. |
| `days_of_week` | Weekly only: day names from `monday` to `sunday`, at least one. Stored lowercase, in week order, without duplicates. Stored as `[]` for other frequencies. |
| `day_of_month` | Monthly only: a whole number from 1 to 31. Stored as `null` for other frequencies. |
| `time_of_day` | 24-hour `HH:MM`, from `00:00` to `23:59`. |
| `timezone` | An exact IANA time zone name that the server's time zone database has, such as `America/New_York`. Names are case-sensitive. `Factory`, `localtime` and `posixrules` aren't offered. |

Surrounding spaces are removed from text fields. A field the frequency doesn't
use is dropped rather than checked, so switching a weekly schedule to daily
doesn't fail on its old days.

A refused schedule returns the save route's reviewed 400 with one of these
messages:

| Problem | Message |
| --- | --- |
| Unknown kind | Schedule kind must be interval or calendar. |
| Unknown frequency | Schedule frequency must be daily, weekdays, weekly or monthly. |
| A day that isn't a day name | Schedule days of the week must be day names from monday to sunday. |
| A weekly schedule with no days | Choose at least one day of the week for a weekly schedule. |
| A day of the month that isn't a whole number | Schedule day of the month must be a whole number. |
| A day of the month outside 1 to 31 | Schedule day of the month must be between 1 and 31. |
| A time that isn't `HH:MM` | Schedule time must use 24-hour HH:MM format, such as 08:00. |
| An unknown time zone | Schedule time zone must be an IANA time zone name, such as America/New_York. |
| An interval below the administrator's minimum | This schedule runs more often than the administrator allows. Choose an interval of at least 1 hour. |

The rules live in one module, `functions_workflow_schedules.py`, which imports
only the standard library and the reviewed validation error. The personal and
group saves both call `_normalize_schedule` in `functions_personal_workflows.py`.

### Next runs

`next_workflow_schedule_run(schedule, from_time)` returns the first run strictly
after `from_time`, as UTC ISO text. It follows RFC 5545:

- a local time that doesn't exist, because the clocks went forward past it, runs
  at the instant the UTC offset from before the change gives it. On the new
  clock that's later by the size of the gap, so 02:30 in New York runs at 03:30;
- a local time that happens twice, because the clocks went back, runs once, at
  its first occurrence;
- a monthly day that a month doesn't have runs on that month's last day.

Examples, computed by the module:

| Schedule | Runs (UTC) |
| --- | --- |
| Mondays 08:00 America/New_York, across 8 March 2026 | 2 March 13:00, 9 March 12:00, 16 March 12:00 |
| Mondays 08:00 America/New_York, across 1 November 2026 | 26 October 12:00, 2 November 13:00 |
| Daily 02:30 America/New_York, across the spring-forward night | 7 March 07:30, 8 March 07:30 (03:30 local), 9 March 06:30 |
| Daily 01:30 America/New_York, across the fall-back night | 31 October 05:30, 1 November 05:30 (the first 01:30), 2 November 06:30 |
| Weekdays 07:30 Europe/London, from Friday 27 March 2026 | 30 March 06:30, 31 March 06:30, 1 April 06:30 |
| Monthly on day 31, 08:00 UTC, in 2026 | 31 January, 28 February, 31 March, 30 April |
| Monthly on day 31, 08:00 UTC, in February 2028 | 29 February |

`compute_next_run_at` in `functions_personal_workflows.py` uses this for a
calendar schedule and the unchanged interval arithmetic otherwise. Group
workflows use the same function. A save recomputes `next_run_at` when the
workflow is new, is re-enabled, or changes its trigger or schedule, or when
`next_run_at` is missing. A disabled or manual workflow has no next run.

If a stored calendar schedule no longer validates, for example because a later
time zone database release drops its zone, the workflow has no next run and the
server logs `[Workflows] Calendar schedule could not compute a next run.` with
the workflow ID. It isn't run at a guessed time. Saving the workflow again names
the problem.

### Scheduler and catch-up

The scheduler in `background_tasks.py` isn't changed. It checks for due
workflows every 5 seconds. When it queues a durable run, or when a synchronous
run finishes, it sets the next run from the current time. So a workflow whose
run was missed while the scheduler was stopped runs once when it catches up,
then waits for the first scheduled time after that, exactly as an interval
workflow does. It doesn't replay each missed occurrence.

The scheduler never reads the minimum interval setting.

### Readable labels

A schedule is described the same way wherever it appears:

| Schedule | Label |
| --- | --- |
| Daily at 07:00 UTC | Daily 07:00 UTC |
| Weekdays at 07:30 in London | Weekdays 07:30 Europe/London |
| Mondays at 08:00 in New York | Mondays 08:00 America/New_York |
| Mondays and Wednesdays at 08:00 in New York | Mondays and Wednesdays 08:00 America/New_York |
| Day 31 of each month at 18:00 in Tokyo | Monthly on day 31 (or last day), 18:00 Asia/Tokyo |
| A group File Sync monitor on weekdays | Monitor File Sync: Weekdays 07:30 Europe/London |
| Every 15 minutes | Every 15 minutes |
| Every hour | Every hour |

Days 29, 30 and 31 add "(or last day)", because some months don't have them.

The labels come from `workflow_schedule_label(trigger_type, schedule)` on the
server and `workflowScheduleLabel` in the V2 editor. The classic workflow list
shows the same calendar labels, and keeps its existing wording for intervals.

### Administrator minimum interval

| Setting | Key | Default | Range |
| --- | --- | --- | --- |
| Workflow Minimum Schedule Interval (seconds) | `workflow_min_schedule_interval_seconds` | 1 | 1 to 86,400 |

One second is the shortest interval a schedule could already use, so the
default changes nothing. The setting is in **Admin Settings > Workflow** in both
the classic and V2 admin pages. Both validate it with
`validate_workflow_min_schedule_interval_seconds` in
`functions_workflow_limits.py`, which refuses anything other than a whole number
in range instead of clamping it.

Both saves apply it in `_normalize_schedule`:

- `workflow_schedule_minimum_applies` decides whether it applies. It applies to
  an interval schedule on a new workflow, on a workflow that wasn't scheduled
  before, or whose schedule changed. It doesn't apply when the stored schedule
  is the same, including when the workflow switches between the Interval and
  Monitor File Sync changes triggers, or is turned off and on. It never applies
  to a calendar schedule, which runs at most once a day.
- `enforce_workflow_schedule_minimum` refuses an interval shorter than the
  minimum, naming the minimum in the largest whole unit ("1 hour", "5 minutes",
  "90 seconds").
- The setting is read only when the minimum applies. If the stored setting isn't
  a valid minimum, the save is refused with the generic "Invalid workflow
  settings. Review the task, runner, trigger, and document inputs." error rather
  than skipping the check.

### Microsoft 365 Run as approvals

`schedule` is one of the fields in the Microsoft 365 Run as approval
fingerprint (`functions_m365_workflow_binding.py`). Existing interval
workflows keep their stored schedule byte for byte, and re-saving one without
changing it produces the same schedule, so their fingerprints and approvals
don't change. Changing a workflow's schedule, including to a calendar
schedule, changes its fingerprint. Since 0.261.229 the new revision needs
renewed approval only when someone other than the Run as user saved it; a
schedule change the Run as user saved runs as them without asking.

### Editor options, routes and the MCP summary

There's no new route. The existing editor options routes,
`GET /api/user/workflows/editor-options` and
`GET /api/group/workflows/editor-options?group_id=...`, add a `schedule` block:

```json
{
  "kinds": ["interval", "calendar"],
  "units": ["seconds", "minutes", "hours"],
  "frequencies": ["daily", "weekdays", "weekly", "monthly"],
  "days_of_week": ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"],
  "timezones": ["Africa/Abidjan", "..."],
  "min_interval_seconds": 1
}
```

`timezones` is the sorted list of zones a calendar schedule may use on this
server, built once per process.

The personal and group save routes accept the calendar shape in `schedule`.

The inbound MCP workflow summary (`_serialize_personal_workflow_summary` in
`functions_mcp_server_tools.py`) adds `schedule`, the normalized schedule or
`{}` for a manual or unreadable one, and `schedule_label`.

### V2 editor

`WorkflowScheduleFields.tsx` renders the schedule for both scopes, beside the
**Trigger** select in `WorkflowEditorDialog.tsx`:

- **Repeats** chooses **At an interval**, **Daily**, **Weekdays (Monday to
  Friday)**, **Weekly on chosen days** or **Monthly on a day of the month**. The
  trigger stays **Schedule**, or **Monitor File Sync changes** for a group
  monitor.
- **Days of the week** checkboxes appear for weekly schedules, and **Day of the
  month** for monthly schedules, with a note that months without the day run on
  their last day.
- **Time** is a time input, which the browser displays in its own clock format
  and the editor saves as 24-hour `HH:MM`. **Time zone** is a text field that
  suggests the server's zones as you type.
- A new calendar schedule starts at 09:00 in the browser's time zone, when the
  server lists it. Otherwise it starts in UTC, with a note naming the browser's
  zone.
- The editor reads the schedule back ("Schedule: Mondays 08:00 America/New_York.
  Runs follow local time in this zone, including daylight saving changes."), and
  the workflow list shows "Schedule: Mondays 08:00 America/New_York".
- Switching to another cadence and back keeps the days, time and zone chosen
  earlier.

Before saving, the editor checks the same rules as the server, with the same
messages, including the minimum for a new or changed interval
(`workflowScheduleForSave` and the save checks in `lib/workflowSettings.ts`).
`normalizeWorkflowSchedule` in `lib/workflowEditor.ts` keeps an interval
schedule as `{unit, value}` when the editor round-trips it.

From version 0.261.202, a scheduled workflow whose stored schedule the editor
can't show exactly opens read-only. That's a kind, calendar frequency, interval
unit or weekly day the server doesn't define, a `seconds` or `minutes` unit
stored other than exactly (the scheduler runs any other unit text as hours), or
an interval value that isn't a whole number. Only a newer server, a direct write
or a record saved before a rule existed can store one.
`normalizeWorkflowDefinition` keeps the schedule exactly as stored and sets the
read-only reason, the schedule fields show "This workflow's schedule can't be
shown or changed in this editor.", and `workflowForSave` refuses to build a
payload. `normalizeWorkflowSchedule` reads through `workflowScheduleForEditor`
in `lib/workflowSettings.ts`, which changes only what the server's save
canonicalizes and keeps a whole-number value the save refuses for validation to
name. A manual workflow doesn't use its schedule, so it stays editable. See
[the fix](../fixes/V2_WORKFLOW_UNSUPPORTED_SCHEDULE_FIX.md).

### Classic workspace editor

The classic editor edits only fixed intervals. `workflowNeedsNativeEditor` in
`static/js/workspace/workspace_workflows.js` now sends a calendar workflow to V2
with "This workflow uses a calendar schedule. Open V2 to edit it without losing
its configuration. Run and Cancel remain available here." Saving it in the
classic form would otherwise replace the calendar schedule. The classic list
shows calendar labels.

### Files

| File | Change |
| --- | --- |
| `application/single_app/functions_workflow_schedules.py` | New: schedule rules, next runs, labels and editor options |
| `application/single_app/functions_personal_workflows.py` | `_normalize_schedule` and `compute_next_run_at` |
| `application/single_app/functions_group_workflows.py` | Passes the stored workflow and settings to `_normalize_schedule` |
| `application/single_app/functions_workflow_limits.py` | The minimum interval's range, validation and getter |
| `application/single_app/functions_settings.py` | The setting's default and update validation |
| `application/single_app/admin_settings_fields.py` | The V2 admin field |
| `application/single_app/route_frontend_admin_settings.py` | The classic admin save |
| `application/single_app/templates/admin/_panes/workflow.html` | The classic admin field |
| `application/single_app/functions_workflow_editor.py` | The editor options' `schedule` block |
| `application/single_app/functions_mcp_server_tools.py` | `schedule` and `schedule_label` in the MCP summary |
| `application/single_app/static/js/workspace/workspace_workflows.js` | Classic labels and routing to V2 |
| `application/v2_ui/src/components/workflows/WorkflowScheduleFields.tsx` | New: V2 schedule fields |
| `application/v2_ui/src/components/workflows/WorkflowEditorDialog.tsx` | Uses the schedule fields |
| `application/v2_ui/src/components/workflows/WorkflowFileSyncFields.tsx` | Monitor help text refers to the schedule, not only an interval |
| `application/v2_ui/src/lib/workflowSettings.ts` | Client schedule rules and labels |
| `application/v2_ui/src/lib/workflowEditor.ts` | Schedule types, options and round-tripping |
| `application/v2_ui/src/pages/workspace/WorkflowsSection.tsx` | Schedule labels in the list |

## Usage

### Enable or configure

Calendar schedules are available wherever personal or group workflows are.
Nothing needs turning on.

To stop authors creating schedules that run every few seconds, set **Workflow
Minimum Schedule Interval (seconds)** in **Admin Settings > Workflow**. For
example, 300 refuses a new or changed interval shorter than 5 minutes. See
[Workflow settings](../../admin/workflow.md).

### Create "Mondays 08:00 America/New_York"

1. In V2, open **Workflows** in a personal or group workspace, then choose
   **Create workflow** or edit a workflow.
2. Set **Trigger** to **Schedule**.
3. Set **Repeats** to **Weekly on chosen days**, and select **Monday**.
4. Set **Time** to 08:00 and **Time zone** to `America/New_York`.
5. Save. The workflow list shows "Schedule: Mondays 08:00 America/New_York".

The workflow runs at 12:00 UTC while New York is on daylight saving time and at
13:00 UTC otherwise.

The author guide is [Create a workflow](../../guides/create-a-workflow.md).

## Testing and validation

| Test | Covers |
| --- | --- |
| `functional_tests/test_workflow_calendar_schedules.py` | Normalization; next runs across spring-forward and fall-back nights, weekly on several days, weekdays, monthly day 31 in short months and February in leap and other years, and a year of runs checked day by day; catch-up; refused time zones, times, days and kinds; labels; personal and group saves through the real save route bodies over doubled storage, with the same results in both scopes; the minimum applying only to new or changed interval schedules; unchanged legacy interval shapes and Microsoft 365 Run as fingerprints, against values captured before this change; the editor options; the MCP summary |
| `functional_tests/test_workflow_calendar_schedule_client_parity.py` | The V2 editor's schedule rules, run in Node, against the server's for the same raw schedules and drafts, including the minimum and the labels |
| `ui_tests/test_v2_workflow_calendar_schedules.py` | The V2 editor: "Mondays 08:00 America/New_York" saved, listed and reopened in both scopes; stored calendar schedules re-saved unchanged; the UTC fallback; problems named before saving; the minimum |
| `ui_tests/test_workflow_loop_admin_limits.py` | The minimum interval field in the classic and V2 admin pages |
| `ui_tests/test_workflow_classic_advanced_guard.py` | The classic editor sending calendar workflows to V2 |

Performance: listing the available zones reads the whole time zone database,
so the list is built once per process and cached. Working out a next run looks
at no more than 16 candidate days, or 4 candidate months.

Known limitations:

- The zones offered are the ones the server's time zone database has. A browser
  whose zone the server doesn't list starts a new schedule in UTC and says so.
- A stored calendar schedule whose zone a later database release removes stops
  being scheduled until it's saved again with a valid zone.
- Runs start when the scheduler next checks, within a few seconds of the
  scheduled time.

From version 0.261.202, every run of a calendar workflow tells the model the
run's local date and time, so relative times in its instructions, such as "this
week", resolve in the schedule's time zone. See
[Workflow draft service](WORKFLOW_DRAFT_SERVICE.md#calendar-run-time-in-the-prompt).
