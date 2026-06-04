# Workflow File Sync Triggers

Implemented in version: **0.241.133**

Fixed/Implemented in version: **0.241.133**

## Overview

Workflows can now trigger configured File Sync sources before the prompt runs. The workflow can run manually, on an interval, or in Monitor File Sync Changes mode. Monitor mode checks selected File Sync sources on the configured interval and only continues into the workflow prompt when the sync detects new or changed files.

## Dependencies

- File Sync must be enabled for the selected personal, group, or public workspace source.
- The current workflow owner must still be authorized for each selected File Sync source when saving and running the workflow.
- Dynamic changed-file processing works with Analyze workflows and reuses the existing workflow document action pipeline.
- Version was updated in `application/single_app/config.py` to `0.241.133` for the workflow trigger and run-item storage changes.

## Technical Specifications

- Workflows persist a `file_sync` block with selected source scope, source ID, wait mode, continue mode, and dynamic changed-document targeting.
- A new `file_sync` workflow trigger type powers Monitor File Sync Changes mode.
- The workflow scheduler treats `file_sync` workflows as due scheduled work and records `file_sync_monitor` as the trigger source.
- File Sync runs now record `created`, `updated`, `changed_documents`, and `changed_document_ids` in run metadata.
- File Sync items record `last_sync_run_id` and `last_sync_action` for traceability.
- Workflows store durable per-document run items in the `personal_workflow_run_items` container partitioned by `run_id`.
- Resume Failed reruns only failed document run items from a previous Analyze workflow run and disables File Sync for the retry run.

## API Endpoints

- `GET /api/user/workflows/file-sync-sources` returns sanitized File Sync sources the current user can select for a workflow.
- `GET /api/user/workflows/<workflow_id>/runs/<run_id>/items` returns per-item batch tracking records for a workflow run.
- `POST /api/user/workflows/<workflow_id>/runs/<run_id>/resume-failed` starts a follow-up workflow run for failed document items.

## File Structure

- `application/single_app/functions_personal_workflows.py` - workflow trigger validation, File Sync config normalization, and run-item persistence helpers.
- `application/single_app/functions_workflow_runner.py` - File Sync pre-run execution, changed-document prompt context, dynamic Analyze targeting, and per-item tracking callbacks.
- `application/single_app/functions_file_sync.py` - inline run support and changed-document metadata on File Sync runs/items.
- `application/single_app/route_backend_workflows.py` - File Sync source picker, run-item list, and resume-failed endpoints.
- `application/single_app/static/js/workspace/workspace_workflows.js` - workflow modal File Sync controls, monitor run mode, and resume-failed history action.
- `application/single_app/templates/workspace.html` - workflow modal File Sync form controls.
- `functional_tests/test_workflow_file_sync_triggers.py` - static functional coverage for backend and frontend contracts.
- `ui_tests/test_workspace_workflow_file_sync_controls.py` - optional Playwright coverage for the workflow File Sync modal controls.

## Usage Instructions

Create or edit a personal workflow, enable File Sync Before Run, select one or more sync sources, and choose whether the workflow should always continue or only continue when files changed. For Monitor File Sync Changes, select that run mode, choose the interval, and keep the default complete-and-changed behavior.

For batch document processing, choose Analyze and enable Use changed files as Analyze targets. The workflow can save without static document IDs; each run uses the documents created or updated by the File Sync pre-run.

If a batch run records failed document items, open the workflow run history and select Resume failed. The follow-up run targets only the failed documents from that previous run.

## Testing and Validation

- Python compile coverage: `python -m py_compile` for changed backend modules.
- JavaScript syntax coverage: `node --check application/single_app/static/js/workspace/workspace_workflows.js` and `node --check application/single_app/static/js/workspace/workspace-file-sync.js`.
- Functional coverage: `functional_tests/test_workflow_file_sync_triggers.py`.
- UI coverage: `ui_tests/test_workspace_workflow_file_sync_controls.py`.

## Known Limitations

- Monitor mode is polling-based, not a push notification from remote storage.
- Resume Failed currently supports Analyze workflow document items.
- Queue-only File Sync pre-runs cannot be combined with continue-only-on-change because the workflow needs completed sync metadata to know what changed.
