# V2 Workflow Alert Editing (v0.261.144)

## Overview

Personal and group workflows can now have their alerts set up and changed in
the native V2 workflow editor. Before this release, V2 kept a workflow's stored
alert settings but couldn't change them. Group workflows only showed a read-only
summary, with a link to the classic editor for version 1 workflows. Every V2
save converts a workflow to a definition the classic editor refuses, so a
workflow created or saved in V2 could never get alerts at all.

Implemented in version: **0.261.144**, tracked in
`application/single_app/config.py`.

Alert evaluation, notification delivery and the workflow runtime are unchanged.
No setting, route or container is added.

## What an alert configuration is

A workflow stores four alert fields, normalized by
`normalize_workflow_alert_settings` in `functions_workflow_alerts.py`:

| Field | Values |
|---|---|
| `alert_mode` | `off`, `every_run`, `rules` |
| `alert_priority` | `none`, `low`, `medium`, `high`, used by `every_run` |
| `alert_rules` | Up to 20 rules |
| `alert_evaluation.on_error` | `skip` or `alert`, for model-evaluated rules that can't be judged |

Each rule has:
- an optional name, up to 120 characters. An empty name is replaced by a
  description of the condition;
- whether it is enabled;
- a severity: `info`, `low`, `medium`, `high` or `critical`;
- a delivery: `default`, `notify_only` or `popup`. By default, info and low go to
  the notification bell, and medium and above open the pop-up alert;
- a scope: the final output, any task's output, or one task. Only conditions
  that read output use it: task status, output text, no output, and a model's
  judgement. Run status, File Sync result and agent alerts apply to the whole
  run, so the editor hides the scope for them. It shows the scope again only
  when a stored rule carries a non-final scope, so the author can reset it;
- a condition, one of the seven below. A new rule is left unnamed on purpose:
  the server names it from its condition, for example "Run status is failed",
  and the editor's heading follows the condition as it changes.

| Condition | Fields |
|---|---|
| Run finished with a status | One or more of completed, failed, cancelled, completed with task errors |
| A task finished with a status | Succeeded or failed |
| Output text matches | Contains any of, contains all of, or doesn't contain up to 25 values (400 characters each); or a regex up to 200 characters, with nested quantifiers refused |
| File Sync result | Changed documents found, none found, or File Sync failed |
| The run produced no output | None |
| A model judges a condition | A condition of up to 2000 characters |
| The agent raised an alert | An optional signal name and a minimum severity |

When several rules match a run, the highest severity wins and every matched rule
is listed in the alert.

## The editor

`WorkflowAlertEditor.tsx` renders **Alerts** after the tasks, in both scopes,
for anyone who can manage the workflow:
- **When to alert**, with **Pop-up alert priority** for **On every run**;
- the rules: add, remove, reorder and enable, each with its condition fields,
  scope, severity and delivery. The scope picker keeps a task that was removed
  visible, as "Removed task (review)", so the problem can't hide;
- **If a model evaluated condition cannot be judged**, shown when a rule uses a
  model.

Viewers who can't manage the workflow see `WorkflowAlertSummary.tsx`, a
read-only summary resolved the way the server's `resolve_workflow_alert_config`
does. The group editor's link to the classic alert editor is gone.

### Saving

- The four fields are sent only after an alert edit. An untouched configuration
  goes back exactly as it was loaded (`workflowAlertsForSave`).
- Rules kept while the mode is **off** or **every run** are still sent and still
  checked, as the server does.
- **A stored record that has only a priority** (from before alert rules) is
  turned into the equivalent rules by the server on any save, including an
  untouched one. Alerts behave the same before and after.

### Validation

`workflowAlertErrors` in `lib/workflowAlerts.ts` mirrors
`normalize_workflow_alert_settings`. It uses the server's reviewed messages word
for word, and applies the same trimming and length rules. So the editor allows a
save if and only if the server accepts it, with one exception: regex syntax is
checked only by Python's `re`, which the browser can't reproduce. For regex
syntax, the server's reviewed 400 is shown as returned.

## Server messages

The save routes, `POST /api/user/workflows` and `POST /api/group/workflows`,
used to answer every invalid alert setting with the generic "Invalid workflow
settings. Review the task, runner, trigger, and document inputs." The alert
normalizer now raises `WorkflowPublicValidationError`, defined in
`functions_workflow_definitions.py`. Both routes return it as:

```json
{"error": "<reviewed message>", "code": "invalid_workflow_alerts"}
```

Every other invalid setting keeps the generic message. The messages name a rule
by its position, `{n}`, and only fixed limits. They never echo text you entered:

| Area | Messages |
|---|---|
| Settings | "Alert priority must be none, low, medium or high." · "Alert mode must be off, every_run or rules." · "Add at least one alert rule, or choose a different alert mode." · "Choose a pop-up priority for alerts on every run, or choose a different alert mode." · "Choose skip or alert for model-evaluated conditions that cannot be judged." · "Alert rules must be a list." · "A workflow can have up to 20 alert rules." |
| Rule | "Alert rule {n} is invalid." · "… name must be 120 characters or fewer." · "… delivery must be default, notify_only or popup." · "… severity must be info, low, medium, high or critical." |
| Scope | "Alert rule {n} must look at the final output, any task output, or a specific task." · "… needs a task to watch." · "… watches a task that is no longer in this workflow." |
| Condition | "… has an unsupported condition type." · "… run statuses must be a list." · "… has an unsupported run status." · "… needs at least one run status." · the same three for task statuses · "… text match must be contains_any, contains_all, not_contains or regex." · "… needs a regex pattern." · "… regex pattern must be 200 characters or fewer." · "… regex pattern uses nested quantifiers, which are not allowed." · "… regex pattern is not a valid regular expression." · "… match values must be a list of text." · "… match values must each be 400 characters or fewer." · "… needs at least one match value." · "… can match up to 25 values." · "… File Sync result must be changes_found, no_changes or sync_failed." · "… needs a condition for the model to judge." · "… model condition must be 2000 characters or fewer." · "… signal name must be 120 characters or fewer." |

The classic editor shows the same messages, because it displays the server's
`error`.

The regex check the workflow runner uses at run time, `validate_alert_regex`, is
unchanged. The save path translates its errors, so the regex compiler's own text
never reaches a client.

## Files

| File | Change |
|---|---|
| `application/single_app/functions_workflow_definitions.py` | `WorkflowPublicValidationError` |
| `application/single_app/functions_workflow_alerts.py` | Reviewed messages on the save path |
| `application/single_app/route_backend_workflows.py` | Both save routes map the new error to its own 400 |
| `application/v2_ui/src/lib/workflowAlerts.ts` | New: the alert model, server resolution, validation and save overlay |
| `application/v2_ui/src/components/workflows/WorkflowAlertEditor.tsx` | New: the editor |
| `application/v2_ui/src/components/workflows/WorkflowAlertSummary.tsx` | Read-only viewers only; the classic link is removed |
| `application/v2_ui/src/components/workflows/WorkflowEditorDialog.tsx`, `lib/workflowEditor.ts`, `pages/workspace/WorkflowsSection.tsx`, `pages/GroupWorkspacePage.tsx` | Mounting, the save overlay and validation, and the removed classic handoff. Alert keys leave "Preserved settings" |

## Known limitations

- Regex syntax is checked only by the server (see above).
- The classic editor can't open a workflow saved in V2, as before.
- A File Sync source deleted after the editor loaded its list still makes a save
  fail with 404, which V2 treats as lost access. This is unchanged from 0.261.141.

## Testing and validation

| Suite | Cases | Coverage |
|---|---|---|
| `functional_tests/test_workflow_alert_reviewed_messages.py` | 75 | Both save routes, over the real personal and group stores: each reviewed message; every condition type saves; any other invalid setting stays generic; the runtime regex check and evaluation are unchanged |
| `functional_tests/test_workflow_alert_client_parity.py` | 84 | The production TypeScript runs under Node against the real normalizer. The editor accepts exactly what the server accepts, with identical messages, for every refusal and one accepted case per condition type |
| `functional_tests/test_workflow_file_sync_analyze_targets.py` | 11 | Analyze on changed files, in personal and group scope, through the real save functions |
| `ui_tests/test_v2_workflow_alerts.py` | 18 | Personal and group authoring of each condition type; edit, delete and reorder; the saved body; a rule watching a removed task; a priority-only record; the read-only summary |

The browser fixture runs the real `normalize_workflow_alert_settings` on both
save routes. The existing workflow suites were updated for native editing.

## Related

- [V2 Group Workflows](V2_GROUP_WORKFLOWS.md)
- [Workflow Alert Rules](WORKFLOW_ALERT_RULES.md)
- [Workflow alert removed-task save fix](../fixes/WORKFLOW_ALERT_REMOVED_TASK_SAVE_FIX.md)
