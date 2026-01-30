# Control Center Application Roles

## Overview

Added two new application roles for finer-grained access control to the Control Center, enabling organizations to delegate administrative functions while maintaining security boundaries.

**Version Implemented:** v0.237.001

## New Roles

### Control Center Admin

| Property | Value |
|----------|-------|
| **Role Name** | Control Center Admin |
| **Description** | Full administrative access to Control Center functionality |
| **Access Level** | Full read/write access to all Control Center features |

**Permissions:**
- View all Control Center dashboards and metrics
- Manage user access and permissions
- Execute administrative operations (take ownership, transfer, delete)
- Approve/reject workflow requests
- Configure Control Center settings

### Control Center Dashboard Reader

| Property | Value |
|----------|-------|
| **Role Name** | Control Center Dashboard Reader |
| **Description** | Read-only access to Control Center dashboards |
| **Access Level** | View-only access to dashboards and metrics |

**Permissions:**
- View Control Center dashboard
- View activity trends and metrics
- View user statistics
- View group and workspace information
- **Cannot** perform administrative actions
- **Cannot** modify settings or configurations

## Use Cases

### Scenario 1: IT Operations Team
- **Need**: Monitor system health and usage without admin capabilities
- **Solution**: Assign "Control Center Dashboard Reader" role
- **Benefit**: Visibility into metrics without risk of accidental changes

### Scenario 2: Delegated Administration
- **Need**: Department leads manage their users' access
- **Solution**: Assign "Control Center Admin" role to specific individuals
- **Benefit**: Distributed administration without full application admin access

### Scenario 3: Compliance Auditors
- **Need**: Review activity logs and usage patterns
- **Solution**: Assign "Control Center Dashboard Reader" role
- **Benefit**: Audit capability without modification access

## Configuration

### Adding Roles to Entra ID Enterprise Application

1. Navigate to Azure Portal → Entra ID → Enterprise Applications
2. Find your SimpleChat application registration
3. Go to **App roles** 
4. Add the new roles from `appRegistrationRoles.json`

### Role Assignment

```json
{
  "roles": [
    {
      "allowedMemberTypes": ["User"],
      "description": "Full administrative access to Control Center",
      "displayName": "Control Center Admin",
      "isEnabled": true,
      "value": "ControlCenterAdmin"
    },
    {
      "allowedMemberTypes": ["User"],
      "description": "Read-only access to Control Center dashboards",
      "displayName": "Control Center Dashboard Reader",
      "isEnabled": true,
      "value": "ControlCenterDashboardReader"
    }
  ]
}
```

### Assigning Roles to Users

1. Navigate to Enterprise Application → Users and groups
2. Click **Add user/group**
3. Select user(s) to assign
4. Select the appropriate role
5. Click **Assign**

## Role Hierarchy

```
┌─────────────────────────────────────┐
│              Admin                   │  ← Full application admin
│  (All permissions)                   │
└─────────────────┬───────────────────┘
                  │
┌─────────────────▼───────────────────┐
│       Control Center Admin           │  ← Control Center admin only
│  (Full CC access, no app settings)   │
└─────────────────┬───────────────────┘
                  │
┌─────────────────▼───────────────────┐
│  Control Center Dashboard Reader     │  ← View-only access
│  (Read-only dashboard access)        │
└─────────────────────────────────────┘
```

## Integration with Existing Roles

| Existing Role | Control Center Access |
|---------------|----------------------|
| Admin | Full access (includes all CC permissions) |
| User | No Control Center access by default |
| Owner | Group-level access only |
| DocumentManager | No Control Center access |

| New Role | Control Center Access |
|----------|----------------------|
| ControlCenterAdmin | Full CC admin access |
| ControlCenterDashboardReader | Read-only CC dashboard access |

## Security Considerations

1. **Principle of Least Privilege**: Assign Dashboard Reader by default, escalate to Admin only when needed
2. **Audit Trail**: All Control Center actions are logged regardless of role
3. **Role Separation**: Dashboard Reader cannot perform any destructive operations
4. **Admin Oversight**: Full Admin role retains visibility into all role assignments

## Files Modified

- `appRegistrationRoles.json` - Added new role definitions

## Related Features

- [Control Center](../v0.235.001/control_center.md) - Main Control Center functionality
- [Approval Workflow System](../v0.235.001/APPROVAL_WORKFLOW_SYSTEM.md) - Protected operations requiring approval
- [Enhanced User Management](../v0.235.001/ENHANCED_USER_MANAGEMENT.md) - User metrics and management

## Migration Notes

Existing deployments should:
1. Update the Entra ID app registration with new roles
2. Assign appropriate roles to users who need Control Center access
3. Review existing Admin role assignments for potential role refinement
