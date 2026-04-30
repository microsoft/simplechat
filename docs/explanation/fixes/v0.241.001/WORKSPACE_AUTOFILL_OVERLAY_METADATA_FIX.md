# Workspace Autofill Overlay Metadata Fix (v0.240.007)

## Issue Description
Opening the personal workspace could still trigger browser autofill overlay errors in the console even after the plugin modal hardening. The workspace page renders several hidden modals and builder surfaces up front, and those non-login controls were still exposed to password-manager classification.

## Root Cause Analysis
The earlier workspace autofill fix only covered the plugin modal's password fields. The main workspace template, the shared model-endpoint modal, and the agent builder still exposed text, email, select, and password controls without consistent autofill-ignore metadata. Some autofill overlays treated those fields like login candidates and hit a null autocomplete assumption while classifying them.

## Version Implemented
Fixed/Implemented in version: **0.240.007**

## Technical Details
- Files modified:
  - `application/single_app/templates/workspace.html`
  - `application/single_app/templates/_agent_modal.html`
  - `application/single_app/templates/_multiendpoint_modal.html`
  - `application/single_app/config.py`
  - `functional_tests/test_workspace_autofill_overlay_metadata.py`
  - `ui_tests/test_workspace_page_autofill_metadata.py`
- Code changes summary:
  - Added explicit autofill-ignore metadata to the prompt, document metadata, and share-document forms rendered by the workspace page.
  - Added a workspace-scoped normalization helper that stamps `autocomplete` and common password-manager ignore attributes onto workspace tab fields and modal controls at load time.
  - Hardened the shared agent modal container and the model-endpoint secret fields with explicit autofill metadata.
  - Added focused functional and UI regression tests for the workspace autofill markers.
  - Bumped the application version to `0.240.007`.
- Testing approach:
  - Run the focused workspace autofill functional test.
  - Run the workspace UI metadata test when an authenticated UI environment is available.

## Validation
- Before: opening the workspace could still surface autofill overlay null-reference errors when the browser inspected hidden workspace controls.
- After: the workspace page and its shared modals expose explicit non-login autofill metadata, reducing extension-side crashes during page analysis.