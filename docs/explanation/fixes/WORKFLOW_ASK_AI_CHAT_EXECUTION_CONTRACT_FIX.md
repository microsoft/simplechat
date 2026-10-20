# Workflow Ask AI chat-execution contract fix (v0.261.362)

## Issue and root cause

Fixed in version: **0.261.362**, tracked by
`application/single_app/config.py`.

Two observed requests to `POST /api/user/workflows/assist` returned HTTP 502
while authoring a new email-review workflow. Both model calls in each request
completed normally, but the fifth operation was rejected during application,
including after the single correction retry. This was an application rejection,
not an App Service timeout or model-provider outage.

Historical diagnostics did not retain the operation name or response body, so
they cannot prove which exact edit failed. Investigation reproduced the same
failure pattern using a separate, confirmed contract defect: the assistant's
chat-execution schemas accepted combinations that runtime validation refused.
Selected mode could have no requirements; orchestration and Off could carry
requirements even though only selected mode accepts them. The correction
message did not explain these cross-field rules.

A second confirmed defect removed 11 newer supported operation names from
content-free diagnostics. That included chat-execution, results-delivery, and
document-selection edits, preventing identification of their rejected operations.
The reproduction is not a recovered copy of the historical model response.

## Technical changes

`functions_workflow_assist_operations.py` now gives workflow-level and task-level
chat-execution operations the same conditional schema constraints:

| Mode | Required capabilities and visual requirements |
| --- | --- |
| Selected | At least one of the two lists must be nonempty |
| Orchestration or Off | Both lists must be empty |

The model prompt in `functions_workflow_assist.py` explains these rules.
Schema feedback identifies the invalid combination, and the runtime normalizer
continues to validate it independently. Runtime failures retain server-authored
guidance and distinguish invalid configuration from unavailable modes,
capabilities, and visual outputs. No model/provider exception text is exposed.

`functions_assist_diagnostics.py` explicitly allows every supported operation
name and the new closed chat-rejection categories. The shared module remains
bootstrap-free. Existing debug gating, hashed correlation, bounded reason counts,
both logging sinks, and filtering of private content remain unchanged.

No route, permission, setting, workflow execution, or frontend behavior is added.
The assistant still applies a candidate atomically, corrects at most once,
and never saves or starts the workflow. It does not silently remove invalid
operations, substitute unavailable capabilities, grant Microsoft 365 access,
or invent a missing schedule time.

## Validation

`functional_tests/test_workflow_assist_chat_results.py` compares the real
operation schemas with the real normalizer across workflow/task modes and
capability/visual selections. It also exercises runtime rejection, unavailable
choices, persistent-invalid 502 responses, and successful second-round correction.

A scripted single-blank-task scenario prepares Monday/Tuesday email-review
instructions and a Wednesday recurrence while asking for the missing run time.
The original draft, Run as identity, and results destination are preserved.
This tests authoring only: it does not claim that mailbox access is configured
or that an email review has run.

`functional_tests/test_ask_ai_debug_diagnostics.py` checks every supported
operation name through actual rejection events and both logging sinks, with
attempts, indexes, stages, and hashed correlation. Private values, unknown
categories, raw submission IDs, and provider messages remain excluded.
Fresh subprocess probes run under normal and optimized Python with network
access blocked and explicit checks that cannot disappear under `python -O`.

Run the focused regression suite in an environment matching the application
requirements:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short functional_tests\test_workflow_assist_chat_results.py functional_tests\test_workflow_assist_scenarios.py functional_tests\test_ask_ai_debug_diagnostics.py functional_tests\test_workflow_assist_operations_security.py functional_tests\test_workflow_configuration.py functional_tests\route_tests\test_workflow_assist_policy.py
```

The suite above was run with the neighboring request, dry-run parity, runtime
limits, field parity, and goal-first authoring suites: **786 passed, 1 skipped**.
The existing V2 build-dependent check was skipped because its dependencies
were not installed. Normal and optimized network-blocked probes passed.
Documentation inventory/coverage passed **7/7** checks and site quality passed
**6/6** checks. The application surface inventory remains current.

Before the fix, invalid cross-field combinations passed the advertised schema
and reached a generic apply failure. After the fix, they fail schema validation
with actionable correction feedback; valid corrected replies produce a candidate,
and persistently invalid replies still return 502 without partial changes.

These changes require deployment before production behavior changes. Repeat the
original unsaved-draft request after deployment and correlate any remaining
rejection by its operation name and safe rule before claiming the historical
incident is resolved.

See [Workflow AI assistant](../features/WORKFLOW_AI_ASSISTANT.md) for the
authoring contract and [Ask AI operation diagnostics](ASK_AI_OPERATION_DIAGNOSTICS_FIX.md)
for bounded telemetry queries and privacy limits.
