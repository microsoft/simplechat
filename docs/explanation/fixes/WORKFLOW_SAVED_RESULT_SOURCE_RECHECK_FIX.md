# Workflow Saved Result Source Re-check Fix

Fixed in version: **0.261.231**

Related issues: [#1621](https://github.com/microsoft/simplechat/issues/1621) (layer 3a). Follows
[Workflow Run History Source Re-check Fix](WORKFLOW_RUN_HISTORY_SOURCE_RECHECK_FIX.md) (0.261.229).

## Issue

Saved and generated workflow results stopped working whenever a document they came from changed. Deleting,
re-uploading or holding one source document for review was enough:

- A task result page, a structured run's execution history, a For each item list or a Repeat round answered
  403 with "Current access to this execution or its contributing sources could not be confirmed."
- Per-task previews in run history were replaced with "This saved analysis is unavailable because its access
  could not be confirmed."
- Opening a saved workflow's Flow returned 403 with "Current access to this workflow definition or its sources
  could not be confirmed." when one referenced document was missing, held or outside the reader's access. V2
  then cleared the whole diagram.
- A chat answer about a workflow result was withheld with "This workflow result is unavailable because access
  to one of its sources could not be confirmed.", and earlier answers in that chat were hidden too.
- A later task could not read an earlier task's output: the run paused with "A collected source changed. The
  saved records were retained." or "The Repeat state's original sources are no longer available.", or the
  task failed when its checkpoint was resumed.
- V2 execution and Repeat history showed "Source snapshots have changed" warnings.
- One task's held input could leave the model fence set for every later task in the same run, because the
  fence lived on one request context for the whole run.

## Root Cause

Every saved result carried the list of documents it came from, and every read re-resolved that list for the
current reader. The lineage walk in `WorkflowLineageAuthorization` (`functions_workflow_node_results.py`)
and `authorize_workflow_task_result_read` (`functions_workflow_results.py`) called
`authorize_analysis_sources` for each result and each consumed ancestor. Any missing, changed, held or
inaccessible document raised `AnalysisResultUnavailable`, or set `source_snapshot_changed`, which other
code treated as a reason to stop. History, inspection, Repeat state, Collect, the record readers, chat
follow-ups and the document provenance run link all used that walk.

Under the upload-only screening model tracked in #1621, a document is checked when it enters a workspace
and when a workflow reads it as an input. Results generated from it take their access from the workflow,
run or conversation they belong to and are never re-checked.

## Technical Details

### Files modified

Application (`application/single_app/`):

- `functions_workflow_node_results.py`, `functions_workflow_results.py`: lineage only
- `functions_workflow_iterations.py`, `functions_workflow_flow_runner.py`, `functions_workflow_repeat_state.py`,
  `functions_workflow_repeat_execution.py`, `functions_workflow_structured_execution.py`: removed re-check gates
- `functions_workflow_repeat_history.py`, `functions_workflow_execution_history.py`,
  `functions_workflow_loop_history.py`, `functions_workflow_reporting.py`, `functions_workflow_runtime.py`:
  history and status
- `functions_workflow_inspection.py`, `route_backend_workflows.py`: Flow inspection and route messages
- `functions_workflow_result_reader.py`, `functions_workflow_result_store.py`, `functions_saved_analysis.py`:
  chat follow-ups and run history previews
- `functions_document_provenance.py`: the document provenance run link
- `functions_workflow_runner.py`, `content_screening/access.py`: per-task model fence
- `config.py`: version 0.261.231

V2 (`application/v2_ui/src/`): `lib/workflowExecutionHistory.ts`, `lib/workflowResults.ts`,
`components/workflows/WorkflowExecutionHistory.tsx`, `components/workflows/WorkflowFlowView.tsx`,
`components/workflows/WorkflowDefinitionInspector.tsx`.

### Changes

- **Lineage only.** `WorkflowLineageAuthorization`, `authorize_workflow_node_result_read`,
  `authorize_workflow_task_result_read` and `authorize_workflow_run_read` still prove that each result and
  each consumed receipt belongs to this workflow, run, task or node and attempt, that contract versions and
  hashes match, and that receipts chain correctly. They no longer call `authorize_analysis_sources`. They still
  return the collected sources as provenance, so a later result that consumes this one keeps its
  `analysis_access`. `source_snapshot_changed` is always `false`; the key stays in responses and payloads so
  older clients and in-flight input digests keep working. The `source_resolver` parameters are kept and
  unused. `authorize_analysis_sources` itself is unchanged; its remaining Analyze, chat and orchestration
  callers are handled in the next layer.
- **Generated output flows on.** Collect, Repeat state, record inputs, checkpoint resume and the iteration path
  proof no longer stop when a source behind an earlier output changed. The pause messages that remain are for
  input or integrity failures: "The loop's input is no longer available or could not be verified." and "The
  Repeat state's input is no longer available or could not be verified. Saved originals are retained."
- **Input checks stay.** Reading an uploaded document as an input is still checked: For each document items
  (`_authorize_frozen_document`, `load_frozen_item_value`), document selections, reference inputs
  (`load_workflow_reference`), configured File Sync and other sources (`functions_workflow_readiness.py`) and
  the File Sync trigger.
- **Per-task model fence.** `isolate_request_source_fence()` gives each task attempt an empty fence and puts the
  caller's state back afterwards. A held input still blocks its own task's model call. It can no longer block a
  later task that reads only generated output.
- **Run history previews.** `sanitize_workflow_analysis_history` no longer redacts a preview because of its
  sources. A result that fails its lineage check or can't be read is withheld with "This saved task output is
  unavailable because it could not be read or verified."
- **Flow inspection.** `authorize_workflow_flow_sources` was removed. A definition takes its access from its
  workflow. Only the `selection` rows on the requested page are looked up, and a missing, held or inaccessible
  source gets `"available": false` on its row. V2 shows "Not available to you right now. It may have been
  removed, be held for review, or be outside your access. The workflow definition is unchanged." Storage
  failures still fail the request, so an outage isn't shown as an unavailable source.
- **Routes.** Saved results need only the existing container checks: workflow scope, the run belongs to the
  workflow, group membership, and someone else's run answering like a missing one. The new messages:

  | Where | Before | After |
  | --- | --- | --- |
  | Flow routes | 403 "Current access to this workflow definition or its sources could not be confirmed." | 403 "Current access to this workflow could not be confirmed." (container checks only) |
  | Execution history | 403 "Current access to this execution or its contributing sources could not be confirmed." | 409 "This saved execution record could not be verified." for a lineage failure; 403 "Current access to this execution could not be confirmed." |
  | Task result pages | 403 "Access to this task result is not allowed." for any `AnalysisResultUnavailable` | 409 "The saved result or requested page is unavailable." for a lineage failure |
  | Activity streams | `source_access_denied` "Workflow source access is no longer available." | `activity_unavailable` "Workflow activity is no longer available." |

- **Chat follow-ups.** The workflow result reader keeps its ownership, privacy and digest checks. A lineage
  failure now maps to `workflow_result_invalid` instead of `workflow_result_access_denied`, whose message is now
  "This workflow result is unavailable because access to it could not be confirmed." Masking keeps answers when
  a source is lost.
- **Document provenance.** A document's "Created by" link names its run when the run belongs to the workflow the
  reader can open. It no longer re-checks the run's saved results.
- **V2.** Execution and Repeat history ignore `source_snapshot_changed` and no longer show "Source snapshots have
  changed". The Flow 403 message reads "Current access to this workflow could not be confirmed. Cached Flow
  details were removed."

Nothing is migrated or withdrawn. Results saved before this version are read the same way.

## Validation

`functional_tests/test_workflow_saved_results_container_access.py` (new, 34 tests) runs the real workflow
modules over the existing in-memory result, journal and Cosmos fixtures:

- Deleting, re-uploading or holding a source document does not hide or fail saved task results, node
  results, execution history, Repeat rounds and state, loop history, run history previews or chat follow-ups,
  and no source is looked up.
- A later task consumes an earlier task's output after that output's source changed, in both the task
  sequence and structured flows.
- A held document is still refused as a loop document item, a reference input, a configured source and a File
  Sync trigger, and still blocks its own task's model call. Each task gets its own fence.
- Group results stay limited to group members, and someone else's run still answers like a missing one.
- Forged producer identities, hash mismatches and a changed digest are still refused, as integrity failures
  rather than source denials.

Without the fix, 29 of its 34 tests fail; the 5 that pass either way cover the checks that stay.

Tests that asserted source re-checks were rewritten to assert the container and integrity behavior instead:
`test_analysis_workflow_source_inheritance.py`, `test_workflow_result_masking.py`,
`test_workflow_history_source_access.py`, `test_workflow_flow_inspection.py`,
`route_tests/test_workflow_flow_inspection_policy.py`, `test_workflow_loop_native_analysis.py`,
`test_workflow_repeat_recovery.py`, `test_workflow_structured_edges.py`, `test_workflow_structured_flow.py`,
`test_workflow_structured_publication.py`, `test_workflow_named_result_inputs.py`, `test_workflow_result_reader.py`,
`test_workflow_result_routes.py`, `test_workflow_result_followup.py`, `test_workflow_loop_reporting.py`,
`test_workflow_collect_publication.py`, `test_workflow_repeat_publication.py`, `test_workflow_data_flow_execution.py`,
`test_document_provenance_origin.py`, and the V2 tests `ui_tests/test_v2_workflow_repeat_until.py`,
`ui_tests/test_v2_workflow_flow_authoring.py` and `ui_tests/test_v2_workflow_flow_inspection.py` (new check that
an unavailable source is marked on its own row).

Before-and-after runs, on a shared and heavily loaded test host, compared every FAILED/ERROR test id:

- **Functional tests:** the 241 files covering `functional_tests/test_workflow_*.py`, the group workflow, provenance,
  Analyze and saved-analysis tests, `route_tests/test_workflow_*_policy.py` and the three route policy tests,
  plus the new file. Baseline 4,449 passed with 1,589 failures and errors; after 4,479 passed with 1,580, all
  of which also fail on the base branch (stale harnesses and tests that need Azure configuration). No new
  failures. The only differences are `test_workflow_data_flow_execution.py`, whose whole file fails on the base
  branch for an unrelated harness reason and where one test was renamed, and
  `test_orchestration_workflow_results_imports.py`, an import-order test that stalls under this host's load
  inside the batch runner; run directly it passes, 26 of 26.
- **V2 browser tests:** 11 files (Repeat until, Flow authoring and inspection, loops, authoring history, control
  runtime and flow, durable runtime, chat workflow results, document provenance, orchestration workflow results
  input). 339 passed before and after; the same 4 errors in `test_v2_orchestration_workflow_results_input.py`
  occur on the base branch.
- **Node client tests:** `test_workflow_results_clients.mjs`, `test_workflow_execution_inspection_client.js` and
  `test_v2_orchestration_workflow_results_naming.mjs` pass before and after.
- `npm run typecheck` and `npm run build` in `application/v2_ui` pass.
