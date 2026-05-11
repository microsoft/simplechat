# Group Status Management Feature

**Version Implemented:** 0.233.319  
**Feature Type:** Group Administration, Access Control  
**Module:** Group Workspaces

## Overview

The Group Status Management feature provides administrators with fine-grained control over group workspace operations through status-based access controls. This feature enables administrators to restrict or enable specific operations (document uploads, deletions, chat access) based on the group's current status, with full audit trail logging of all status changes.

## Purpose

This feature addresses several key use cases:
- **Compliance & Legal Holds:** Lock groups in read-only mode during audits or legal investigations
- **Storage Management:** Prevent new uploads while allowing cleanup operations
- **Project Lifecycle Management:** Transition groups through active, maintenance, and decommissioned states
- **Risk Mitigation:** Quickly disable problematic groups while preserving data

## Status Definitions

### 🟢 Active
**Full functionality enabled**
- ✅ Document uploads allowed
- ✅ Document deletions allowed
- ✅ Chat and document search enabled
- ✅ All group features operational

**Use Cases:**
- Normal day-to-day operations
- Active projects and teams
- Ongoing collaboration

---

### 🔒 Locked (Read-Only)
**Group is in read-only preservation mode**
- ❌ Document uploads **blocked**
- ❌ Document deletions **blocked**
- ✅ Chat and document search **allowed**
- ✅ Viewing existing documents **allowed**

**Use Cases:**
- Legal holds and compliance audits
- Project completion (preserve state)
- Historical reference archives
- Data preservation during investigations

**User Experience:**
```
Error: "This group is locked (read-only mode). Document uploads are disabled."
Error: "This group is locked (read-only mode). Document deletions are disabled."
```

---

### 📁 Upload Disabled
**Restrict new content while allowing cleanup**
- ❌ Document uploads **blocked**
- ✅ Document deletions **allowed**
- ✅ Chat and document search **allowed**
- ✅ Full read access to existing documents

**Use Cases:**
- Storage quota enforcement
- Preparation for group archival
- Cleanup phase before decommissioning
- Cost optimization (limit storage growth)

**User Experience:**
```
Error: "Document uploads are disabled for this group."
```

---

### ⭕ Inactive
**Group is completely disabled**
- ❌ Document uploads **blocked**
- ❌ Document deletions **blocked**
- ❌ Chat operations **blocked**
- ❌ Document access **blocked** (except admin viewing)

**Use Cases:**
- Decommissioned projects
- Suspended groups pending review
- Compliance violations
- Groups scheduled for deletion

**User Experience:**
```
Error: "This group is inactive. All operations are disabled."
```

---

## Technical Implementation

### Database Schema

#### Group Document Fields
```json
{
  "id": "group-uuid",
  "name": "Project Alpha",
  "status": "active",  // active | locked | upload_disabled | inactive
  "modifiedDate": "2025-01-15T10:30:00.000Z",
  "statusHistory": [
    {
      "old_status": "active",
      "new_status": "locked",
      "changed_by_user_id": "admin-user-id",
      "changed_by_email": "admin@company.com",
      "changed_at": "2025-01-15T10:30:00.000Z",
      "reason": "Legal hold for audit #2025-01"
    }
  ]
}
```

#### Activity Log Entry
```json
{
  "id": "activity-log-uuid",
  "activity_type": "group_status_change",
  "timestamp": "2025-01-15T10:30:00.000Z",
  "group": {
    "group_id": "group-uuid",
    "group_name": "Project Alpha"
  },
  "status_change": {
    "old_status": "active",
    "new_status": "locked",
    "changed_at": "2025-01-15T10:30:00.000Z",
    "reason": "Legal hold for audit #2025-01"
  },
  "changed_by": {
    "user_id": "admin-user-id",
    "email": "admin@company.com"
  },
  "workspace_type": "group",
  "workspace_context": {
    "group_id": "group-uuid"
  }
}
```

### API Endpoints

#### Update Group Status
**Endpoint:** `PUT /api/admin/control-center/groups/<group_id>/status`

**Request:**
```json
{
  "status": "locked",
  "reason": "Legal hold for audit #2025-01"
}
```

**Response (Success):**
```json
{
  "message": "Group status updated successfully",
  "old_status": "active",
  "new_status": "locked"
}
```

**Response (No Change):**
```json
{
  "message": "Group status unchanged",
  "status": "locked"
}
```

**Valid Status Values:**
- `active`
- `locked`
- `upload_disabled`
- `inactive`

---

### Enforcement Points

#### 1. Document Upload
**File:** `route_backend_group_documents.py`  
**Function:** `api_upload_group_document()`

```python
# Check if group status allows uploads
from functions_group import check_group_status_allows_operation
allowed, reason = check_group_status_allows_operation(group_doc, 'upload')
if not allowed:
    return jsonify({'error': reason}), 403
```

**Blocks when:**
- Status = `locked`
- Status = `upload_disabled`
- Status = `inactive`

---

#### 2. Document Deletion
**File:** `route_backend_group_documents.py`  
**Function:** `api_delete_group_document()`

```python
# Check if group status allows deletions
from functions_group import check_group_status_allows_operation
allowed, reason = check_group_status_allows_operation(group_doc, 'delete')
if not allowed:
    return jsonify({'error': reason}), 403
```

**Blocks when:**
- Status = `locked`
- Status = `inactive`

---

#### 3. Chat Operations
**File:** `route_backend_chats.py`  
**Function:** `chat_api()`

```python
if group_doc:
    # Check if group status allows chat operations
    from functions_group import check_group_status_allows_operation
    allowed, reason = check_group_status_allows_operation(group_doc, 'chat')
    if not allowed:
        return jsonify({'error': reason}), 403
```

**Blocks when:**
- Status = `inactive`

---

### Helper Functions

#### Check Status Permissions
**File:** `functions_group.py`  
**Function:** `check_group_status_allows_operation()`

```python
def check_group_status_allows_operation(group_doc, operation_type):
    """
    Check if the group's status allows the specified operation.
    
    Args:
        group_doc: The group document from Cosmos DB
        operation_type: One of 'upload', 'delete', 'chat', 'view'
    
    Returns:
        tuple: (allowed: bool, reason: str)
    """
    status = group_doc.get('status', 'active')
    
    status_permissions = {
        'active': {'upload': True, 'delete': True, 'chat': True, 'view': True},
        'locked': {'upload': False, 'delete': False, 'chat': True, 'view': True},
        'upload_disabled': {'upload': False, 'delete': True, 'chat': True, 'view': True},
        'inactive': {'upload': False, 'delete': False, 'chat': False, 'view': False}
    }
    
    permissions = status_permissions.get(status, status_permissions['active'])
    allowed = permissions.get(operation_type, False)
    
    if not allowed:
        return False, generate_helpful_error(status, operation_type)
    
    return True, ""
```

#### Log Status Change
**File:** `functions_activity_logging.py`  
**Function:** `log_group_status_change()`

```python
def log_group_status_change(
    group_id: str,
    group_name: str,
    old_status: str,
    new_status: str,
    changed_by_user_id: str,
    changed_by_email: str,
    reason: Optional[str] = None
) -> None:
    """
    Log group status change to activity_logs container for audit trail.
    Creates permanent record of who changed status, when, and why.
    """
    # Creates activity log entry with full audit information
```

---

## User Interface

### Control Center Modal
The group status can be changed through the Group Management Modal in the Control Center:

**Location:** Admin > Control Center > Groups > Manage Group

**UI Elements:**
1. **Group Status Control** section with dropdown
2. Options: Active, Locked (Read-only), Upload Disabled, Inactive
3. Optional "Reason" field for documenting the change
4. "Save Changes" button to apply the new status

**Visual Feedback:**
- Status badges with color coding
- Clear labels explaining each status option
- Confirmation for status changes

---

## Audit Trail

### Status History
Every status change is recorded in two places:

1. **Group Document** (`statusHistory` array):
   - Embedded in the group document
   - Full history of all status changes
   - Who, when, what, and why for each change

2. **Activity Logs Container**:
   - Permanent audit log
   - Queryable for compliance reporting
   - Independent of group deletion
   - Includes Application Insights logging

### Audit Queries

**Get all status changes for a group:**
```sql
SELECT * FROM c 
WHERE c.activity_type = 'group_status_change' 
  AND c.group.group_id = @group_id
ORDER BY c.timestamp DESC
```

**Find all groups locked in a date range:**
```sql
SELECT * FROM c 
WHERE c.activity_type = 'group_status_change' 
  AND c.status_change.new_status = 'locked'
  AND c.timestamp >= @start_date 
  AND c.timestamp <= @end_date
```

**Get all status changes by an admin:**
```sql
SELECT * FROM c 
WHERE c.activity_type = 'group_status_change' 
  AND c.changed_by.email = @admin_email
ORDER BY c.timestamp DESC
```

---

## Security & Permissions

### Required Permissions
To change group status, a user must have:
1. **Login Required** - Authenticated user session
2. **Admin Required** - Site-wide admin role
3. **Control Center Admin Required** - Specific control center permissions

### Permission Hierarchy
```
✅ Control Center Admin
  └─ Can change status of any group
  └─ Can view status history
  └─ Can override any status

❌ Group Owner
  └─ Cannot change group status
  └─ Group status supersedes owner permissions

❌ Group Admin
  └─ Cannot change group status
  └─ Subject to status restrictions
```

---

## Operational Guidelines

### Best Practices

#### ✅ DO:
- Document the reason for status changes
- Use "locked" for compliance holds
- Use "upload_disabled" for quota management
- Use "inactive" before deletion
- Review status history regularly
- Set status back to "active" when appropriate

#### ❌ DON'T:
- Change status without documenting reason
- Leave groups in restrictive states indefinitely
- Use "inactive" for temporary restrictions
- Forget to communicate status changes to group members
- Change status during active user operations

### Status Transition Workflows

#### Project Completion
```
Active → Locked
Reason: "Project completed, preserving final state"
```

#### Storage Cleanup
```
Active → Upload Disabled
Reason: "Storage quota reached, cleanup required"
→ (After cleanup) → Active
```

#### Decommissioning
```
Active → Upload Disabled
→ (After review) → Locked
→ (After approval) → Inactive
→ (After archival) → Delete Group
```

#### Legal Hold
```
Active → Locked
Reason: "Legal hold for case #XYZ"
→ (After hold release) → Active
```

---

## Monitoring & Reporting

### Key Metrics
- Number of groups by status
- Status change frequency
- Average time in each status
- Most common status change reasons

### Dashboard Queries
```sql
-- Groups by status
SELECT c.status, COUNT(1) as group_count 
FROM c 
WHERE c.id != c.user_id 
GROUP BY c.status

-- Recent status changes
SELECT TOP 20 * FROM c 
WHERE c.activity_type = 'group_status_change' 
ORDER BY c.timestamp DESC
```

---

## Troubleshooting

### Users Can't Upload Documents

**Check:**
1. Group status (`active` required for uploads)
2. User role (Owner, Admin, or DocumentManager required)
3. Group workspace feature enabled in settings

**Solution:**
```
If status is locked or upload_disabled:
→ Admin changes status to "active"
```

---

### Chat Not Working in Group

**Check:**
1. Group status (`active`, `locked`, or `upload_disabled` required)
2. Group status is not `inactive`

**Solution:**
```
If status is inactive:
→ Admin changes status to "active" or "locked"
```

---

### Need to Preserve Group Data

**Solution:**
```
Change status to "locked"
Reason: "Data preservation - [explain why]"
```

This prevents all modifications while maintaining full read access.

---

## Migration & Backwards Compatibility

### Default Behavior
- Groups without a `status` field default to `active`
- Existing groups continue to function normally
- No migration required for existing groups

### Gradual Rollout
1. Feature enabled with default "active" status
2. Admins can set status on groups as needed
3. No disruption to existing workflows

---

## Related Features

- **Group Workspaces** - Parent feature providing group collaboration
- **Document Management** - Status controls document operations
- **Control Center** - Administrative interface for status management
- **Activity Logging** - Audit trail for compliance

---

## Testing

### Test Coverage

**Functional Tests:** `functional_tests/test_group_status_enforcement.py`

**Test Scenarios:**
1. ✅ Upload blocked when status = locked
2. ✅ Upload blocked when status = upload_disabled
3. ✅ Upload blocked when status = inactive
4. ✅ Upload allowed when status = active
5. ✅ Delete blocked when status = locked
6. ✅ Delete blocked when status = inactive
7. ✅ Delete allowed when status = active
8. ✅ Delete allowed when status = upload_disabled
9. ✅ Chat blocked when status = inactive
10. ✅ Chat allowed for all other statuses
11. ✅ Status changes logged to activity_logs
12. ✅ Status history maintained in group document
13. ✅ UI elements hidden/shown based on status (v0.234.004)

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 0.234.005 | 2025-01-XX | Fixed UI visibility - updateRoleDisplay now checks both role AND status |
| 0.234.004 | 2025-01-XX | Added dynamic UI visibility - hides upload/create controls for restricted groups |
| 0.234.003 | 2025-01-XX | Added status alert boxes to group workspace pages |
| 0.234.002 | 2025-01-XX | Fixed status persistence bug in backend |
| 0.234.001 | 2025-01-XX | Fixed status display bug in Control Center |
| 0.233.321 | 2025-01-XX | Added dynamic help text for status selection in Control Center |
| 0.233.320 | 2025-01-XX | Fixed backend status reading (was hardcoded to 'active') |
| 0.233.319 | 2025-12-20 | Initial implementation with 4 status types and full audit logging |

---

## References

**Related Files:**
- [functions_group.py](../../application/single_app/functions_group.py) - Status validation logic
- [functions_activity_logging.py](../../application/single_app/functions_activity_logging.py) - Audit logging
- [route_backend_control_center.py](../../application/single_app/route_backend_control_center.py) - Admin API
- [route_backend_group_documents.py](../../application/single_app/route_backend_group_documents.py) - Document enforcement
- [route_backend_chats.py](../../application/single_app/route_backend_chats.py) - Chat enforcement
- [control_center.html](../../application/single_app/templates/control_center.html) - Admin UI
- [group_workspaces.html](../../application/single_app/templates/group_workspaces.html) - UI visibility controls
- [manage_group.html](../../application/single_app/templates/manage_group.html) - Status alerts

**Related Documentation:**
- [Group Status UI Visibility](GROUP_STATUS_UI_VISIBILITY.md) - Dynamic UI hiding feature
- [Activity Logging](../explanation/activity_logging.md)
