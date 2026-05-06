# Generated Analysis Artifact Workspace Promotion

Overview

Implemented in version: **0.241.127**

This feature completes the next step of the generated analysis artifact flow by letting users move chat-scoped generated outputs into workspace documents. Personal promotions are added immediately to the requester’s workspace. Group and public promotions create a visible pending document shell, notify the workspace, and only become usable after an approver accepts the request.

Dependencies

- Chat artifact authorization and download routes in `application/single_app/route_enhanced_citations.py`
- Generated document processing helpers in `application/single_app/functions_simplechat_operations.py`
- Group workspace document routes in `application/single_app/route_backend_group_documents.py`
- Public workspace document routes in `application/single_app/route_backend_public_documents.py`
- Chat artifact card rendering in `application/single_app/static/js/chat/chat-messages.js`
- Group and public workspace document UIs in `application/single_app/templates/group_workspaces.html` and `application/single_app/static/js/public/public_workspace.js`

Technical Specifications

Architecture overview

- Chat artifact cards now expose an `Add to Workspace` action for blob-backed generated artifacts.
- The backend resolves the target workspace from the active conversation or the selected chat scope.
- Personal promotions download the artifact bytes and queue the normal workspace document processing flow immediately.
- Group and public promotions create a pending workspace document record with source blob metadata, approval metadata, and notification entries.
- Group and public approvers can accept the request from the workspace document list, which then queues the existing document processing pipeline against the stored artifact blob.

Promotion flow

- `POST /api/chat_artifacts/promote`
  - `personal`: uploads directly into the personal workspace.
  - `group`: creates a pending group document and sends approval notifications.
  - `public`: creates a pending public document and sends approval notifications.
- `POST /api/group_documents/<document_id>/approve-generated-artifact`
  - Queues the stored artifact into the active group workspace document shell.
- `POST /api/public_documents/<document_id>/approve-generated-artifact`
  - Queues the stored artifact into the active public workspace document shell.

Pending document behavior

- Pending group/public promoted files are visible in the workspace list immediately.
- Pending files have no processed blob/chunk output yet, so they are not usable for search/chat until approval queues document processing.
- Pending promoted files use a unique artifact-suffixed file name to avoid archiving an existing same-name live document before approval is granted.

Notifications

- Workspace-scoped notifications are created with `approval_request_pending` so the workspace sees a reviewable request.
- The requester also receives an `approval_request_pending_submitter` notification.
- On approval, the requester receives an `approval_request_approved` notification when processing is queued.

Usage Instructions

User workflow

- Generate a review, comparison, or tabular artifact in chat.
- Click `Add to Workspace` on the generated artifact card.
- If the target is personal, the file is added to the personal workspace immediately.
- If the target is group or public, the file appears in the workspace as pending approval.
- A group or public workspace approver clicks `Approve` in the workspace document list.
- After approval, the file begins processing and becomes usable like any other workspace document once processing completes.

Target resolution rules

- If the current conversation is already scoped to a group or public workspace, that workspace is used.
- Otherwise, the chat scope selection must resolve to exactly one workspace target.
- Ambiguous multi-scope selections are rejected in the chat UI before the request is sent.

Testing and Validation

Functional coverage

- `functional_tests/test_generated_artifact_workspace_promotion.py`
- `ui_tests/test_chat_generated_tabular_output_card.py`

Validation performed

- Python diagnostics and `py_compile` on the touched backend files
- Workspace UI diagnostics for the touched group/public files
- Focused functional regression for promotion route and approval UI wiring

Known limitations

- Group/public promotion currently supports approval but not a dedicated deny action.
- Reloaded artifact cards do not yet deduplicate repeated promotion requests for the same artifact automatically.