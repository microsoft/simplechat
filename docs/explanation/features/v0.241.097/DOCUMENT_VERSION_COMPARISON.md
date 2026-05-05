# Document Version Comparison

Implemented in version: **0.241.097**
Related version update:
- `application/single_app/config.py` now reports version `0.241.097`.

## Overview

Document comparison now supports selecting multiple stored revisions from the same document family instead of limiting comparison targets to the current revision of each selected document. This lets users compare `v1` vs `v2`, `v1` vs `v3`, or mix one document's older revisions with other selected documents in both chat and workflow experiences.

Dependencies:
- `application/single_app/functions_documents.py`
- `application/single_app/route_backend_documents.py`
- `application/single_app/route_backend_group_documents.py`
- `application/single_app/route_backend_public_documents.py`
- `application/single_app/static/js/chat/chat-documents.js`
- `application/single_app/static/js/chat/chat-messages.js`
- `application/single_app/static/js/workspace/workspace_workflows.js`
- `application/single_app/templates/chats.html`
- `application/single_app/templates/workspace.html`

## Technical Specifications

Architecture overview:
- Each stored document revision keeps its own document id while sharing a `revision_family_id` with the rest of the family.
- New per-scope version endpoints expose all stored revisions for a selected document family in personal, group, and public workspaces.
- Chat comparison expands selected current documents into version-specific comparison targets and lets the user choose the left-side baseline from the chosen revisions.
- Workflow comparison uses the same version-target model and saves version-specific ids in the existing comparison payload fields.

API endpoints:
- `GET /api/documents/<document_id>/versions`
- `GET /api/group_documents/<document_id>/versions?group_id=<group_id>`
- `GET /api/public_workspace_documents/<document_id>/versions?workspace_id=<workspace_id>`

Configuration options:
- Existing document action capability limits continue to apply.
- Comparison document counts are now based on the selected version targets instead of the number of currently selected document families.

File structure:
- Version metadata exposure: `application/single_app/functions_documents.py`
- Personal document versions route: `application/single_app/route_backend_documents.py`
- Group document versions route: `application/single_app/route_backend_group_documents.py`
- Public workspace versions route: `application/single_app/route_backend_public_documents.py`
- Chat comparison UI: `application/single_app/templates/chats.html`
- Chat comparison behavior: `application/single_app/static/js/chat/chat-documents.js`, `application/single_app/static/js/chat/chat-messages.js`
- Workflow comparison UI and payload builder: `application/single_app/templates/workspace.html`, `application/single_app/static/js/workspace/workspace_workflows.js`

## Usage Instructions

How to use in chat:
1. Open chat and enable document search.
2. Select one or more documents.
3. Change the action to `Compare`.
4. Choose the versions you want to compare from `Comparison Versions`.
5. Pick the left-side baseline version.
6. Send the compare request.

How to use in workflows:
1. Open `Personal Workspace` and go to `Your Workflows`.
2. Create or edit a workflow.
3. Change the action type to `Compare`.
4. Select workspace documents and choose `Use selected workspace documents`.
5. Pick the comparison versions and choose the left-side baseline version.
6. Save the workflow.

Integration points:
- Chat requests continue to submit `left_document_id` and `right_document_ids`, but those ids can now be multiple revisions from one document family.
- Workflow saves use the same payload shape, so no backend workflow contract change is required.

## Testing And Validation

Functional coverage:
- `functional_tests/test_document_actions_and_comparison_feature.py` verifies the new version endpoints, version-aware chat and workflow selectors, and the linked feature documentation.

UI coverage:
- `ui_tests/test_chat_document_action_selector_labels.py` validates the chat comparison version selector and left-side version picker.
- `ui_tests/test_workflow_document_action_modal.py` validates workflow version selection and saved comparison payloads.

Performance and limitations:
- Version selectors currently load on demand per selected document family.
- Workflow version selection is driven from the currently selected personal workspace documents.
- Existing administrator document action limits still cap how many comparison targets can run in one request.
