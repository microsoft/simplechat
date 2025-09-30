# Create Group Permission Display Fix

**Version Implemented:** 0.229.001

## Issue Description
When the "Require Membership to Create Groups" setting was enabled in the admin settings, users without the required `CreateGroups` role could still see the "Create New Group" button on the My Groups page. When they clicked on it, they would encounter an error because the backend API correctly enforced the permission, but the frontend UI was not respecting the permission setting.

## Root Cause Analysis
The issue was in the `my_groups.html` template and the corresponding route handler:

1. **Frontend Template Issue**: The "Create New Group" button was displayed unconditionally without checking if the user had the required permissions.

2. **Missing Backend Context**: The route handler (`/my_groups`) was not passing the user's permission status to the template, so the frontend had no way to know whether to show or hide the button.

3. **JavaScript Event Handlers**: The JavaScript code was binding event handlers for create group functionality without checking permissions.

## Technical Details

### Files Modified
- `route_frontend_groups.py` - Added permission checking logic
- `templates/my_groups.html` - Added conditional display logic
- `config.py` - Updated version number

### Code Changes Summary

#### Backend Route Changes (`route_frontend_groups.py`)
```python
# Added permission checking logic
user = session.get('user', {})
settings = get_settings()
require_member_of_create_group = settings.get("require_member_of_create_group", False)

# Check if user can create groups
can_create_groups = True
if require_member_of_create_group:
    can_create_groups = 'roles' in user and 'CreateGroups' in user['roles']

return render_template("my_groups.html", can_create_groups=can_create_groups)
```

1. **JavaScript Permission Handling**:
   ```javascript
   const canCreateGroups = {{ can_create_groups|tojson }};
   const createGroupModal = canCreateGroups ? new bootstrap.Modal(document.getElementById('createGroupModal')) : null;
   
   if (canCreateGroups) {
     $("#createGroupForm").on("submit", handleCreateGroup);
   }
   ```

## Testing Approach
Created functional test `test_create_group_permission_fix.py` that validates:
- Template correctly implements conditional display logic
- Route passes permission status to template
- JavaScript handles permissions appropriately
- Modal and event handlers are conditional

## Impact Analysis
- **User Experience**: Users without permission no longer see a button they cannot use
- **Security**: No impact on security as backend API was already protected
- **Functionality**: No loss of functionality for authorized users
- **Compatibility**: Fully backward compatible

## Validation
- **Before Fix**: Users without `CreateGroups` role could see the button but got errors when clicking
- **After Fix**: Users without `CreateGroups` role don't see the button at all
- **Authorized Users**: Unaffected, can still create groups normally

## Related Features
This fix works in conjunction with:
- Admin Settings page where "Require Membership to Create Groups" is configured
- Azure AD App Registration roles configuration
- Backend API protection via `@create_group_role_required` decorator

## Configuration
The fix automatically respects the existing admin setting:
- **Setting**: `require_member_of_create_group`
- **Required Role**: `CreateGroups` (defined in Azure AD App Registration)
- **Location**: Admin Settings > Groups & Collaboration tab
