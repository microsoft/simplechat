# RETENTION_POLICY_DEFAULTS.md

**Feature**: Admin-Configurable Default Retention Policies  
**Version**: v0.237.001

## Overview and Purpose

The Retention Policy Defaults feature allows administrators to configure organization-wide default retention periods for conversations and documents across all workspace types (personal, group, and public). Users can choose to use the organization default or set their own custom retention period. Administrators also have the ability to force push defaults to override all custom policies.

## Key Features

- **Organization Defaults**: Set default retention periods for conversations and documents per workspace type
- **User Choice**: Users see "Using organization default (X days)" option and can override with custom settings
- **Conditional Display**: Default settings only appear for enabled workspace types
- **Force Push**: Administrators can push organization defaults to all workspaces, overriding custom settings
- **Activity Logging**: Force push actions are logged for audit purposes
- **Settings Auto-Save**: Force push automatically saves pending settings changes before executing

## Technical Specifications

### Architecture Overview

The feature integrates with the existing retention policy system and adds:

1. **Backend Settings** - 6 new settings fields for default retention values
2. **Admin UI** - Dropdown selectors in Admin Settings for each workspace type
3. **API Endpoints** - New endpoints for fetching defaults and force pushing
4. **User UI Integration** - Updated profile, control center, and workspace manager
5. **Execution Logic** - Resolution of 'default' values at policy execution time

### New Settings Fields

Added to `functions_settings.py`:

| Setting | Default Value | Description |
|---------|---------------|-------------|
| `default_retention_conversation_personal` | `'none'` | Default conversation retention for personal workspaces |
| `default_retention_document_personal` | `'none'` | Default document retention for personal workspaces |
| `default_retention_conversation_group` | `'none'` | Default conversation retention for group workspaces |
| `default_retention_document_group` | `'none'` | Default document retention for group workspaces |
| `default_retention_conversation_public` | `'none'` | Default conversation retention for public workspaces |
| `default_retention_document_public` | `'none'` | Default document retention for public workspaces |

**Note**: Value `'none'` means no automatic deletion. Numeric values represent days.

### API Endpoints

#### Get Retention Defaults

**Endpoint**: `GET /api/retention-policy/defaults/<workspace_type>`

**Parameters**:
- `workspace_type`: One of `personal`, `group`, or `public`

**Response**:
```json
{
  "success": true,
  "workspace_type": "personal",
  "defaults": {
    "conversation_retention_days": "none",
    "document_retention_days": "30"
  }
}
```

**Authentication**: Requires user authentication (`@login_required`)

#### Force Push Retention Defaults

**Endpoint**: `POST /api/admin/retention-policy/force-push`

**Request Body**:
```json
{
  "scopes": ["personal", "group", "public"]
}
```

**Response**:
```json
{
  "success": true,
  "message": "Defaults pushed to 150 items",
  "updated_count": 150,
  "scopes": ["personal", "group"],
  "details": {
    "personal": 100,
    "group": 50
  }
}
```

**Authentication**: Requires admin authentication (`@admin_required`)

### File Structure

**Backend Files**:
- `functions_settings.py` - New default retention settings fields
- `route_frontend_admin_settings.py` - Handling for saving new settings
- `route_backend_retention_policy.py` - New API endpoints
- `functions_retention_policy.py` - `resolve_retention_value()` helper function
- `functions_activity_logging.py` - `log_retention_policy_force_push()` function

**Frontend Files**:
- `templates/admin_settings.html` - Default Retention Policies section, Force Push modal
- `templates/profile.html` - Updated retention dropdowns with org default option
- `templates/control_center.html` - Updated group and public workspace retention UI
- `static/js/workspace-manager.js` - Public workspace retention settings

## Usage Instructions

### Configuring Organization Defaults (Admin)

1. Navigate to **Admin Settings** > **Content** tab
2. Scroll to the **Retention Policy** section
3. For each enabled workspace type, you'll see:
   - **Default Conversation Retention Days**: How long conversations are kept
   - **Default Document Retention Days**: How long documents are kept
4. Select the desired defaults from the dropdown (1 day to 10 years, or "Don't delete")
5. Click **Save All Settings**

### Force Pushing Defaults (Admin)

1. In the **Default Retention Policies** section, click **Force Push Defaults to All**
2. In the modal, select which workspace types to update
3. Review the warning about overriding custom policies
4. Click **Force Push** to confirm
5. The system will:
   - First save any pending settings changes
   - Then push defaults to all selected workspaces
   - Display a summary of updated items
6. Click **Close** when complete

### User Experience

Users see updated retention options in their workspace settings:

- **Using organization default (X days)** - Uses the admin-configured default
- **Don't delete** - Keep items indefinitely
- **Custom values** - 1 day to 10 years

When "Using organization default" is selected:
- The actual default value is shown (e.g., "30 days")
- If the admin changes the default, the user's policy automatically follows
- Users can override by selecting a specific value

## Activity Logging

Force push actions are logged to the `activity_logs` container with:

- **Activity Type**: `retention_policy_force_push`
- **Admin Info**: User ID and email of admin who executed
- **Scopes**: Which workspace types were affected
- **Results**: Breakdown of updates per workspace type
- **Total Updated**: Number of workspaces/users updated
- **Timestamp**: When the action occurred

## UI/UX Details

### Admin Settings Modal Flow

1. **Initial State**: Shows Cancel and Force Push buttons
2. **Processing**: 
   - Status shows "Saving settings first..."
   - Then "Pushing defaults to workspaces..."
3. **Completed**: 
   - Cancel and Force Push buttons hide
   - Only Close button visible
   - Results summary displayed

### Conditional Visibility

Default retention dropdowns only appear when the corresponding workspace type is enabled:
- Personal workspace defaults shown only when `enable_retention_policy_personal` is checked
- Group workspace defaults shown only when `enable_retention_policy_group` is checked
- Public workspace defaults shown only when `enable_retention_policy_public` is checked

## Testing and Validation

### Test Coverage

The feature can be validated by:
1. Setting organization defaults in Admin Settings
2. Verifying the defaults appear in user-facing dropdowns
3. Testing the Force Push functionality
4. Checking activity logs for audit records
5. Verifying retention policy execution respects 'default' values

### Performance Considerations

- Force push iterates through all users/groups/workspaces
- Large deployments may take several seconds to complete
- Progress indicator shown during execution
- Non-blocking - admin can continue using the application

## Known Limitations

- Force push is an all-or-nothing operation per workspace type
- No option to selectively target specific users/groups
- Requires page refresh to see updated defaults in user UI after admin changes

## Related Documentation

- Retention Policy system documentation
- Admin Settings configuration guide
- Activity Logging reference
