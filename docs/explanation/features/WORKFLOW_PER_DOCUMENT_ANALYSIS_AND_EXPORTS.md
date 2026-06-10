# Workflow Per-Document Analysis And Generated Office Exports

Implemented in version: **0.241.182**

Related version update:
- `application/single_app/config.py` reports version `0.241.182`.

## Overview

Workflow Analyze actions can now either run across the selected document set as one combined context or run the same prompt against each selected document separately. SimpleChat actions can also create generated Word documents and PowerPoint presentations, allowing workflow prompts to turn each per-document result into a saved workspace artifact.

Dependencies:
- `application/single_app/functions_document_actions.py`
- `application/single_app/functions_workflow_runner.py`
- `application/single_app/functions_simplechat_operations.py`
- `application/single_app/semantic_kernel_plugins/simplechat_plugin.py`
- `application/single_app/static/js/workspace/workspace_workflows.js`
- `application/single_app/templates/workspace.html`
- `application/single_app/templates/group_workspaces.html`

## Technical Specifications

Architecture overview:
- Analyze document action configuration includes `analysis_mode` with supported values `combined` and `per_document`.
- `combined` remains the default and preserves existing workflow behavior.
- `per_document` makes the runner prepare a one-document workflow for each selected document, reuse the existing Analyze execution path, and combine the replies, coverage, citations, generated artifacts, tabular outputs, token usage, and alert targets.
- Per-document prompts include runtime guidance telling the model or agent which document is being processed and that generated artifacts should be specific to that document.
- SimpleChat generated document actions expose `upload_word_document` and `upload_powerpoint_document` alongside the existing Markdown upload action.
- Group workflow SimpleChat actions default generated uploads to the current group workspace by resolving `workspace_scope="current"` through the plugin manifest `default_group_id`.
- The existing group upload path still enforces current group access checks before saving artifacts.

Configuration options:
- Workflow Analyze mode is saved in `document_action.analysis_mode` and mirrored into the legacy `analyze.analysis_mode` payload for compatibility.
- SimpleChat action capability maps include `upload_word_document` and `upload_powerpoint_document`.
- Older capability maps inherit the existing `upload_markdown_document` setting for the new Office upload actions when the new keys are absent.

File structure:
- Backend normalization: `application/single_app/functions_document_actions.py`
- Workflow execution: `application/single_app/functions_workflow_runner.py`
- Generated document helpers: `application/single_app/functions_simplechat_operations.py`
- Semantic Kernel tool wrapper: `application/single_app/semantic_kernel_plugins/simplechat_plugin.py`
- Workflow modal UI: `application/single_app/templates/workspace.html` and `application/single_app/templates/group_workspaces.html`
- Workflow modal behavior: `application/single_app/static/js/workspace/workspace_workflows.js`

## Usage Instructions

How to enable/configure:
1. Enable personal or group workflows from Admin Settings.
2. Ensure the workflow runner uses an agent or model that has access to the selected documents.
3. For generated Word or PowerPoint files, enable the matching SimpleChat capability on the action used by the workflow agent.

User workflow:
1. Open Personal Workspace or Group Workspaces.
2. Create or edit a workflow.
3. Set the document action to `Analyze`.
4. Select the documents to process.
5. Turn on `Run each document separately` when the same prompt should be applied independently to every selected document.
6. Use a prompt that asks the workflow agent to call the SimpleChat Word or PowerPoint upload action when saved artifacts are needed.

Integration points:
- Per-document Analyze uses the same workflow conversation and run history as combined Analyze.
- Generated Office artifacts are uploaded through the normal document processing pipeline.
- Group workflow artifacts save into the current group workspace when the workflow is executed from a group context.
- Workflow activity/history and alert conversation actions open linked conversations in a new browser tab so the current workflow view stays available.

## Testing And Validation

Functional coverage:
- `functional_tests/test_workflow_per_document_analysis_mode.py` verifies analysis mode normalization, per-document result combination, UI/static contracts, and new-tab link contracts.
- `functional_tests/test_simplechat_generated_office_exports.py` verifies generated Word and PowerPoint upload helpers, current group scope resolution, capability fallbacks, labels, and frontend capability contracts.

UI coverage:
- `ui_tests/test_workflow_document_action_modal.py` validates the `Run each document separately` modal control and the saved `analysis_mode='per_document'` payload.
- `ui_tests/test_workflow_priority_alert_modal.py` validates workflow alert conversation actions opening in a new tab and preserving mark-read behavior.

Performance and limitations:
- Per-document mode runs one Analyze operation per selected document, so runtime and model/tool usage scale with selected document count.
- Office byte rendering depends on the installed `python-docx` and `python-pptx` packages; upload helper tests skip the binary rendering assertion when those optional packages are unavailable locally.
- Per-document mode only changes Analyze behavior when more than one document is selected; a single selected document follows the standard Analyze execution path.
