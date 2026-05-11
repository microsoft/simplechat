# Group Notification Context Enhancement

## Overview
Enhanced group document notifications to include group names and automatically set the active group when users click notification links.

## Version
**Fixed in version: 0.234.060**

## Problem Statement
When users uploaded documents to group workspaces, the notifications:
1. Did not include the group name in the message, making it unclear which group the document belonged to
2. Linked to `/group_workspaces` without setting the active group, causing users to land on the wrong group

## Root Cause
1. The `create_group_notification()` call in `functions_documents.py` did not fetch the group details to include the group name
2. The `link_url` parameter was set to `/group_workspaces` without query parameters to set the active group

## Solution

### 1. Added Group Name to Notification Messages
**File**: `functions_documents.py` (lines 5264-5285)

```python
# Fetch group details to get group name
from functions_group import find_group_by_id
group = find_group_by_id(group_id)
group_name = group.get('name', 'Unknown Group') if group else 'Unknown Group'

create_group_notification(
    group_id=group_id,
    notification_type='document_processing_complete',
    title=notification_title,
    message=f"Document uploaded to {group_name} has been processed successfully with {total_chunks_saved} chunks.",
    link_url='/group_workspaces',
    link_context={
        'workspace_type': 'group',
        'group_id': group_id,
        'document_id': document_id
    },
    metadata={
        'document_id': document_id,
        'file_name': original_filename,
        'chunks': total_chunks_saved,
        'group_name': group_name,
        'group_id': group_id
    }
)
```

### Changes Made:
1. **Import**: Added `from functions_group import find_group_by_id`
2. **Group Lookup**: Fetch group details using `find_group_by_id(group_id)`
3. **Extract Name**: Get group name with fallback to 'Unknown Group'
4. **Enhanced Message**: Include group name: `"Document uploaded to {group_name} has been processed..."`
5. **Updated Link**: Set `link_url='/group_workspaces'` (navigation handled by JavaScript)
6. **Metadata**: Added `group_name` and `group_id` to metadata for JavaScript to use

### 2. Enhanced JavaScript Click Handler
**File**: `notifications.js` (handleNotificationClick function)

```javascript
async function handleNotificationClick(notification) {
    // Mark as read
    if (!notification.is_read) {
        markNotificationRead(notification.id);
    }
    
    // Check if this is a group notification - set active group before navigating
    const groupId = notification.metadata?.group_id;
    if (groupId && notification.link_url === '/group_workspaces') {
        try {
            const response = await fetch('/api/groups/setActive', {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ groupId: groupId })
            });
            
            if (!response.ok) {
                console.error('Failed to set active group:', await response.text());
            }
        } catch (error) {
            console.error('Error setting active group:', error);
        }
    }
    
    // Navigate if link exists
    if (notification.link_url) {
        window.location.href = notification.link_url;
    }
}
```

### Changes Made:
1. **Made function async**: Required for await fetch() calls
2. **Extract group_id**: From notification.metadata.group_id
3. **Conditional API call**: Only for group workspace notifications
4. **Set Active Group**: Call `/api/groups/setActive` with groupId before navigation
5. **Error Handling**: Log errors but continue with navigation
6. **Navigate**: After setting active group, redirect to /group_workspaces

## Testing

### Test Scenario 1: Group Name Display
1. Upload a document to a group workspace
2. Wait for processing to complete
3. Check notification badge appears
4. Click notification badge → navigate to notifications page
5. **Verify**: Notification message includes the actual group name

### Test Scenario 2: Active Group Navigation
1. Upload a document to group "Test Group"
2. Wait for processing to complete
3. Click the notification in the notifications list
4. **Verify**: Browser console shows no errors from setActive API call
5. **Verify**: `/api/groups/setActive` is called with correct groupId (check Network tab)
6. **Verify**: Page navigates to `/group_workspaces`
7. **Verify**: The correct group ("Test Group") is automatically selected and displayed
8. **Verify**: User is not viewing a different group's workspace

## User Experience Improvements

### Before:
- Notification: "Document has been processed successfully with 45 chunks."
- Link: `/group_workspaces` (lands on default/last active group)
- Users had to manually find which group the document was uploaded to

### After:
- Notification: "Document uploaded to **Marketing Team** has been processed successfully with 45 chunks."
- Link: `/group_workspaces` (with automatic group activation via API)
- JavaScript calls `/api/groups/setActive` API before navigation
- Users immediately know which group and are taken directly to it

## Impact Analysis

### Files Modified:
1. **functions_documents.py** (lines 5264-5285)
   - Added group name lookup
   - Enhanced notification message
   - Set link_url to '/group_workspaces' (group activated via API)
   - Added metadata fields including group_id for JavaScript

2. **notifications.js** (handleNotificationClick function)
   - Made function async to support API calls
   - Added group_id detection from notification metadata
   - Calls `/api/groups/setActive` API before navigation for group notifications
   - Error handling for API failures

3. **config.py**
   - Updated VERSION to 0.234.060

### Dependencies:
- Requires `find_group_by_id()` from `functions_group.py`
- Requires `/api/groups/setActive` endpoint in `route_backend_groups.py`
- JavaScript fetch() API for async API calls
- Notification metadata must include group_id field

### Backward Compatibility:
- Existing notifications without group_name metadata will still function
- Notifications without group_id in metadata won't trigger API call (graceful fallback)
- No breaking changes to notification system
- API call failures don't prevent navigation (error is logged only)

## Related Features
- Notification system infrastructure (see `NOTIFICATION_SYSTEM.md`)
- Group workspaces (see `GROUP_WORKSPACES.md`)
- Document processing (see `DOCUMENT_PROCESSING.md`)

## Future Enhancements
Consider similar improvements for:
1. **Public workspace notifications**: Include workspace name
2. **Personal workspace notifications**: Include workspace/collection context
3. **Group activity notifications**: Include group name for all notification types
4. **Notification history**: Add filtering by group name

## Notes
- Group name is fetched synchronously during document processing
- If group is deleted before notification creation, falls back to 'Unknown Group'
- Active group is set via `/api/groups/setActive` API before navigation
- API call is async and doesn't block navigation if it fails
- Notification badge system remains unchanged - this only affects message content and navigation
- Uses existing backend API endpoint for group activation (no new endpoints needed)
