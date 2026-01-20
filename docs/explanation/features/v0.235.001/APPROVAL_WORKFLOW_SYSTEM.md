# Approval Workflow System for Control Center

## Overview
The Approval Workflow System adds a comprehensive approval process for sensitive administrative operations in the Control Center. This system ensures that high-impact actions require review and approval from authorized users before execution, providing an audit trail and preventing unauthorized or accidental changes.

## Version Information
- **Implemented in**: Version 0.234.034
- **Feature Type**: Security & Governance Enhancement
- **Scope**: Control Center Administrative Operations

## Feature Description

### Purpose
Enable a controlled approval process for sensitive group management operations, requiring approval from group owners or other administrators before execution. This provides:
- **Accountability**: Every sensitive action requires documented justification
- **Review Process**: Group owners or admins must review and approve changes
- **Audit Trail**: Complete history of approval requests, approvals, and denials
- **Auto-Expiration**: Requests automatically expire after 3 days to prevent stale approvals
- **Notification Integration**: Seamless integration with existing notification system

### Scope of Protected Operations
The following Control Center operations now require approval:

1. **Take Ownership** - Admin assumes ownership of a group
2. **Transfer Ownership** - Transfer group ownership to another user
3. **Delete Documents** - Delete all documents within a group
4. **Delete Group** - Permanently delete an entire group

## Architecture

### Database Schema

#### Cosmos DB Container: `approvals`
- **Partition Key**: `/group_id`
- **TTL**: Enabled (3-day auto-expiration)
- **Document Structure**:
  ```json
  {
    "id": "uuid",
    "group_id": "group_id",
    "group_name": "Group Name",
    "action_type": "take_ownership|transfer_ownership|delete_documents|delete_group",
    "requested_by": "user_id",
    "reason": "Reason for request",
    "status": "pending|approved|denied",
    "created_at": "ISO timestamp",
    "expires_at": "ISO timestamp (created_at + 3 days)",
    "approved_by": "user_id (if approved)",
    "approved_at": "ISO timestamp (if approved)",
    "denied_by": "user_id (if denied)",
    "denied_at": "ISO timestamp (if denied)",
    "admin_comment": "Optional comment from approver",
    "auto_denied": true|false,
    "action_params": {
      "newOwnerId": "user_id (for transfer_ownership)"
    }
  }
  ```

### Backend Components

#### 1. `functions_approvals.py` (NEW)
Core approval workflow management system.

**Key Functions**:
- `create_approval_request(group_id, group_name, action_type, requested_by, reason, action_params=None)`
  - Creates a new approval request with 3-day TTL
  - Returns approval ID for tracking
  - Sends notification to eligible approvers

- `get_pending_approvals(user_id, filters=None)`
  - Retrieves approval requests for current user
  - Filters by status, action type, and search query
  - Determines approval eligibility using `_can_user_approve()`

- `approve_request(approval_id, approved_by, group_id, comment=None)`
  - Approves request and executes the action
  - Calls appropriate execution function
  - Updates approval status and sends notifications

- `deny_request(approval_id, denied_by, group_id, comment)`
  - Denies request with required comment
  - Updates approval status
  - Sends notification to requester

- `auto_deny_expired_approvals()`
  - Background job function
  - Finds approvals past expiration date
  - Auto-denies with `auto_denied` flag
  - Sends expiration notifications

**Approval Eligibility Logic** (`_can_user_approve()`):
Users can approve a request if they are:
- The group owner, OR
- A ControlCenterAdmin, OR
- An admin (system administrator)

AND they are NOT the person who created the request (cannot approve own requests).

**Action Execution Functions**:
- `_execute_take_ownership(group_id, requested_by)` - Transfers ownership to requesting admin
- `_execute_transfer_ownership(group_id, new_owner_id)` - Transfers ownership to specified user
- `_execute_delete_documents(group_id, requested_by)` - Deletes all documents in group
- `_execute_delete_group(group_id)` - Permanently deletes the entire group

#### 2. `route_backend_control_center.py` (MODIFIED)
Added new approval endpoints and modified existing group management endpoints.

**New Endpoints**:
- `GET /api/admin/control-center/approvals`
  - Lists approval requests with filtering and pagination
  - Filters: status, action_type, search query
  - Only returns approvals user is eligible to see/approve
  
- `POST /api/admin/control-center/approvals/<approval_id>/approve`
  - Approves an approval request
  - Executes the associated action
  - Requires: groupId in body, optional comment
  
- `POST /api/admin/control-center/approvals/<approval_id>/deny`
  - Denies an approval request
  - Requires: groupId and comment in body

**Modified Endpoints** (now create approval requests):
- `POST /api/admin/control-center/groups/<group_id>/take-ownership`
  - Now requires `reason` parameter
  - Creates approval request instead of immediate execution
  - Returns `approval_id` instead of confirmation

- `POST /api/admin/control-center/groups/<group_id>/transfer-ownership`
  - Now requires `reason` and `newOwnerId` parameters
  - Creates approval request instead of immediate execution
  - Returns `approval_id` instead of confirmation

- `DELETE /api/admin/control-center/groups/<group_id>`
  - Now requires `reason` in request body
  - Creates approval request instead of immediate deletion
  - Returns `approval_id` instead of confirmation

- `POST /api/admin/control-center/groups/<group_id>/delete-documents` (NEW)
  - Creates approval request for document deletion
  - Requires `reason` parameter
  - Returns `approval_id`

#### 3. `app.py` (MODIFIED)
Added scheduled background job for auto-denying expired approvals.

**Background Thread**:
```python
def check_expired_approvals():
    while True:
        try:
            time.sleep(21600)  # Check every 6 hours
            auto_deny_expired_approvals()
        except Exception as e:
            logging.error(f"Error in approval expiration check: {e}")
```

Runs as daemon thread, checks every 6 hours for expired approvals and auto-denies them.

#### 4. `config.py` (MODIFIED)
Added Cosmos DB container configuration:
```python
cosmos_approvals_container = cosmos_database.create_container_if_not_exists(
    id='approvals',
    partition_key=PartitionKey(path='/group_id'),
    default_ttl=-1
)
```

### Frontend Components

#### 1. Control Center UI - Approvals Tab
New dedicated tab in Control Center for managing approval requests.

**Features**:
- Responsive table displaying all approval requests
- Filter by status (all, pending, approved, denied)
- Filter by action type (all, take_ownership, transfer_ownership, delete_documents, delete_group)
- Search by group name or reason
- Pagination support
- Real-time approval/denial actions
- Loading indicators and error handling

**Table Columns**:
- Status (badge: Pending/Approved/Denied/Auto-Denied)
- Action Type (badge with icon)
- Group Name
- Reason
- Requested By
- Created At
- Actions (Approve/Deny buttons when eligible)

#### 2. Approval Action Modal
Modal dialog for approving or denying requests.

**Components**:
- Approval/Denial confirmation
- Comment field (optional for approval, required for denial)
- Approve/Deny action buttons
- Request context display

#### 3. Group Management Modal (MODIFIED)
Updated group management modal to include reason input for ownership changes.

**Changes**:
- Added `ownershipReasonGroup` textarea
- Shows/hides based on ownership dropdown selection
- Required for "Take Ownership" and "Transfer to Another User" options
- Integrated into `saveGroupChanges()` function

#### 4. JavaScript Manager: `ApprovalManager`
New JavaScript object following the `GroupManager` pattern.

**Key Functions**:
- `init()` - Initialize approval management and bind events
- `loadApprovals(page)` - Load approvals from API with filters and pagination
- `renderApprovalRow(approval)` - Render individual approval row
- `showApprovalModal(approvalId, groupId, action)` - Display approval/denial modal
- `handleApprove()` - Process approval request
- `handleDeny()` - Process denial request
- `updatePagination(totalCount, currentPage, pageSize)` - Update pagination controls
- `refreshApprovals()` - Reload current page

**Event Handlers**:
- Search input filtering
- Status filter dropdown
- Action type filter dropdown
- Approve/Deny button clicks
- Pagination controls

#### 5. Modified JavaScript Functions
Updated existing JavaScript functions to handle approval workflow:

**`saveGroupChanges()`**:
- Validates reason field when ownership change selected
- Includes reason in API request body
- Shows approval request confirmation instead of immediate success
- Displays approval ID in response message

**`deleteDocuments()`**:
- Prompts for reason using browser prompt
- Validates reason input
- Calls POST /delete-documents endpoint
- Shows approval request confirmation

**`deleteGroup()`**:
- Prompts for reason using browser prompt
- Validates reason input
- Includes reason in DELETE request body
- Shows approval request confirmation

## User Workflows

### Creating an Approval Request

1. **Navigate to Control Center** → Groups tab
2. **Open Group Management Modal** for target group
3. **Select Sensitive Action**:
   - Take Ownership (dropdown)
   - Transfer Ownership (dropdown + user selection)
   - Delete Documents (button)
   - Delete Group (button)
4. **Provide Reason** (required)
5. **Confirm Action** → Approval request created
6. **Notification Sent** to eligible approvers (group owner + admins)

### Approving a Request

1. **Navigate to Control Center** → Approvals tab
2. **View Pending Requests** (filtered automatically)
3. **Click "Approve"** button on desired request
4. **Add Optional Comment** (recommended but not required)
5. **Confirm Approval** → Action executes immediately
6. **Notification Sent** to requester confirming approval and execution

### Denying a Request

1. **Navigate to Control Center** → Approvals tab
2. **View Pending Requests**
3. **Click "Deny"** button on desired request
4. **Provide Denial Reason** (required)
5. **Confirm Denial**
6. **Notification Sent** to requester with denial reason

### Monitoring Approvals

1. **Navigate to Control Center** → Approvals tab
2. **Use Filters**:
   - Status: All, Pending, Approved, Denied
   - Action Type: All, specific action types
   - Search: Group name or reason keywords
3. **View Request Details** in table
4. **Check Expiration Time** for pending requests (shows hours remaining)
5. **Review Historical Approvals** (approved/denied remain visible)

## Auto-Denial Process

### Trigger Conditions
Approval requests are automatically denied when:
- Request is still in `pending` status
- Current time exceeds `expires_at` timestamp (3 days from creation)
- Background job detects expired request

### Auto-Denial Workflow
1. **Background Job** runs every 6 hours (`app.py`)
2. **Queries** for pending approvals past expiration
3. **Updates Status** to `denied` with `auto_denied: true` flag
4. **Sends Notification** to requester explaining auto-denial
5. **Logs Event** for audit trail

### Backup Expiration
Cosmos DB TTL provides secondary expiration mechanism:
- Document is automatically deleted 3 days after creation
- Acts as cleanup for expired approvals
- Ensures no indefinite pending requests

## Notification Integration

### Notification Events

#### 1. Approval Request Created
- **Recipients**: All eligible approvers (group owner + admins)
- **Message**: "[User] has requested [action] for group [group_name]. Reason: [reason]. Expires in 3 days."
- **Action Link**: Link to Approvals tab with filter

#### 2. Request Approved
- **Recipients**: Original requester
- **Message**: "Your request for [action] on group [group_name] has been APPROVED by [approver]. Comment: [comment]"
- **Action Link**: Link to group or approvals tab

#### 3. Request Denied
- **Recipients**: Original requester
- **Message**: "Your request for [action] on group [group_name] has been DENIED by [denier]. Reason: [comment]"
- **Action Link**: Link to approvals tab

#### 4. Request Auto-Denied
- **Recipients**: Original requester
- **Message**: "Your request for [action] on group [group_name] has expired and was automatically denied after 3 days."
- **Action Link**: Link to create new request

## Security Considerations

### Authorization
- **Request Creation**: Any admin can create approval requests
- **Request Approval**: Only eligible users can approve (owner OR admin, but NOT requester)
- **Request Denial**: Only eligible users can deny (same as approval)
- **View Permissions**: Users only see requests they created or can approve

### Audit Trail
All approval actions are logged with:
- Requester ID and timestamp
- Approver/Denier ID and timestamp
- Reason for request
- Admin comment (for approval/denial)
- Auto-denial flag (for expired requests)

### Isolation
- Approval requests partitioned by `group_id`
- Users cannot approve their own requests
- Approvals tied to specific groups for access control validation

## Configuration

### Required Environment Variables
No new environment variables required. Uses existing:
- Azure Cosmos DB connection settings
- Notification system settings

### Cosmos DB Configuration
Container created automatically on startup:
```python
cosmos_approvals_container = cosmos_database.create_container_if_not_exists(
    id='approvals',
    partition_key=PartitionKey(path='/group_id'),
    default_ttl=-1  # Enable TTL, set per-document
)
```

### Approval Expiration Settings
**Expiration Period**: 3 days (72 hours)
- Set at request creation: `expires_at = created_at + 3 days`
- Checked by background job every 6 hours
- Cosmos DB TTL cleanup ensures document deletion

**Configurable in**: `functions_approvals.py`
```python
expires_at = datetime.now(timezone.utc) + timedelta(days=3)
```

## Testing

### Manual Testing Checklist

#### Backend Approval Creation
- [ ] Create take_ownership approval request
- [ ] Create transfer_ownership approval request
- [ ] Create delete_documents approval request
- [ ] Create delete_group approval request
- [ ] Verify approval ID returned in response
- [ ] Verify notification sent to eligible approvers

#### Backend Approval Actions
- [ ] Approve take_ownership request
- [ ] Approve transfer_ownership request
- [ ] Approve delete_documents request
- [ ] Approve delete_group request
- [ ] Deny each request type with comment
- [ ] Verify action execution after approval
- [ ] Verify notification sent after approval/denial

#### Frontend Approvals Tab
- [ ] Navigate to Approvals tab
- [ ] Verify pending approvals displayed
- [ ] Filter by status (pending/approved/denied)
- [ ] Filter by action type
- [ ] Search by group name
- [ ] Verify pagination works correctly
- [ ] Verify "Approve" button shown when eligible
- [ ] Verify "Cannot approve own request" message shown

#### Frontend Approval Actions
- [ ] Click "Approve" button → modal opens
- [ ] Submit approval with comment
- [ ] Click "Deny" button → modal opens
- [ ] Submit denial with comment
- [ ] Verify approval/denial success messages
- [ ] Verify approvals list refreshes after action

#### Group Management Integration
- [ ] Select "Take Ownership" → reason field appears
- [ ] Select "Transfer to Another User" → reason field appears
- [ ] Submit ownership change with reason
- [ ] Verify approval request created message
- [ ] Click "Delete Documents" → reason prompt appears
- [ ] Submit delete documents with reason
- [ ] Click "Delete Group" → reason prompt appears
- [ ] Submit delete group with reason

#### Auto-Denial Testing
- [ ] Create approval request
- [ ] Fast-forward system time by 3 days (OR wait)
- [ ] Trigger background job manually
- [ ] Verify request auto-denied
- [ ] Verify auto_denied flag set
- [ ] Verify notification sent to requester

#### Authorization Testing
- [ ] Verify group owner can approve requests
- [ ] Verify admin can approve requests
- [ ] Verify requester cannot approve own request
- [ ] Verify non-eligible users cannot see request
- [ ] Verify users only see relevant approvals

### Functional Test Files
No dedicated functional test file created yet. Recommended test file:
`functional_tests/test_approval_workflow_system.py`

## Performance Considerations

### Database Queries
- **List Approvals**: Partitioned by group_id, uses pagination
- **Approval Lookup**: Direct ID lookup within group partition
- **Expiration Check**: Query for pending + expired_at < now (runs every 6 hours)

### Optimization Strategies
- Partition by group_id ensures efficient queries
- TTL cleanup reduces database size over time
- Background job runs every 6 hours (not continuous)
- Pagination limits frontend data transfer

## Known Limitations

1. **Bulk Approvals**: No bulk approve/deny functionality yet
2. **Approval History**: Limited visibility into approval history per group
3. **Cancellation**: Requester cannot cancel pending requests
4. **Re-request**: No automatic retry after denial (must manually create new request)
5. **Mobile UI**: Approvals tab not optimized for mobile devices yet

## Future Enhancements

### Potential Improvements
1. **Approval Delegation**: Allow owners to delegate approval rights to specific users
2. **Escalation**: Auto-escalate to higher admin levels after certain time period
3. **Batch Operations**: Bulk approve/deny multiple requests
4. **Enhanced Audit**: Detailed activity timeline for each approval
5. **Email Notifications**: Send email alerts for approval requests (in addition to in-app)
6. **Request Cancellation**: Allow requesters to cancel pending requests
7. **Approval Templates**: Pre-defined reason templates for common scenarios
8. **Analytics Dashboard**: Metrics on approval patterns, average approval time, denial rates
9. **Custom Expiration**: Allow admins to configure expiration period per action type
10. **Approval Comments**: Threaded comments/discussion on approval requests

## Related Documentation
- [Control Center Overview](../admin_configuration.md)
- [Notification System](../features/NOTIFICATION_SYSTEM.md) (if exists)
- [Group Management](../features/GROUP_MANAGEMENT.md) (if exists)

## Support & Troubleshooting

### Common Issues

**Issue**: Approval requests not appearing in Approvals tab
- **Cause**: User not eligible to approve, or filter set incorrectly
- **Solution**: Check status filter is set to "Pending", verify user is group owner or admin

**Issue**: Cannot approve own request
- **Cause**: System prevents self-approval for security
- **Solution**: Ask another admin or the group owner to approve

**Issue**: Approval request expired
- **Cause**: Request was created more than 3 days ago
- **Solution**: Create a new approval request with updated reason

**Issue**: Action not executed after approval
- **Cause**: Approval succeeded but execution failed
- **Solution**: Check server logs for execution errors, verify group still exists

**Issue**: Notifications not sent
- **Cause**: Notification system error or user preferences
- **Solution**: Check notification system logs, verify user notification preferences

### Debug Logging
Enable approval workflow logging in `functions_approvals.py`:
```python
logging.debug(f"Creating approval request: {action_type} for group {group_id}")
logging.debug(f"Approval eligibility check: user={user_id}, group_owner={group_owner}")
```

## Conclusion
The Approval Workflow System provides a robust, secure, and user-friendly mechanism for managing sensitive Control Center operations. By requiring documented justification and multi-party approval, it ensures accountability while maintaining operational flexibility through auto-expiration and comprehensive notification integration.
