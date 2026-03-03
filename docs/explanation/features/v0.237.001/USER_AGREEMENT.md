# User Agreement Feature

## Overview

The User Agreement feature allows administrators to configure a global agreement that users must accept before uploading files to workspaces. This provides organizations with a mechanism to ensure users acknowledge terms, policies, or guidelines before contributing documents to the system.

**Version Implemented:** v0.237.001

## Key Features

- **Global Admin Configuration**: Single configuration point in Admin Settings → Workspaces tab
- **Workspace Type Selection**: Apply agreement to personal workspaces, group workspaces, public workspaces, and/or chat
- **Markdown Support**: Agreement text supports Markdown formatting for rich content
- **Word Limit**: 200-word limit with real-time word count display
- **Daily Acceptance Option**: Optional setting to only prompt users once per day
- **Activity Logging**: All acceptances are logged for compliance tracking

## Configuration

### Accessing User Agreement Settings

1. Navigate to **Admin Settings** from the sidebar
2. Select the **Workspaces** tab
3. Scroll to the **User Agreement** section

### Configuration Options

| Setting | Description |
|---------|-------------|
| **Enable User Agreement** | Master toggle to enable/disable the feature |
| **Apply To** | Checkboxes to select which workspace types require agreement (Personal, Group, Public, Chat) |
| **Agreement Text** | Markdown-formatted text displayed to users (max 200 words) |
| **Enable Daily Acceptance** | When enabled, users only need to accept once per day instead of every upload |

### Example Agreement Text

```markdown
## File Upload Agreement

By uploading files to this workspace, you agree to the following:

1. **Ownership**: You have the right to share this content
2. **Confidentiality**: You will not upload confidential information without authorization
3. **Compliance**: All uploads comply with organizational policies

For questions, contact your administrator.
```

## User Experience

### File Upload Flow

1. User initiates a file upload (drag-and-drop or file picker)
2. System checks if User Agreement is enabled for that workspace type
3. If enabled and user hasn't accepted today (when daily acceptance is on):
   - Modal appears with agreement text
   - User can **Accept & Upload** or **Cancel**
4. Upon acceptance:
   - Acceptance is logged to activity logs
   - File upload proceeds normally
5. If cancelled:
   - Upload is aborted
   - No files are uploaded

### Modal Interface

The User Agreement modal displays:
- Agreement title
- Rendered Markdown content (sanitized via DOMPurify)
- Daily acceptance info (when enabled): "You only need to accept once per day"
- **Cancel** button - Dismisses modal, cancels upload
- **Accept & Upload** button - Records acceptance, proceeds with upload

## Technical Architecture

### Backend Components

| File | Purpose |
|------|---------|
| `route_frontend_admin_settings.py` | Handles form submission for User Agreement settings |
| `route_backend_user_agreement.py` | API endpoints for checking/accepting agreements |
| `functions_activity_logging.py` | `log_user_agreement_accepted()` and `has_user_accepted_agreement_today()` |

### Frontend Components

| File | Purpose |
|------|---------|
| `admin_settings.html` | Configuration UI in Workspaces tab |
| `base.html` | User Agreement upload modal |
| `user-agreement.js` | `UserAgreementManager` module for handling upload checks |

### API Endpoints

#### Check Agreement Status
```
GET /api/user_agreement/check?workspace_type={type}&workspace_id={id}&action_context=file_upload
```

**Response:**
```json
{
    "needsAgreement": true,
    "agreementText": "## Agreement\n\nYour agreement text...",
    "enableDailyAcceptance": true
}
```

#### Record Acceptance
```
POST /api/user_agreement/accept
Content-Type: application/json

{
    "workspace_type": "personal",
    "workspace_id": "default",
    "action_context": "file_upload"
}
```

**Response:**
```json
{
    "success": true,
    "message": "User agreement accepted"
}
```

### Settings Data Model

Settings are stored in `app_settings` with the following keys:

```python
{
    "enable_user_agreement": False,  # Master toggle
    "user_agreement_text": "",       # Markdown content
    "user_agreement_apply_to": [],   # List: ["personal", "group", "public", "chat"]
    "enable_user_agreement_daily": False  # Daily acceptance toggle
}
```

### Activity Log Entry

When a user accepts the agreement, an activity log entry is created:

```python
{
    "activity_type": "user_agreement_accepted",
    "user_id": "user@example.com",
    "workspace_type": "personal",
    "workspace_id": "default",
    "action_context": "file_upload",
    "timestamp": "2026-01-21T10:30:00Z"
}
```

## Integration Points

### Workspace Upload Handlers

The following files integrate with `UserAgreementManager`:

| File | Workspace Type | Integration Point |
|------|----------------|-------------------|
| `workspace-documents.js` | Personal | `handleFileUpload()` |
| `group_workspaces.html` | Group | `uploadFiles()` |
| `public_workspace.js` | Public | `handleFileUpload()` |
| `chat-input-actions.js` | Chat | `handleFileSelect()` |

### Usage Pattern

```javascript
// Example integration in upload handler
async function handleFileUpload(files) {
    // Check user agreement before upload
    UserAgreementManager.checkBeforeUpload(
        'personal',           // workspace type
        'default',            // workspace id
        files,                // files to upload
        function(approvedFiles) {
            // This callback runs after user accepts
            proceedWithUpload(approvedFiles);
        }
    );
}
```

## Security Considerations

- Agreement text is sanitized using DOMPurify before rendering
- All API endpoints require user authentication
- Admin settings are protected by `@admin_required` decorator
- Activity logs provide audit trail for compliance

## Dependencies

- **marked.js**: Markdown parsing
- **DOMPurify**: HTML sanitization
- **Bootstrap 5**: Modal component

## Sidebar Navigation

The User Agreement settings are accessible via:
- **Admin Settings** → **Workspaces** submenu → **User Agreement**

This follows the same pattern as other workspace-related admin settings like Retention Policy.

## Testing

To test the feature:

1. Enable User Agreement in Admin Settings → Workspaces
2. Select at least one workspace type (e.g., Personal Workspaces)
3. Enter agreement text
4. Navigate to a personal workspace
5. Attempt to upload a file
6. Verify the agreement modal appears
7. Accept and verify the upload proceeds
8. Check Activity Logs for acceptance entry

## Related Features

- [Activity Logging](../v0.229.001/ACTION_LOGGING_AND_CITATION.md) - Acceptance tracking
- [Public Workspaces](../v0.229.001/PUBLIC_WORKSPACES.md) - Workspace types
