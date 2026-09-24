# Workflow Alert Removed-Task Save Fix

Fixed in version: **0.261.144**

## Issue

A workflow alert rule can watch a single task. If that task was deleted in the
V2 workflow editor, every later save of the workflow failed with the generic
message "Invalid workflow settings. Review the task, runner, trigger, and
document inputs." Nothing pointed at the alert rule, so the workflow couldn't be
saved at all until the stale rule was found some other way. The classic editor
couldn't help, because it doesn't open workflows saved by V2.

More generally, every invalid alert setting produced the same generic message,
from either save route.

## Root cause

Two things combined:

1. The V2 editor sends the loaded `alert_rules` back on every save. The server
   checks a task-scoped rule against the workflow's current tasks whenever the
   save carries `alert_rules`, so a rule watching a removed task is refused
   (`functions_workflow_alerts.py`, `_normalize_alert_rule_scope`).
2. Both save routes turned every `ValueError`, including the alert normalizer's,
   into one generic 400 (`route_backend_workflows.py`). The V2 editor didn't
   check alert rules before saving.

## Technical details

### Files modified

| File | Change |
|---|---|
| `application/single_app/functions_workflow_definitions.py` | `WorkflowPublicValidationError(ValueError)`, carrying a reviewed, data-free message |
| `application/single_app/functions_workflow_alerts.py` | The save path raises it for each alert validation failure, naming the rule's position |
| `application/single_app/route_backend_workflows.py` | Both save routes return it as 400 `{"error", "code": "invalid_workflow_alerts"}`, before the generic branch |
| `application/v2_ui/src/lib/workflowAlerts.ts`, `components/workflows/WorkflowAlertEditor.tsx`, `lib/workflowEditor.ts` | The editor validates alert rules before saving, with the same messages, and marks a rule whose task was removed |

### Behaviour after the fix

- Deleting a task that a rule watches marks the rule in the editor ("Removed task
  (review)"). The save is blocked with "Alert rule {n} watches a task that is no
  longer in this workflow." until another task is chosen or the rule is removed.
- If a save still reaches the server with an invalid alert setting, the reply
  names the problem and the rule's position, instead of the generic message. The
  classic editor shows the same text.
- Every other invalid workflow setting keeps the generic message.

## Validation

- `functional_tests/test_workflow_alert_reviewed_messages.py` pins each reviewed
  message on both save routes, including the removed-task case. It also checks
  that other invalid settings stay generic.
- `functional_tests/test_workflow_alert_client_parity.py` runs the editor's
  validation against the real normalizer. The two agree on every case, with
  identical messages.
- `ui_tests/test_v2_workflow_alerts.py` removes a watched task in the browser,
  and checks that the rule is marked and the save is blocked with the message.

| Case | Before | After |
| --- | --- | --- |
| Delete a task that a rule watches, then save | Generic 400; the workflow can't be saved | The rule is marked; the save is blocked with a message naming the rule |
| Any other invalid alert setting | Generic 400 | 400 naming the rule and the problem, with `invalid_workflow_alerts` |
| Any other invalid workflow setting | Generic 400 | Generic 400 (unchanged) |

## Related

- [V2 Workflow Alert Editing](../features/V2_WORKFLOW_ALERT_EDITING.md)
