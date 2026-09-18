# Microsoft 365 CodeQL remediation (v0.261.030)

Fixed in version: **0.261.030**

Application version: `application/single_app/config.py`, updated from
`0.261.029` to `0.261.030`. No deployment logic or deployer version changed.
Related work: [PR #1497](https://github.com/microsoft/simplechat/pull/1497)
and [issue #1493](https://github.com/microsoft/simplechat/issues/1493).

## Issue and root cause

The PR's Python CodeQL analysis reported 31 findings. Four
`py/stack-trace-exposure` alerts shared an existing workflow alert evaluator:
provider exceptions were copied into model-evaluation errors and matched-rule
reasons. Those reasons were persisted and could be returned in run history,
activity streams, and notifications.

The flagged HTTP 202 response lines were new approval/sign-in branches, not
the diagnostic producer. The completed-run reproduction did not take a waiting
branch. The fix removes diagnostics at their source and read boundaries rather
than changing correct waiting behavior or attributing all exposure to the PR.

The other actionable findings concerned a nullable exception read after an
asynchronous iteration, an implicit return possibility in bounded budget
persistence, a real connection/execution import cycle, dead imports/assignments,
and undocumented expected Cosmos outcomes.

## Public error handling

`functions_workflow_alerts.py` now emits the stable code
`workflow_alert_evaluation_failed` and an actionable public message. Diagnostic
details remain in server-side `log_event` calls, correlated by workflow and run
IDs. The `alert` versus `skip` setting, rule severity, batching, and ordinary
model-authored explanations are unchanged.

`functions_workflow_alert_safety.py` projects current and historical decisions
without mutating their stored records. It recognizes explicit error provenance
and the old model-evaluation error prefix when provenance was not persisted.
It also removes the corresponding diagnostic text from rendered workflow alert
details. This is a targeted compatibility projection, not a broad deletion of
model explanations or a database rewrite.

The projection is used by `functions_workflow_runner.py`,
`functions_personal_workflows.py` (also used by group workflow storage),
`functions_workflow_activity.py`, and `functions_notifications.py`.
Approval/sign-in fields remain actionable, and personal/group run and resume
handlers retain HTTP 202 for waiting runs.

## Authorization dependency boundary

`functions_m365_context.py` owns the immutable execution context, scoped
accessors, policy error, and canonical fingerprint helpers. It has no
configuration, storage, logging, or policy-owner dependency.
`functions_m365_execution.py` preserves its existing context API, and approvals
continue to expose the same policy-error/fingerprint objects.

`functions_m365_connections.py` no longer imports the execution owner, including
inside functions. Instead, `app.py` and
`background_tasks.check_m365_workflow_continuations_once()` configure the live
workflow authorizer after configuring execution's ownership callbacks. The
setter preserves the existing connection service and its configured factories.

An absent or malformed authorization callback fails before storage, cache
decryption, key lookup, or MSAL access. Approved workflows still revalidate
before and after refresh. Disconnect generations, revocation, workflow
revision, source scope, and data-user identity checks are retained. No caller,
owner, or application-token fallback is introduced.

## Control flow and cleanup

`AgentContinuationJournal.finish()` captures the checked pending exception
before asynchronous history iteration and raises that same object after saving
the checkpoint. Completed sibling calls remain completed and are not replayed.

`resolve_m365_budget_run()` declares a string return and an explicit terminal
failure. It continues to retry only conditional-write conflicts, reuse the same
budget, reject conflicting budget IDs, and surface exhausted or other storage
errors. It never returns `None` as a usable budget.

Unused imports and the dead URL-parser assignment were removed. Deferred config
imports use consistent module-qualified access. Personal-action settings
bootstrap still executes. Narrow Cosmos 404/409 handlers now explain the lookup
or idempotence condition they intentionally accept; other errors retain their
existing failure/logging behavior.

## Intentional findings retained

These four findings do not justify changing runtime interfaces:

| Original alert | Construct | Disposition |
|---|---|---|
| [2752](https://github.com/microsoft/simplechat/security/code-scanning/2752) | `MemoryBlobTransport.read` Protocol stub | Keep `...`; it declares the structural typing contract. |
| [2753](https://github.com/microsoft/simplechat/security/code-scanning/2753) | `MemoryBlobTransport.put` Protocol stub | Keep `...`; concrete transports supply the implementation. |
| [2754](https://github.com/microsoft/simplechat/security/code-scanning/2754) | `MemoryBlobTransport.delete` Protocol stub | Keep `...`; this is not unfinished executable logic. |
| [2764](https://github.com/microsoft/simplechat/security/code-scanning/2764) | `MemoryUnavailableError` facade import | Keep the public export used by providers and regression tests. |

No query is disabled and no blanket suppression is added. A maintainer may
individually dismiss these documented false positives; removing the facade
export or adding an incomplete `__all__` would be an incompatible workaround.

## Validation

Regression coverage includes:

- `test_workflow_alert_error_redaction.py`: synthetic diagnostic canaries,
  historical records, real run/resume handler status selection, activity stream
  serialization, notification read boundaries, and preserved model explanations.
- `test_workflow_alert_model_evaluation.py`: batched evaluation, severity
  selection, skipped evaluation, and error policy.
- `test_m365_connections.py`: missing/malformed authorizers, pre/post-refresh
  validation, mid-refresh revocation/disconnect, safe errors, and key protection.
- `test_m365_runtime_imports.py`: real web/scheduler startup and both
  connection/execution import orders in fresh normal and optimized Python;
  blocked network access, unconfigured early access, and static checks including
  function-local imports.
- `test_m365_agent_continuation.py`: original exception identity after concurrent
  mutation, no-pending behavior, approval/sign-in waits, and no replay.
- `test_m365_file_runtime.py`: budget reuse, conflict recovery/exhaustion,
  identity mismatch, and propagation of non-conflict storage failures.

The expanded offline run passed **606 tests and 96 subtests**. The focused
optimized-Python run passed **161 tests and 87 subtests**. Fresh-process import
checks passed in both modes; route-policy and documentation checks also passed.

Three unchanged tests in `test_conversation_context_grounding.py` were excluded
from the final expanded run only after reproducing their same failures against
pre-remediation PR head `b8a75418`: a stale call-count assertion and two missing
dependencies in AST-extracted test fixtures. They are
`test_chat_and_document_action_paths_are_wired`,
`test_document_action_message_builders_place_context_before_user`, and
`test_per_document_results_preserve_resolved_context`. No test or production
behavior was changed to hide those unrelated failures.

These tests use scoped external-I/O fakes, not a live tenant. Commercial,
Government, custom-cloud API availability, tenant consent, and live Key Vault
qualification remain deployment-specific checks. See
[Microsoft 365 actions](../features/MICROSOFT_365_ACTIONS.md) for prerequisites.
