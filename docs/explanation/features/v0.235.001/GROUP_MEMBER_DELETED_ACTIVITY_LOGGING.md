# Group Member Deleted Activity Logging

## Overview
Group member deletion activity logging provides comprehensive tracking of all group member removals, including both self-removals (members leaving) and administrative removals (owners/admins removing members). This feature creates permanent audit trails in the `activity_logs` container for compliance, governance, and group management analytics.

## Version Information
- **Implemented in**: Version 0.234.025
- **Migration**: Standardized from previous `type: 'group_member_removed'` to `activity_type: 'group_member_deleted'`

## Purpose
Track all group member removals to:
- Provide audit trails for group membership changes
- Enable compliance and governance reporting
- Monitor group dynamics and member turnover
- Support troubleshooting and user support
- Track admin actions vs. voluntary departures
- Generate analytics on group membership patterns

## Activity Type
The activity logs use `activity_type: 'group_member_deleted'` to identify member removal transactions.

## Action Types
Two distinct actions are tracked:
1. **`member_left_group`** - Member voluntarily left the group (self-removal)
2. **`admin_removed_member`** - Owner or Admin removed a member

## What Gets Logged

### Core Fields
- **User Information**: User ID of the person who performed the removal (for partitioning)
- **Removed By**: User ID, email, and role of the person initiating the removal
- **Removed Member**: User ID, email, and display name of the member being removed
- **Group Information**: Group ID and group name
- **Action**: Type of removal (self-removal vs. admin removal)
- **Timestamp**: ISO 8601 formatted timestamp of the removal
- **Description**: Human-readable description of what happened

## Activity Log Structure

### Member Self-Removal Example
```json
{
    "id": "uuid-string",
    "user_id": "leaving-user-id",
    "activity_type": "group_member_deleted",
    "action": "member_left_group",
    "timestamp": "2024-12-20T10:30:00.000Z",
    "created_at": "2024-12-20T10:30:00.000Z",
    "removed_by": {
        "user_id": "leaving-user-id",
        "email": "user@example.com",
        "role": "Member"
    },
    "removed_member": {
        "user_id": "leaving-user-id",
        "email": "user@example.com",
        "name": "John Doe"
    },
    "group": {
        "group_id": "group-oid",
        "group_name": "Marketing Team"
    },
    "description": "Member user@example.com left group Marketing Team"
}
```

### Admin Removal Example
```json
{
    "id": "uuid-string",
    "user_id": "admin-user-id",
    "activity_type": "group_member_deleted",
    "action": "admin_removed_member",
    "timestamp": "2024-12-20T10:30:00.000Z",
    "created_at": "2024-12-20T10:30:00.000Z",
    "removed_by": {
        "user_id": "admin-user-id",
        "email": "admin@example.com",
        "role": "Admin"
    },
    "removed_member": {
        "user_id": "removed-user-id",
        "email": "removed@example.com",
        "name": "Jane Smith"
    },
    "group": {
        "group_id": "group-oid",
        "group_name": "Marketing Team"
    },
    "description": "Admin admin@example.com removed member Jane Smith (removed@example.com) from group Marketing Team"
}
```

### Owner Removal Example
```json
{
    "id": "uuid-string",
    "user_id": "owner-user-id",
    "activity_type": "group_member_deleted",
    "action": "admin_removed_member",
    "timestamp": "2024-12-20T10:30:00.000Z",
    "created_at": "2024-12-20T10:30:00.000Z",
    "removed_by": {
        "user_id": "owner-user-id",
        "email": "owner@example.com",
        "role": "Owner"
    },
    "removed_member": {
        "user_id": "removed-user-id",
        "email": "removed@example.com",
        "name": "Bob Johnson"
    },
    "group": {
        "group_id": "group-oid",
        "group_name": "Engineering Team"
    },
    "description": "Owner owner@example.com removed member Bob Johnson (removed@example.com) from group Engineering Team"
}
```

## Implementation Details

### Function: `log_group_member_deleted`
Location: `functions_activity_logging.py`

**Parameters:**
- `removed_by_user_id` (str, required): ID of user performing the removal
- `removed_by_email` (str, required): Email of user performing the removal
- `removed_by_role` (str, required): Role of user performing the removal (Owner, Admin, Member)
- `member_user_id` (str, required): ID of the member being removed
- `member_email` (str, required): Email of the member being removed
- `member_name` (str, required): Display name of the member being removed
- `group_id` (str, required): ID of the group
- `group_name` (str, required): Name of the group
- `action` (str, required): Specific action ('member_left_group' or 'admin_removed_member')
- `description` (str, optional): Human-readable description of the action

### Route That Logs Member Deletions

**Route**: `DELETE /api/groups/<group_id>/members/<member_id>`  
**File**: `route_backend_groups.py`  
**Function**: `remove_member()`

**Scenarios:**
1. **Self-Removal**: Member removes themselves (cannot remove if they are owner)
2. **Admin Removal**: Owner or Admin removes another member
3. **Owner Protection**: Owner cannot be removed

## Querying Activity Logs

### Get All Member Deletions for a Group
```sql
SELECT * FROM c
WHERE c.group.group_id = 'group-id'
AND c.activity_type = 'group_member_deleted'
ORDER BY c.timestamp DESC
```

### Get All Removals Performed by a User
```sql
SELECT * FROM c
WHERE c.user_id = 'user-id'
AND c.activity_type = 'group_member_deleted'
ORDER BY c.timestamp DESC
```

### Get All Self-Removals (Members Who Left)
```sql
SELECT * FROM c
WHERE c.activity_type = 'group_member_deleted'
AND c.action = 'member_left_group'
ORDER BY c.timestamp DESC
```

### Get All Admin/Owner Removals
```sql
SELECT * FROM c
WHERE c.activity_type = 'group_member_deleted'
AND c.action = 'admin_removed_member'
ORDER BY c.timestamp DESC
```

### Track Removals of a Specific User Across All Groups
```sql
SELECT * FROM c
WHERE c.removed_member.user_id = 'user-id'
AND c.activity_type = 'group_member_deleted'
ORDER BY c.timestamp DESC
```

### Get Recent Member Deletions Across All Groups
```sql
SELECT * FROM c
WHERE c.activity_type = 'group_member_deleted'
ORDER BY c.timestamp DESC
OFFSET 0 LIMIT 50
```

### Distinguish Between Owner and Admin Removals
```sql
SELECT * FROM c
WHERE c.activity_type = 'group_member_deleted'
AND c.action = 'admin_removed_member'
AND c.removed_by.role = 'Owner'
ORDER BY c.timestamp DESC
```

## Integration with Application Insights

In addition to Cosmos DB storage, member deletion events are logged to Application Insights with:
- Event name: "Group member deleted"
- Full activity record as custom properties
- Log level: INFO

This enables:
- Real-time monitoring of group membership changes
- Alerting on unusual removal patterns
- Cross-system correlation with other events
- Azure Monitor integration

## Analytics Use Cases

### 1. Group Membership Auditing
Track who removed whom from which groups for compliance and governance.

### 2. Member Retention Analysis
Identify patterns of voluntary departures vs. administrative removals.

### 3. Admin Activity Monitoring
Monitor which admins/owners are removing members and how frequently.

### 4. Group Health Metrics
Analyze member turnover rates and stability of group membership.

### 5. User Experience Tracking
Understand why users are leaving groups (voluntary vs. removed).

### 6. Compliance Reporting
Generate reports showing all membership changes for specific time periods.

## Key Differences from Previous Implementation

### Before (Inline Logging)
```json
{
    "id": "uuid",
    "type": "group_member_removed",  // ❌ Non-standard field name
    "action": "admin_removed_member",
    "timestamp": "...",
    "removed_by_user_id": "...",
    "removed_by_email": "...",
    // Flat structure
}
```

### After (Standardized Logging)
```json
{
    "id": "uuid",
    "activity_type": "group_member_deleted",  // ✅ Standard field name
    "action": "admin_removed_member",
    "timestamp": "...",
    "removed_by": {  // ✅ Structured data
        "user_id": "...",
        "email": "...",
        "role": "..."
    },
    "removed_member": {  // ✅ Clear separation
        "user_id": "...",
        "email": "...",
        "name": "..."
    },
    "group": {  // ✅ Grouped context
        "group_id": "...",
        "group_name": "..."
    }
}
```

## Migration Notes

- **Field Name Change**: Changed from `type` to `activity_type` for consistency with other activity logs
- **Data Structure**: Improved organization with nested objects for clarity
- **Function Extraction**: Moved from inline logging to reusable function
- **Error Handling**: Enhanced with proper logging and non-blocking error handling
- **Backward Compatibility**: Old logs with `type: 'group_member_removed'` remain queryable but new logs use `activity_type: 'group_member_deleted'`

## Error Handling

The logging function includes comprehensive error handling:
- Errors are logged to Application Insights but don't break the member removal flow
- Console warnings are printed for debugging
- The member removal succeeds even if activity logging fails
- This ensures user experience is not impacted by logging issues

## Testing

Functional test: `test_group_member_deleted_activity_logging.py`

The test validates:
- ✅ Admin removal logging (Owner/Admin removes member)
- ✅ Self-removal logging (Member leaves group)
- ✅ Owner removal logging (Owner removes member)
- ✅ Group-level deletion queries
- ✅ Activity log structure and data integrity
- ✅ Proper action type tracking

## Business Rules

1. **Owner Protection**: Owners cannot leave groups or be removed - they must transfer ownership or delete the group
2. **Self-Removal**: Any member can remove themselves (except owner)
3. **Admin Removal**: Only Owners and Admins can remove other members
4. **Role Tracking**: The role of the person performing the removal is logged
5. **Bidirectional Tracking**: Both who removed and who was removed are logged

## Related Documentation

- [Group Status Change Activity Logging](./GROUP_STATUS_CHANGE_ACTIVITY_LOGGING.md)
- [Document Creation Activity Logging](./DOCUMENT_CREATION_ACTIVITY_LOGGING.md)
- [Activity Logging Architecture](./ACTIVITY_LOGGING_ARCHITECTURE.md)

## Performance Considerations

- Activity logging is non-blocking and won't impact member removal performance
- Logs are stored with the removed_by user_id as partition key for efficient querying
- Cosmos DB throughput may need adjustment based on group activity volume
- Application Insights logging is asynchronous

## Best Practices

1. **Query Optimization**: Use partition key (user_id) in queries when possible
2. **Data Retention**: Implement retention policies based on compliance requirements
3. **Monitoring**: Set up alerts for unusual member removal patterns (e.g., mass removals)
4. **Privacy**: Ensure descriptions don't contain sensitive information
5. **Analytics**: Regularly analyze member turnover to improve group health
6. **Compliance**: Maintain logs for required audit periods
7. **Reporting**: Build dashboards showing member removal trends over time
