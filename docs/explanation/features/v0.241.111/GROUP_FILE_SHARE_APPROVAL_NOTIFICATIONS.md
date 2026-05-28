# Group File Share Approval Notifications

## Overview

Version: 0.241.111

Implemented in version: **0.241.111**

Group document sharing now follows the same review model as personal document sharing. Documents shared to another group are visible to the receiving group as pending, but they are not available to group document search until a group Owner, Admin, or Document Manager approves the share. Share recipients and share originators now receive notifications for pending, approved, and denied share decisions.

Dependencies:

- `application/single_app/route_backend_group_documents.py`
- `application/single_app/route_backend_documents.py`
- `application/single_app/functions_notifications.py`
- `application/single_app/templates/group_workspaces.html`
- `functional_tests/test_group_file_share_approval_notifications.py`
- `ui_tests/test_group_workspace_shared_document_approval.py`

## Technical Specifications

### Architecture Overview

- Group shares are stored as status-qualified `shared_group_ids` entries such as `group-id,not_approved` and `group-id,approved`.
- Pending group shares are listed for the receiving group but do not satisfy the Azure AI Search access filter until approval changes the entry to `approved`.
- Pending-share notifications are sent to the receiving group's Owner, Admins, and Document Managers as personal notifications so regular group members are not asked to review shares they cannot approve.
- Approval and denial notifications are sent to the user who initiated the group share, with fallback to the source group owner when legacy share metadata is unavailable.
- Receiving groups can approve, deny, or remove a shared document, but cannot view the source group's shared-recipient list or delete the original document.

### API Endpoints

- `POST /api/group_documents/<document_id>/share-with-group` creates a pending group share and notifies receiving group reviewers.
- `POST /api/group_documents/<document_id>/approve-share-with-group` approves a pending group share and notifies the share initiator.
- `DELETE /api/group_documents/<document_id>/remove-self` removes the active group from a shared document, treating pending removal as a denial.
- `GET /api/group_documents/<document_id>/shared-groups` is restricted to managers in the owning group.

### File Structure

- `application/single_app/route_backend_group_documents.py`
- `application/single_app/route_backend_documents.py`
- `application/single_app/functions_documents.py`
- `application/single_app/functions_notifications.py`
- `application/single_app/templates/group_workspaces.html`

## Usage Instructions

1. In the owning group workspace, an Owner, Admin, or Document Manager opens the document Share action and selects a target group.
2. Owners, Admins, and Document Managers in the receiving group receive a notification and see the document as pending in group documents.
3. A receiving group reviewer approves or denies the share.
4. Approved documents become available to group document search; denied documents are removed from the receiving group view.

## Testing And Validation

Functional coverage:

- `functional_tests/test_group_file_share_approval_notifications.py`

UI coverage:

- `ui_tests/test_group_workspace_shared_document_approval.py`

Known limitations:

- Legacy bare group share entries are treated as approved for compatibility. New shares use explicit `not_approved` and `approved` status values.