# Workflow budget failure and recovery fix

Fixed in version: **0.261.362**.

Application version: `application/single_app/config.py`.

## Issue

A durable agent workflow could remain in `waiting_recovery` after a local
input-budget refusal. Its task history still showed `running`, its run error
was empty, and the workflow header could remain `Queued` while the run history
already showed the recovery wait. This obscured both the reason for failure and
what the user could safely do next.

In the investigated case, the complete agent request was estimated at 10,249
tokens. Missing model token metadata selected the conservative compatibility
policy, allowing only 7,936 input tokens after its safety margin. The refusal
occurred before an observed model-generation or connector request; it was not
evidence that the intended upstream error had occurred.

## Root causes

### Incomplete shared token metadata

Several existing text-model catalog entries described capabilities without
verified context/output capacities. The workflow budget resolver correctly
refused to invent limits, so these models used the unknown-model compatibility
policy when the saved connection supplied no numeric overrides.

### Deterministic refusals intercepted as recovery waits

Agent task boundaries conservatively treat execution as potentially
side-effecting. The durable wrapper previously converted every ordinary
exception at that boundary into a recovery gate before the task runner could
record its failure. The suspension bypassed normal task-error persistence and
retry-policy handling, including the existing non-retryable context-budget
path. Both ordered and structured workflows shared this behavior.

### Independent UI refreshes

Run history polled its own data, but ordinary background transitions did not
refresh the workflow collection that supplies the header, row, attention count,
and action state. Those surfaces could disagree until a manual reload or
explicit runtime action.

## Changes

- Complete evidence-backed numeric metadata for the existing GPT-4o,
  GPT-4.1, and o-series text entries through the shared model catalog. Provider,
  version, and hosting distinctions remain explicit; no workflow-specific
  model allowance is introduced.
- Share a bootstrap-free policy-error contract between the budget guard,
  ordered/structured durable controllers, and task runner.
- Record application-owned budget/configuration refusals as failed attempts
  with a safe error code and message. Oversized requests retain their numeric
  context-budget audit in task history.
- Let the existing halt/continue policy decide whether independent later tasks
  can execute. Configured ordinary retries never replay a deterministic policy
  refusal, including a refusal after an earlier model/tool round.
- Keep the workbench synchronized with scoped server status rather than
  inferring completion or available actions from stale client state.

Principal implementation files:

- `application/single_app/static/json/model_capabilities.json`
- `application/single_app/functions_model_capabilities.py`
- `application/single_app/functions_workflow_policy_errors.py`
- `application/single_app/functions_workflow_context.py`
- `application/single_app/functions_workflow_execution.py`
- `application/single_app/functions_workflow_structured_execution.py`
- `application/single_app/functions_workflow_runner.py`
- `application/v2_ui/src/pages/workspace/WorkflowsSection.tsx`
- `application/v2_ui/src/components/workflows/WorkflowRunHistory.tsx`
- `application/v2_ui/src/components/workflows/useWorkflowResource.ts`

## What remains unchanged

- Unknown/custom model limits remain conservative. Inputs and tool definitions
  are not silently truncated, and the compatibility allowance is not increased.
- Recovery of interrupted or unclassified potentially side-effecting operations
  still requires an explicit decision. A policy refusal is not proof that earlier
  external effects can be undone or repeated.
- Approval binding, cancellation, ownership fencing, immutable results, and
  structured-loop waits keep their existing contracts.
- A corrected explicit run has a separate identity and does not overwrite a
  failed run. Existing deployed waiting runs are not rewritten or automatically
  resumed by this change.
- A model-written description of an error is not converted into a successful
  connector test or a fabricated execution failure. Output validation remains
  distinct from invocation failure.

## Validation

`functional_tests/test_workflow_policy_failures.py` exercises real request
budgets, durable controllers, task-sequence persistence, and runtime projections
with isolated service boundaries. It covers ordered/structured definitions,
personal/group scopes, zero and positive retry counts, first-request refusal,
later-round refusal, a real Semantic Kernel tool loop, independent-task
continuation, crash safety, and an explicitly corrected second run preserving
the first failure.

Fresh-process probes test both import orders and optimized Python with network
access blocked. Existing context-budget, durable execution, structured flow,
result handoff, model binding, and Cosmos SDK boundary suites provide regression
coverage for unaffected behavior. UI regressions exercise the built application
against closed API fixtures, not the deployed environment.

### Recorded results

Validation used an isolated Python 3.12 environment and local browser fixtures.
No deployed workflows, model configuration, or Azure permissions were modified.
These are focused product checks, not a claim that every existing repository or
live acceptance test passes.

| Check | Result |
| --- | --- |
| `python -m pytest -q -p no:cacheprovider functional_tests\test_workflow_policy_failures.py --disable-warnings --tb=short` | 33 passed, including real Semantic Kernel tool rounds and normal/optimized cold imports. |
| Combined context-budget, durable execution/analysis, structured flow/edges, runtime integration, agent binding, result-handoff and policy regression suites | 146 passed; the final policy-only run above also includes three added catalog-boundary cases. |
| Catalog evidence, token limits/budgets, capability/reasoning resolution, profiles, and rebase integration suites | 183 passed; 1,633 subtests passed. Optimized token-limit suite: 18 passed; 312 subtests passed. |
| `npm --prefix application\v2_ui run typecheck` | Passed. |
| `npm --prefix application\v2_ui run build` | Passed; existing large-bundle warning. |
| `python -m pytest -q ui_tests\test_v2_workflow_status_freshness.py ui_tests\test_v2_workflow_durable_runtime.py ui_tests\test_v2_workflow_editor.py::test_edit_preserves_legacy_fields_and_run_inspection_surfaces_validation` | 24 passed, including 18 new freshness cases. |
| `python functional_tests\test_docs_app_surface_coverage.py` | 7/7 checks passed. |
| `python functional_tests\test_docs_site_quality.py` | 6/6 checks passed. |
| `python scripts\check_cosmos_response_boundaries.py --run-contracts` | 1,174 passed; 144 subtests passed; no inventory review gaps. |
| Post-base-merge policy, catalog evidence, and workflow SDK boundary suites | 86 passed; 709 subtests passed at version 0.261.362. Merged UI build and storage inventory checks also passed. |
| Changed-file XSS sink check and UI mechanical detector | Passed. |

See [Durable workflow execution](../features/WORKFLOW_DURABLE_EXECUTION.md) for
recovery semantics and the user-facing run controls.
