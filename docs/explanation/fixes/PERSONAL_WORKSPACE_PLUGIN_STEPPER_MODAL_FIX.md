# Personal Workspace Plugin Stepper Modal Fix

Fixed/Implemented in version: **0.250.032**

## Issue Description

The personal workspace could throw `Cannot read properties of null (reading 'addEventListener')` from `plugin_modal_stepper.js` when user actions were disabled or unavailable by governance. The plugin modal markup was conditionally rendered, but the shared plugin stepper module was still loaded unconditionally near the end of the workspace page.

The personal document delete modal could also emit a browser accessibility warning because the focused delete button remained inside the modal while Bootstrap applied `aria-hidden` during hide.

## Root Cause Analysis

- `workspace.html` used the correct governance check when including `_plugin_modal.html`, but did not use the same check for `plugin_modal_stepper.js`.
- `plugin_modal_stepper.js` created `PluginModalStepper` immediately and `bindEvents()` assumed modal controls such as `#plugin-modal-next` existed.
- `workspace-documents.js` hid the delete modal directly from button click handlers without first releasing focus from the clicked modal button.

## Technical Details

Files modified:

- `application/single_app/templates/workspace.html`
- `application/single_app/static/js/plugin_modal_stepper.js`
- `application/single_app/static/js/workspace/workspace-documents.js`
- `application/single_app/config.py`
- `functional_tests/test_workspace_plugin_stepper_script_gating.py`
- `ui_tests/test_workspace_family_document_revision_delete_modal.py`

Code changes summary:

- The workspace page now loads `plugin_modal_stepper.js` only when the personal action modal is rendered.
- The stepper module now checks for `#plugin-modal` before creating the global `window.pluginModalStepper` instance.
- The personal document delete modal now blurs focused modal descendants before hiding.

## Validation

- Added a functional regression test that verifies script gating and defensive stepper initialization.
- Updated UI coverage for the personal document delete modal focus handoff.
- Ran JavaScript syntax checks and targeted pytest coverage for the changed tests.

Reference version update: `application/single_app/config.py` was updated to **0.250.032**.