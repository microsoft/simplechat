# Workflow Alert Rules

Conditional, severity-graded notifications for personal and group workflows.

- **Implemented in version:** `0.250.209`
- **Applies to:** personal workflows and group workflows
- **Dependencies:** existing workflow runner, notification center, Semantic Kernel SimpleChat plugin

## Overview

Before this feature a workflow carried a single `alert_priority` field with the values
`none`, `low`, `medium` or `high`. If it was anything other than `none`, the runner created a
notification on **every** run, whether the run succeeded or failed and regardless of what it found.
The alert therefore only told the owner "the workflow ran," which made it easy to either drown in
notifications or turn them off entirely.

Workflow alert rules replace that single switch with a small rule engine. An owner declares **why**
a workflow should notify them and **how loudly**, and a run that matches nothing produces no
notification at all.

## Architecture

```
run finishes (completed / failed / cancelled)
        │
        ▼
build_workflow_alert_facts()  ──►  run status, task results, final output, task outputs,
                                   File Sync result, agent raised signals, error text
        │
        ▼
evaluate_workflow_alert_rules()
        │   deterministic rules evaluated first (free)
        │   model evaluated rules batched into one call, and skipped entirely when a
        │   deterministic rule already matched at or above their severity
        ▼
decision { should_alert, severity, category, delivery, matched_rules[], reasons[] }
        │
        ├── should_alert = False  ──►  no notification, decision recorded on the run
        └── should_alert = True   ──►  create_workflow_priority_notification()
```

### File structure

| File | Role |
|---|---|
| `application/single_app/functions_workflow_alerts.py` | Rule schema, validation, evaluators, batched model evaluation, legacy migration |
| `application/single_app/functions_workflow_runner.py` | Builds the facts, calls the engine, records the decision, creates the notification, hosts the agent signal scope |
| `application/single_app/functions_personal_workflows.py` | Normalizes alert settings on personal workflow save |
| `application/single_app/functions_group_workflows.py` | Normalizes alert settings on group workflow save |
| `application/single_app/functions_notifications.py` | Severity and category presentation, notify-only filtering |
| `application/single_app/functions_workflow_activity.py` | Surfaces the configured rules and each run's alert decision |
| `application/single_app/semantic_kernel_plugins/simplechat_plugin.py` | `raise_workflow_alert` kernel function |
| `application/single_app/static/js/workspace/workspace_workflows.js` | Rules editor used by both the personal and group workflow modals |
| `application/single_app/static/js/notifications.js` | Badge styling, failure wording, delivery gating |

`functions_workflow_alerts.py` deliberately imports neither the workflow runner nor the workflow
CRUD modules, so it can be shared by every caller without an import cycle. The model client is
injected into the engine as a callable for the same reason.

## Configuration

Alert settings live on the workflow document:

```jsonc
{
  "alert_mode": "off | every_run | rules",
  "alert_priority": "none | low | medium | high",   // only used by every_run
  "alert_rules": [
    {
      "id": "uuid",
      "name": "Expiring certificates",
      "enabled": true,
      "severity": "info | low | medium | high | critical",
      "delivery": "default | notify_only | popup",
      "scope": { "type": "final | any_task | task", "task_id": "" },
      "condition": { "type": "...", /* type specific fields */ }
    }
  ],
  "alert_evaluation": { "on_error": "skip | alert" }
}
```

### Alert modes

| Mode | Behavior |
|---|---|
| `off` | The workflow never notifies. |
| `every_run` | The legacy behavior. Every completed or failed run notifies at `alert_priority`. Cancelled runs stay silent, as before. |
| `rules` | Only runs matching an enabled rule notify. |

Selecting `rules` with an empty rule list, or `every_run` with a priority of `none`, is rejected at
save time so the configuration cannot silently mean "never notify."

### Condition types

| Type | Fields | Matches when |
|---|---|---|
| `run_status` | `statuses[]` from `completed`, `failed`, `cancelled`, `completed_with_task_errors` | The run ended in one of the listed statuses |
| `task_status` | `statuses[]` from `succeeded`, `failed` | A task in scope ended in one of the listed statuses |
| `text_match` | `mode` (`contains_any`, `contains_all`, `not_contains`, `regex`), `values[]` or `pattern`, `case_sensitive` | The scoped output matches |
| `file_sync` | `outcome` (`changes_found`, `no_changes`, `sync_failed`) | The pre-run File Sync produced that outcome |
| `no_output` | — | The scoped output was empty |
| `model_evaluation` | `prompt` | A model judges the plain-English condition to be met |
| `agent_signal` | `signal_name`, `min_severity` | The agent raised a matching signal during the run |

`run_status`, `file_sync` and `agent_signal` read run-level facts, so they ignore scope. Every other
condition honors the rule's scope.

### Scope

| Scope | Reads |
|---|---|
| `final` | The final workflow reply |
| `any_task` | Each task's output, evaluated independently |
| `task` | One specific task's output, selected by `task_id` |

`contains_all` is evaluated per candidate, so `any_task` means "one task output contains all of the
values" rather than "the values appear somewhere across the run."

### Severity, category and delivery

| Severity | Icon | Color | Default delivery |
|---|---|---|---|
| `info` | `bi-info-circle` | info | Notification bell only |
| `low` | `bi-bell` | info | Notification bell only |
| `medium` | `bi-exclamation-circle` | warning | Pop-up alert |
| `high` | `bi-exclamation-triangle` | danger | Pop-up alert |
| `critical` | `bi-exclamation-octagon` | danger, wider accent | Pop-up alert |

Each rule can override the delivery with `notify_only` or `popup`.

Separately from severity, every alert carries a **category**. When the winning rule was triggered by
a run error, a task failure, a File Sync failure, or an empty run, the category is `failure`, which
swaps the icon to `bi-x-octagon`, forces the danger accent, and changes the badge from
`HIGH PRIORITY` to `HIGH FAILURE`. This keeps "the workflow broke" visually distinct from "the
workflow found something," at whatever severity the owner chose.

### Resolving multiple matches

All enabled rules are evaluated. The **highest severity match wins** and sets the severity, category
and delivery; ties are broken by rule order. Every matched rule is still reported, and the alert
detail opens with a `Triggered by` section listing each matched rule, its severity and its reason.

One run produces at most one notification no matter how many rules match.

## Model evaluated conditions

A `model_evaluation` rule holds a plain-English condition such as *"any certificate expires within
14 days."* These are the most useful conditions and the only ones that cost tokens, so they are
tightly bounded:

- **One call per run at most.** Every pending model evaluated rule is batched into a single prompt
  and the model returns one JSON verdict per rule.
- **Skipped when moot.** If a deterministic rule already matched at or above a model rule's
  severity, that model rule cannot change the outcome and is not sent. When no model rule remains,
  no model client is even resolved.
- **Bounded input.** The scoped output is truncated before it enters the prompt.
- **Strict output.** The response is parsed as JSON, tolerating markdown fences and surrounding
  chatter. `alert_evaluation.on_error` decides what happens when it cannot be parsed or the call
  fails: `skip` stays silent, `alert` raises the rule as a `failure` so the condition is not
  silently dropped.

The evaluator uses the workflow's own runner model and falls back to the app default.

## Agent raised alerts

Agent-runner workflows can raise an alert mid-run through the SimpleChat plugin:

```text
raise_workflow_alert(severity, title, reason, signal_name)
```

The signal is written into a run-scoped `contextvar` that the runner opens around the whole run and
resets in a `finally` block, so signals never leak between runs. Outside an active workflow run the
function refuses with a `PermissionError`, so a normal chat cannot fabricate a workflow
notification.

An `agent_signal` rule then decides whether the signal notifies anyone. The rule's severity acts as
a **floor**: an agent can escalate above it but never quiet it below. Use `signal_name` to route
distinct signals to distinct rules.

`raise_workflow_alert` is **opt-in**. It is registered with `default_enabled: False`, so existing
agents do not silently gain the ability to create notifications; an admin enables it per action in
the agent or plugin capability toggles.

## Usage

### Configuring rules

1. Open a workflow in the personal or group workspace and go to the **Review** step.
2. Under **Alerts**, set **When to alert**:
   - *Never notify me* for silence.
   - *Only when a condition is met* to use rules.
   - *On every run* to keep the legacy behavior.
3. In rules mode, add rules with **Add rule**. For each rule choose a name, condition, severity and
   delivery, then fill in the condition fields and, where relevant, what the rule should look at.
4. Choose what should happen when a model evaluated condition cannot be judged.

### Example: alert only on something worth knowing

| Rule | Condition | Severity |
|---|---|---|
| Run failed | Run status is `failed` | `high` |
| Expiring certificates | A model judges "any certificate expires within 14 days" | `critical` |
| Nightly ran | Run status is `completed` | `info` |

A clean nightly run produces a quiet bell entry. A run that finds an expiring certificate raises a
critical pop-up listing all three matched rules. A broken run raises a high failure alert.

## Migration

Workflows saved before this feature only carry `alert_priority`. They are migrated **on read** by
`resolve_workflow_alert_config()`, so no data migration is required and behavior is preserved
exactly:

| Legacy value | Migrated rules |
|---|---|
| `none` | Mode `off`, no rules |
| `low` / `medium` / `high` | Mode `rules` with `Run failed → high` and `Run completed → <priority>` |

Because legacy alerts always opened the modal regardless of priority, the migrated rules pin
`delivery` to `popup` rather than inheriting the new severity default. The rules are ordinary
editable rules, so an owner can prune the noisy one. Cancelled runs did not alert before and still
do not.

Clients that predate alert rules, such as the `create_personal_workflow` plugin function, still send
only `alert_priority`; the save path materializes the same migrated rules for them.

## Observability

Each run records a compact `alert_decision` on its run record, including whether it alerted, the
winning severity and category, and every matched rule with its reason. This is surfaced through
`functions_workflow_activity.py` alongside the workflow's configured rules, so an owner can see why
a run did or did not alert. The decision is also written to App Insights through `log_event`.

## Limitations and safeguards

- **Regex safety.** Patterns are capped at 200 characters, compiled at save time, and rejected when
  they contain a quantified group that itself contains a quantifier, which is the classic
  catastrophic backtracking shape. Searched text is truncated before matching.
- **Rule count.** A workflow supports up to 20 alert rules.
- **One notification per run.** Multiple matches raise the severity and add reasons, they do not
  multiply notifications.
- **No cooldown yet.** A condition that persists across a short schedule will alert on every cycle.
  Per-rule cooldown and digest rollups are planned follow-ups.
- **Model cost.** Model evaluated conditions add at most one small model call per run. Workflows
  using only deterministic conditions add no model calls.

## Related tests

| Test | Covers |
|---|---|
| `functional_tests/test_workflow_alert_rules.py` | Every condition type, scoping, severity resolution, failure category, validation, legacy migration |
| `functional_tests/test_workflow_alert_model_evaluation.py` | Batching, the skip optimization, response parsing, `on_error` handling, prompt bounds |
| `functional_tests/test_workflow_alert_agent_signal.py` | Signal normalization, severity floor, named routing, plugin gating and opt-in default |
| `functional_tests/test_workflow_priority_alerts.py` | Existing alert content and deep-link behavior |
| `ui_tests/test_workspace_workflow_alert_rules.py` | The rules editor and legacy rule loading |
| `ui_tests/test_workflow_priority_alert_modal.py` | Critical severity, failure styling, notify-only suppression |

## Related documentation

- `docs/explanation/features/WORKFLOW_PRIORITY_ALERTS.md` — the original alert modal and deep links
- `docs/explanation/release_notes.md` — release entry for `0.250.209`
