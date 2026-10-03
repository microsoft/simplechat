# Workflow Test Harness Repair Fix

Fixed in version: **0.261.233**

Related issue: [#1621](https://github.com/microsoft/simplechat/issues/1621) (follow-up). This change touches only functional tests.

## Issue

Several workflow functional tests could not reach their assertions on `paullizer-react-v2-ui`, because their harnesses had fallen behind the application. Nothing flagged it, because CI doesn't run these files.

- `test_workflow_task_result_handoff.py`: every Analyze inventory run failed with "Workflow task 'Extract inventory' failed after 1 attempt(s)" (9 tests).
- `test_workflow_data_flow_execution.py`: 8 tests failed, including all three cases of `test_real_run_entrypoint_persists_the_deliverable_outcome`.
- `test_workflow_runtime_integration.py`: 4 durable runs ended as `failed` instead of completing or waiting for approval.
- `test_workflow_m365_rebase_integration.py`: 9 Microsoft 365 wait and continuation tests failed the same way, through the shared runtime fixture.
- `test_analyze_workflow_publication_integration.py`: all 8 tests errored at setup.
- The group workflow round-trip harness, and every file that reuses it, failed with `ModuleNotFoundError: No module named 'functions_workflow_chat_delivery'` whenever `application/single_app` wasn't on `PYTHONPATH`: 13 files and 1,857 failing tests.
- `test_analyze_artifact_phase7_rollout_rollback.py` left fake `functions_generated_file_exports` and `functions_assistant_table_exports` modules in `sys.modules`. In the same pytest process, later files failed at import, for example `cannot import name 'build_generated_file_export' from 'functions_generated_file_exports'`.

## Root Cause

The harnesses compile production functions from source into a namespace, or load real modules from their files, and supply every global those functions use. Production code gained dependencies the harnesses didn't supply:

- `functions_document_analysis.py` now calls `generated_file_publication_allowed()` from `functions_orchestration_execution_policy.py`. The `NameError` was caught by the task runner, so it surfaced only as a failed task.
- `_run_authorized_workflow_impl` now applies the calendar run-time context through `_apply_workflow_run_time_context`, which reads `WORKFLOW_SCHEDULED_TRIGGER_TYPES` and `workflow_run_time_context` from `functions_workflow_schedules.py`. This failed every run that went through the real run entrypoint.
- `_run_personal_workflow_impl` now authorizes Microsoft 365 actions inside `_ensure_execution_context`. That function compares the Flask `session` user with the workflow owner, and for a run without a signed-in owner it looks the owner up with `read_user_settings_snapshot`. The entrypoint test supplied neither, nor `workflow_m365_manifests` or the run store read that the entrypoint now makes, and its assistant-tracking fake didn't accept the new `assistant_message_id` argument.
- `functions_workflow_context.py` now resolves each request's limits through `resolve_model_token_budget` from `functions_model_capabilities.py`. The publication fixture still patched the removed `resolve_model_token_limits`.
- `functions_personal_workflows.py` now imports `functions_workflow_chat_delivery`. The round-trip harness loads each real module from its file, in import-graph order, without the application folder on the import path, and its list didn't include the chat delivery contract. With the folder on the path, the harness imported the contract inside its stub scope and left that copy, bound to its stub logging module, in `sys.modules`.
- The Phase 7 rollout test installed its lightweight planner stubs at import time with `sys.modules.setdefault` and never removed them.

## Technical Details

Files modified:

- `functional_tests/test_workflow_task_result_handoff.py`
- `functional_tests/test_workflow_data_flow_execution.py`
- `functional_tests/test_analyze_workflow_publication_integration.py`
- `functional_tests/test_group_workflow_round_trip_preservation.py`
- `functional_tests/test_workflow_draft_save_parity.py`
- `functional_tests/test_analyze_artifact_phase7_rollout_rollback.py`

Changes:

- **Inventory harness (`build_inventory_run`).** The Analyze namespace gets the real `generated_file_publication_allowed`; no orchestration task restricts these runs' files. The runner namespace gets the real `WORKFLOW_SCHEDULED_TRIGGER_TYPES` and `workflow_run_time_context`. All three have no application dependencies. This repairs the handoff, data-flow, runtime integration and Microsoft 365 rebase tests that run the real sequence or entrypoint.
- **Run entrypoint test.** The owner starts the run from a signed-in request, so the test supplies a Flask-style `session` for the owner and `_ensure_execution_context` takes its real reuse path. `read_user_settings_snapshot` fails the test if it is called, which proves the context was reused rather than rebuilt. The test also supplies `workflow_m365_manifests` for a workflow with no Microsoft 365 actions, a run store read that returns what the entrypoint saved, and an assistant-tracking fake that reuses a stored assistant message id, as the real helper does.
- **Publication fixture.** It now patches `functions_workflow_context.resolve_model_token_budget` with the same `model_budget` helper the Analyze chat fixture uses, keeping the original 1,000,000-token limits. With the limits applied, the saved report fits one prompt again, so the completion fake still checks that all 150 rows arrive together. The small-model test keeps its 16,000-token limits and still pages all 150 records. No fake was loosened.
- **Round-trip harness.** `functions_workflow_chat_delivery` joins the real-module list after `functions_m365_workflow_binding`, its dependency, in both the group round-trip harness and the save parity harness. The harness now loads the contract from its file and removes it afterwards, like every other module it manages.
- **Phase 7 rollout test.** A module-scoped `planner` fixture installs the stubs with `pytest.MonkeyPatch`, only for dependencies that aren't imported yet. It imports the planner over them, and on exit removes the planner if this scope imported it. The tests take the planner from the fixture, and the `__main__` runner uses the same context manager.

No application code or assertion changed for these repairs.

## Validation

Each file was run in its own pytest process, with `application/single_app` on `PYTHONPATH`, against an untouched worktree of the base commit and against this branch:

| File | Base | This branch |
| --- | --- | --- |
| `test_workflow_task_result_handoff.py` | 9 failed | all pass |
| `test_workflow_data_flow_execution.py` | 8 failed | all pass |
| `test_workflow_runtime_integration.py` | 4 failed | all pass |
| `test_workflow_m365_rebase_integration.py` | 9 failed | all pass |
| `test_analyze_workflow_publication_integration.py` | 8 errors | all pass |

`test_native_source_revocation_does_not_block_the_saved_report`, which proves that revoking a native source after its result is saved doesn't block the report, now runs and passes.

Without `application/single_app` on `PYTHONPATH`, the 13 files built on the round-trip harness went from 1,857 failing tests to none.

`test_analyze_artifact_phase7_rollout_rollback.py`, run in one pytest process with `test_generated_artifact_paging_and_guidance.py`, `test_orchestration_output_downloads.py`, `test_orchestration_result_claim_fencing.py`, `test_workflow_loop_limits.py`, `test_workflow_result_masking.py` and `test_workflow_runtime_integration.py`, went from 5 collection errors to 101 passed.
