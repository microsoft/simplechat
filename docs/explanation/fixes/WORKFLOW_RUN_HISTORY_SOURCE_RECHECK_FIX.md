# Workflow Run History Source Re-check Fix

Fixed in version: **0.261.228**

Related issues: [#1613](https://github.com/microsoft/simplechat/issues/1613) (fixed), [#1621](https://github.com/microsoft/simplechat/issues/1621) (first step).

## Issue

Workflow pages stopped working for runs whose source documents had changed:

- A workflow's run history returned HTTP 403 with "Run history is unavailable because source access could not be confirmed." It took only one of the last 50 runs having used a document that was later deleted or re-uploaded. Runs that never used that document were hidden too.
- Opening a run's task results returned the same kind of 403: "Task results are unavailable because source access could not be confirmed."
- The live activity view of a run ended with "Workflow source access is no longer available."
- A workflow's last-run preview was blanked in the workflow list.
- A task could fail right after it saved its output, with "Saved task output was withheld because its source access could not be confirmed."
- The Approvals page always showed a content screening notice ("Workspace knowledge holds use protected evidence and revision-bound decisions."), even when content screening was off.

## Root Cause

Saved workflow results were re-checked against every source document each time they were shown, using `authorize_workflow_run_read` from `functions_workflow_results.py`. That check re-authorizes each task result and every result it consumed against the current state of its source documents: whether each document still exists, its version, its screening state, and whether the reader can access it. Any change, or any failed lookup, raised `AnalysisResultUnavailable`.

- **Run list and run items:** the run list routes ran the check for each listed run inside one `try` block, so the first failure turned the whole response into a 403. The run items routes did the same for one run.
- **Activity view and definition response:** these ran the same check before showing a run's activity or a workflow's last-run preview.
- **Runner:** the workflow runner read each task's output back through `authorize_workflow_task_result_read` immediately after saving it and failed the task if the read-back raised.

This came from the content screening source checks spreading to saved results. Under the upload-only screening model tracked in #1621, a document is checked when it enters a workspace and when it is read as an input. Results generated from it take their access from the workflow, run or conversation they belong to, and are not re-checked.

## Technical Details

Files modified:

- `application/single_app/route_backend_workflows.py`
- `application/single_app/functions_workflow_runner.py`
- `application/single_app/templates/approvals.html`
- `application/single_app/config.py`
- `functional_tests/test_workflow_run_history_source_recheck_fix.py` (new)
- `functional_tests/test_workflow_history_source_access.py`
- `ui_tests/test_content_screening_classic.py`
- `ui_tests/fixtures/content_screening_classic.py`

Changes:

- **Run history.** The personal and group run list routes return the workflow's runs after the existing container checks: the workflow must be in the caller's scope, and group routes still require group membership. The run items routes still require the run to belong to the workflow. None of these routes re-check run sources any more.
- **Activity view.** `_resolve_workflow_activity_context` and `_resolve_group_workflow_activity_context` no longer re-check the run's sources before building the snapshot.
- **Workflow definitions.** `_workflow_definition_response` keeps a last-run preview that is bound to a run. It still hides a legacy preview that has no `last_run_id` (`result_access: legacy_preview_unbound`). The workflow list no longer runs a source re-check for every workflow on each load.
- **Runner.** `_execute_workflow_task_sequence` no longer reads a task's output back through `authorize_workflow_task_result_read` after saving it. Reading a previous task's output as an input to the next task is unchanged.
- **Approvals page.** The content screening notice renders only when `enable_content_screening` is on, which `sanitize_settings_for_user` keeps. The notice now reads: "To review uploaded documents that content screening is holding, open Content review." Each content screening request keeps its own **Open content review** link, so holds created before screening was turned off stay reachable.

Not changed in this version:

- Per-task previews inside run history still pass through `sanitize_workflow_analysis_history`, which can show "unavailable" for a single task.
- Structured workflow execution history and Flow inspection still re-check sources.

Both are removed in the next step of #1621.

## Validation

`functional_tests/test_workflow_run_history_source_recheck_fix.py` compiles the application's own route bodies and task sequence from source, with storage and identity doubled:

- Personal and group run lists and run items return 200 and every run, even though any per-run source re-check would fail.
- A missing workflow or run still answers 404.
- The route module no longer refers to `authorize_workflow_run_read` or the old 403 messages.
- A single-task workflow succeeds when re-reading its saved output against its sources would fail.
- `approvals.html`, rendered with Jinja, contains the screening notice only when `enable_content_screening` is true, and keeps the content screening request filter.

Without the fix, all 8 behavior checks in that file fail; the version check and the container 404 checks pass either way.

`functional_tests/test_workflow_history_source_access.py` now checks that a run-bound preview is kept without any source lookup, and that a legacy unbound preview is still hidden. Its activity-stream test also gained `M365_ACTIVE_STATES` in its namespace, which the stream function needs.

`ui_tests/test_content_screening_classic.py` checks in a browser that the notice appears only while screening is on, and that a screening request's **Open content review** link stays visible either way. The classic fixture now answers the Approvals page's Microsoft 365 requests and pending-actions calls with empty lists.

A before-and-after run of 29 related workflow, route and provenance test files found no new failures. Remaining failures in those files also fail without this change.
