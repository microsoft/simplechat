# Group Workspace Delete Modal Fix (v0.241.004)

## Overview
Fixed the group workspace document delete flow so the revision-choice modal is always present and behaves the same way as the personal and public workspace pages.

Version Updated: 0.241.004

Implemented in version: **0.241.004**

## Issue Description
Deleting a document from Group Workspace could show `Delete confirmation dialog is unavailable. Refresh the page and try again.` instead of opening the revision-choice modal.

## Root Cause Analysis
The group delete modal markup had been embedded inside the `updateGroupStatusAlert()` JavaScript template instead of being rendered as standalone page markup.

When the active group was in the normal active state, that alert content was hidden, so the modal never existed in the DOM. The delete flow then failed closed as designed because its modal readiness guard could not find the dialog elements.

## Technical Details
Files modified:
- `application/single_app/templates/group_workspaces.html`
- `application/single_app/config.py`
- `functional_tests/test_group_document_delete_modal_wiring.py`
- `ui_tests/test_workspace_family_document_revision_delete_modal.py`

Code changes summary:
- Moved the group delete modal into standalone template markup in the content block.
- Removed the modal markup from the group status alert `innerHTML` template.
- Updated the workspace-family UI regression test to verify the modal exists before the delete action is triggered.
- Added a functional regression test that checks the group template keeps the modal outside the alert injection block.

Testing approach:
- Functional template-wiring regression coverage.
- Workspace-family UI regression coverage for personal, group, and public delete flows.

## Validation
Test results:
- The group delete flow now has a real page-level modal available on initial load.
- The fail-closed path still remains in place if the modal is actually removed or missing.

Before/after comparison:
- Before: group delete could fail immediately because no delete modal existed in the DOM for active groups.
- After: group delete opens the same revision-choice modal pattern used by the other workspace pages.

User experience improvements:
- Group document deletion is now consistent with personal and public workspaces.
- Users can choose between deleting the current revision or all revisions instead of getting blocked by missing modal wiring.