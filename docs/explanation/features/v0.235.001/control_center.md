# Control Center Feature

**Version:** 0.230.002  
**Release Date:** October 2, 2025  
**Status:** Production Ready

## Overview

The **Control Center** is a comprehensive administrative interface that provides data and workspace management capabilities for administrators. This feature introduces powerful tools to manage users, groups, and public workspaces, offering granular control over access permissions, file upload restrictions, and system visibility.

## Key Features

### 1. Dashboard Overview
- **System Summary Cards**: Real-time statistics for users, groups, workspaces, and recent activity
- **Key Alerts**: Automated notifications for blocked users, locked groups, and unusual activity
- **Activity Trends**: Visual insights into system usage patterns (future enhancement)

### 2. User Management
- **Comprehensive User List**: View all users with pagination, search, and filtering
- **Access Control**: Grant or deny user access with permanent or time-based restrictions
- **File Upload Control**: Manage user permissions for personal workspace file uploads
- **Bulk Actions**: Apply changes to multiple users simultaneously
- **Activity Tracking**: Monitor user engagement, document count, and storage usage

### 3. Group Management (Future Enhancement)
- Placeholder for group management functionality
- Will include group permissions, membership management, and activity monitoring

### 4. Public Workspace Management (Future Enhancement)
- Placeholder for public workspace management functionality
- Will include visibility controls, permission management, and usage analytics

## Technical Architecture

### Backend Components

#### Database Schema Extensions
```javascript
// User Settings Schema Enhancement
{
  "settings": {
    "access": {
      "status": "allow|deny",
      "datetime_to_allow": "ISO8601_timestamp|null"
    },
    "file_uploads": {
      "status": "allow|deny", 
      "datetime_to_allow": "ISO8601_timestamp|null"
    }
    // ... existing settings
  }
}

// Activity Logs Container
{
  "id": "activity_log_id",
  "user_id": "user_partition_key",
  "activity_type": "login|chat|upload|document_action",
  "timestamp": "ISO8601_timestamp",
  "metadata": {}
}
```

#### API Endpoints
- `GET /api/admin/control-center/users` - Paginated user list with filtering
- `PATCH /api/admin/control-center/users/{user_id}/access` - Update user access permissions
- `PATCH /api/admin/control-center/users/{user_id}/file-uploads` - Update file upload permissions
- `POST /api/admin/control-center/users/bulk-action` - Execute bulk user actions

#### Authentication Middleware
- **Enhanced user_required decorator**: Checks access control restrictions
- **New file_upload_required decorator**: Validates file upload permissions
- **Automatic time-based restoration**: Expired restrictions are automatically cleared
- **Admin bypass**: Administrators bypass all access restrictions

### Frontend Components

#### User Interface
- **Responsive Bootstrap 5 design** with dark mode support
- **Tabbed interface** for different management areas
- **Interactive modals** for user management and bulk actions
- **Real-time search and filtering** with debounced input
- **Pagination controls** for large datasets

#### JavaScript Functionality
- **ControlCenter class**: Manages all client-side interactions
- **API integration**: Handles all backend communication
- **Toast notifications**: User feedback for actions
- **Form validation**: Ensures data integrity
- **Loading states**: Provides visual feedback during operations

## User Experience

### Admin Workflow

1. **Access Control Center**: Navigate via Admin dropdown in sidebar
2. **View Dashboard**: Monitor system health and key metrics
3. **Manage Users**: 
   - Search and filter users by name, email, or access status
   - Select individual users for detailed management
   - Use bulk actions for efficient multi-user operations
4. **Configure Restrictions**:
   - Set permanent or time-based access restrictions
   - Control file upload permissions independently
   - Monitor restriction status and automatic expiration

### Access Control Scenarios

#### Permanent Access Denial
```json
{
  "status": "deny",
  "datetime_to_allow": null
}
```
User cannot access Simple Chat until admin manually restores access.

#### Time-Based Access Restriction
```json
{
  "status": "deny", 
  "datetime_to_allow": "2025-10-05T12:00:00Z"
}
```
User access is automatically restored at the specified date/time.

#### File Upload Restrictions
Similar structure for controlling personal workspace file uploads while maintaining other functionality.

## Security Considerations

### Admin-Only Access
- All Control Center functionality requires Admin role
- No user can modify their own access status
- Comprehensive audit logging for all administrative actions

### Permission Separation
- Access control and file upload permissions are independent
- Granular control allows for nuanced user management
- Automatic expiration prevents permanent lockouts from forgotten restrictions

### Data Protection
- User activity data is aggregated, not detailed
- Personal information access follows existing privacy patterns
- All API endpoints use existing authentication and authorization

## Implementation Files

### Backend Files
```
route_frontend_control_center.py    # Main Control Center page
route_backend_control_center.py     # API endpoints
functions_authentication.py         # Enhanced middleware
config.py                          # Database schema
```

### Frontend Files
```
templates/control_center.html       # Main UI template
static/js/control-center.js        # Client-side functionality
templates/_sidebar_nav.html         # Navigation integration
```

### Testing Files
```
functional_tests/test_control_center_functionality.py
```

## Configuration

### Environment Variables
No new environment variables required. Uses existing Cosmos DB and authentication configuration.

### Database Requirements
- New `activity_logs` container with `/user_id` partition key
- Extended user settings schema (backward compatible)
- No migration required for existing data

## Limitations and Future Enhancements

### Current Limitations
- Group management is placeholder functionality
- Public workspace management is placeholder functionality
- Activity trends are visual placeholders
- Limited historical activity data

### Planned Enhancements
- Complete group management implementation
- Public workspace administration tools
- Advanced activity analytics and reporting
- Automated policy enforcement
- Integration with external identity providers
- Bulk user import/export functionality

## Usage Examples

### Restricting User Access Temporarily
1. Navigate to Control Center → User Management
2. Search for user by name or email
3. Click "Manage" button for target user
4. Set Access Status to "Deny Until..."
5. Select date/time for automatic restoration
6. Save changes

### Bulk File Upload Restrictions
1. Use search/filter to identify target users
2. Select multiple users via checkboxes
3. Click "Bulk Action" button
4. Choose "Update File Upload Permissions"
5. Set desired restriction (permanent or time-based)
6. Execute action

## Troubleshooting

### Common Issues
- **Control Center not visible**: Ensure user has Admin role
- **User restrictions not applying**: Check authentication middleware integration
- **Statistics not loading**: Verify Cosmos DB connectivity
- **Time-based restrictions not expiring**: Confirm system time synchronization

### Error Messages
- `"Access Denied: Access denied by administrator"` - User has permanent access restriction
- `"File Upload Denied: File uploads disabled until [date]"` - Time-based upload restriction active
- `"Insufficient permissions (Admin role required)"` - User lacks admin privileges

## Migration Notes

### Upgrading from Previous Versions
- No breaking changes to existing functionality
- User settings schema is backward compatible
- New database containers are created automatically
- Existing users default to "allow" status for both access and file uploads

### Rollback Considerations
- Remove Control Center navigation link
- User settings with new fields will be ignored by older versions
- No data loss occurs during rollback
- Activity logs container can be safely removed if needed

## Compliance and Auditing

### Audit Trail
- All administrative actions are logged with timestamps
- User access changes are recorded with admin identity
- Bulk actions include success/failure counts
- Activity logs provide compliance documentation

### Data Retention
- Activity logs follow existing data retention policies
- User access history is maintained in user settings
- Administrative action logs use Application Insights integration

This Control Center feature provides administrators with the tools needed for effective user and data management while maintaining security, usability, and compliance requirements.