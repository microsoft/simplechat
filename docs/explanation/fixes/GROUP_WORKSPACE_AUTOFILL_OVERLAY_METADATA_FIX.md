# Group Workspace Autofill Overlay Metadata Fix (v0.240.007)

## Issue Description
Opening the group workspace could trigger browser autofill overlay errors in the console because the page renders hidden prompt, metadata, sharing, tag-management, and shared endpoint controls on load.

## Root Cause Analysis
The group workspace template still exposed multiple non-login text, select, and textarea controls without explicit `autocomplete` metadata or password-manager ignore markers. Some autofill overlays inspected those controls together with the shared endpoint secret fields and hit a null autocomplete assumption while classifying them.

## Version Implemented
Fixed/Implemented in version: **0.240.007**

## Technical Details
- Files modified:
  - `application/single_app/templates/group_workspaces.html`
  - `application/single_app/config.py`
  - `functional_tests/test_group_workspace_autofill_overlay_metadata.py`
  - `ui_tests/test_group_workspace_page_autofill_metadata.py`
- Code changes summary:
  - Added explicit autofill-ignore metadata to the group selector search field, group prompt form, group document metadata form, group share form, and group tag-management controls rendered at page load.
  - Added a group-workspace normalization helper that stamps `autocomplete` and common password-manager ignore attributes onto group page controls and hidden modal fields at startup.
  - Added focused functional and UI regression tests for the group workspace autofill markers.
  - Bumped the application version to `0.240.007`.
- Testing approach:
  - Run the focused group workspace autofill functional test.
  - Run the group workspace UI metadata test when an authenticated UI environment is available.

## Validation
- Before: opening the group workspace could still surface autofill overlay null-reference errors when extensions inspected hidden group workspace controls.
- After: the group workspace page exposes explicit non-login autofill metadata across its load-time controls, reducing extension-side crashes during page analysis.