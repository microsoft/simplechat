# Workflow Settings Reviewed Messages Fix (v0.261.149)

## Issue

When a workflow save was refused for its File Sync, schedule or trigger
settings, both save routes answered with the same message: "Invalid workflow
settings. Review the task, runner, trigger, and document inputs." Nothing said
which rule failed. The V2 editor checked most of these rules itself for group
workflows. For personal workflows it checked only that an interval was
positive, so a personal interval of 100 minutes passed the editor and was then
refused with the generic message.

Fixed in version: **0.261.149**, tracked in `application/single_app/config.py`.

## Root cause

The File Sync normalizers, `_normalize_schedule` and the trigger rules in
`save_personal_workflow` and `save_group_workflow` raised plain `ValueError`s.
The routes turn every `ValueError` into the generic message, because most
`ValueError` text can carry caller data. Version 0.261.144 introduced a reviewed
error class for alert settings, but these rules never used it.

## Technical details

### Reviewed errors and codes

Each rule now raises `WorkflowPublicValidationError` with a reviewed, data-free
message: it names fixed values and limits, never caller text. The save routes
return each error's `code` beside the message:

| Code | Raised by |
|---|---|
| `invalid_workflow_settings` | File Sync, schedule and trigger rules |
| `invalid_workflow_alerts` | Alert settings (`WorkflowAlertValidationError`, unchanged since 0.261.144) |
| `file_sync_source_unavailable` | A selected source was deleted; see the [save after deletion fix](WORKFLOW_SAVE_AFTER_DELETION_FIX.md) |

The messages:

| Rule | Message |
|---|---|
| Schedule unit | Schedule unit must be seconds, minutes or hours. |
| Schedule value | Schedule value must be a whole number. |
| Schedule range | Schedule value for {unit} must be between 1 and {59 or 24}. |
| File Sync wait mode | File Sync wait mode must be complete or queued. |
| File Sync continue mode | File Sync continue mode must be always or changed. |
| Queue only with Only when files changed | To continue only when changes are found, File Sync must wait for the sync to complete. |
| Group File Sync off | Group File Sync must be enabled before a group workflow can use File Sync sources. |
| A source from another group | Group workflows can only use File Sync sources from this group. |
| No personal sources selected | Select at least one File Sync source for this workflow. |
| No group sources selected | Select at least one group File Sync source for this workflow. |
| Trigger missing | Trigger type is required. |
| Trigger not supported | Trigger type must be manual, interval or file_sync. |
| Monitor trigger without File Sync before run | Monitor File Sync Changes workflows require File Sync before run. |
| Monitor trigger without waiting | Monitor File Sync Changes workflows must wait for sync completion. |
| Monitor trigger without changed-only | Monitor File Sync Changes workflows must continue only when changes are found. |

A few texts were tidied, since clients had never seen them: the list
punctuation, "a whole number" instead of "an integer", and the Queue-only rule.
A schedule value of JSON `Infinity` used to give a 500; it now gets the
whole-number message.

Everything else keeps the generic message: a missing name, the runner type,
agent availability, Analyze and document-action refusals, and URL access
limits.

### The V2 editor

The new `lib/workflowSettings.ts` mirrors these rules in both scopes, in the
server's order, with the same messages. It follows Python's text, strip,
boolean and integer semantics, so the editor refuses exactly what the server
refuses before sending. It replaces the group-only checks from 0.261.141 and the
personal positive-interval check.

The editor keeps one rule of its own: at most 10 File Sync sources.

`GET /api/group/workflows/file-sync-sources` now also returns
`file_sync_enabled`. It is computed by the same `is_file_sync_enabled_for_group`
call the save uses. Before, "File Sync off" and "no sources" both returned an
empty list. When File Sync is off, the editor now says "Group File Sync is not
enabled, so this group's sources cannot be listed.", applies the save's rule,
and doesn't mark saved sources as gone.

The classic editor already shows the server's message, so it shows the reviewed
text without a change.

### Files modified

- `functions_workflow_definitions.py`: the error codes, and the new subclasses.
- `functions_workflow_alerts.py`: alert errors raise
  `WorkflowAlertValidationError`. The texts and the regex check are unchanged.
- `functions_personal_workflows.py` and `functions_group_workflows.py`: the
  reviewed raises.
- `route_backend_workflows.py`: the save routes return `exc.code`, and the
  sources route returns `file_sync_enabled`.
- `application/v2_ui/src/lib/workflowSettings.ts` (new), `workflowEditor.ts`,
  `workflowAlerts.ts`, and `components/workflows/WorkflowEditorDialog.tsx` and
  `WorkflowFileSyncFields.tsx`.

## Testing

| Suite | Cases | What it pins |
|---|---|---|
| `functional_tests/test_workflow_settings_reviewed_messages.py` | 93, shared with the deletion fix | Each rule's message and code on both routes; group File Sync off; the non-finite schedule value; valid settings still saving; other errors staying generic |
| `functional_tests/test_group_workflow_file_sync_client_parity.py` | 173 | The production TypeScript under Node against the real save routes, with the messages compared as well as the outcome. The two divergences, the 10-source limit and a deleted personal source, are pinned |
| `functional_tests/test_group_workflow_file_sync_enabled_seam.py` | 22 | `file_sync_enabled` equals the save's File Sync gate across the File Sync states, the admin-only setting and the caller's app roles |
| `functional_tests/test_workflow_settings_client.js` | 7 | The client mirror |
| `ui_tests/test_v2_workflow_settings_errors.py` | 6, shared with the deletion fix | Personal schedules checked before saving with the server's message, and the File-Sync-off state |
| `functional_tests/test_workflow_alert_reviewed_messages.py` | 75 | Alert errors unchanged; its "stays generic" case now uses the runner type |

## Validation

- Before: every File Sync, schedule and trigger refusal said "Invalid workflow
  settings. Review the task, runner, trigger, and document inputs."
- After: it names the rule, and the V2 editor shows the same message before
  sending.

## Related

- [Workflow Save After Deletion Fix](WORKFLOW_SAVE_AFTER_DELETION_FIX.md)
- [Workflow Alert Removed Task Save Fix](WORKFLOW_ALERT_REMOVED_TASK_SAVE_FIX.md)
- [V2 Group Workflows](../features/V2_GROUP_WORKFLOWS.md)
