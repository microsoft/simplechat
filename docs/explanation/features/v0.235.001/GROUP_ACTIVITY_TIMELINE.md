# Group Activity Timeline Feature

**Version:** 0.234.026  
**Implemented:** December 20, 2024

## Overview

The Group Activity Timeline provides administrators with a comprehensive, real-time view of all activities happening within a group workspace. This feature displays historical data from activity logs, showing document operations, member changes, status modifications, and conversations in an easy-to-read timeline format.

## Purpose

- **Monitor Group Usage**: Track how groups are being utilized over time
- **Audit Trail**: Maintain visibility into all group operations for compliance and security
- **Member Activity**: See who is adding/removing members and when
- **Document Management**: Track document uploads, deletions, and updates
- **Status Changes**: Monitor when group permissions or status are modified

## Activity Types Tracked

The timeline displays the following activity types from the activity logs:

### 📄 Document Activities
- **Document Creation** (`document_creation`)
  - Shows: File name, type, size, page count
  - Icon: File with plus sign (green)
  
- **Document Deletion** (`document_deletion`)
  - Shows: File name, type
  - Icon: File with minus sign (red)
  
- **Document Metadata Update** (`document_metadata_update`)
  - Shows: File name, "Metadata updated" indicator
  - Icon: Pencil square (blue)

### 👥 Member Activities
- **Member Added** (`group_member_added`)
  - Shows: Member name, email, role, who added them
  - Icon: Person with plus sign (blue)
  
- **Member Removed** (`group_member_deleted`)
  - Shows: Member name, email, who removed them
  - Icon: Person with minus sign (yellow/warning)

### ⚙️ Group Management
- **Status Change** (`group_status_change`)
  - Shows: Previous status → New status (with visual badges)
  - Icon: Shield lock (gray)
  - Tracks: Active, Locked, Upload Disabled, Inactive transitions

### 💬 Conversations
- **Conversation Creation** (`conversation_creation`)
  - Shows: "New chat conversation initiated"
  - Icon: Chat dots (blue)

## User Interface

### Access
1. Navigate to **Control Center** → **Groups** tab
2. Find the desired group in the table
3. Click the **Actions** dropdown (⋮) for the group
4. Select **View Activity**

### Timeline Features

#### Time Range Filters
- **Last 7 days** - Recent activity
- **Last 30 days** - Default view
- **Last 90 days** - Long-term trends
- **All time** - Complete history

#### Activity Cards
Each activity displays:
- **Icon**: Visual indicator of activity type (color-coded)
- **Title**: Activity type in plain language
- **Details**: Relevant information (file names, user names, etc.)
- **Timestamp**: Relative time (e.g., "2h ago") with hover for full date/time

#### Interactive Elements
- **Hover Effect**: Cards highlight on hover for better readability
- **Scrollable**: Timeline scrolls smoothly with custom scrollbar
- **Responsive**: Adapts to different screen sizes and themes

### Export Functionality

Click **Export Activity** to download a CSV file containing:
- Timestamp (ISO format)
- Activity type
- Full description

Export filename format: `group_{groupId}_activity_{date}.csv`

## Technical Implementation

### Backend API

**Endpoint:** `GET /api/admin/control-center/groups/<group_id>/activity`

**Query Parameters:**
- `days` (optional): Time range filter (7, 30, 90, or "all")

**Authentication:** Requires admin and control center admin roles

**Response Format:**
```json
{
  "group_id": "group-uuid",
  "activities": [
    {
      "id": "activity-uuid",
      "type": "document_creation",
      "timestamp": "2024-12-20T10:30:00Z",
      "user_id": "user-uuid",
      "description": "Document uploaded...",
      "icon": "file-earmark-plus",
      "color": "success",
      "document": {
        "file_name": "report.pdf",
        "file_type": "pdf",
        "file_size_bytes": 1024000,
        "page_count": 12
      }
    }
  ],
  "count": 45,
  "time_range_days": "30"
}
```

### Data Source

Activities are queried from the `activity_logs` Cosmos DB container using:
- **Partition key queries** for efficient retrieval
- **Timestamp filtering** for time range selection
- **Activity type filtering** for relevant events
- **Cross-partition queries** when necessary

### Frontend Components

**JavaScript Functions:**
- `GroupManager.loadGroupActivity()` - Fetches and renders timeline
- `GroupManager.renderActivityItem()` - Creates HTML for each activity
- `GroupManager.formatFileSize()` - Human-readable file sizes
- `GroupManager.getRelativeTime()` - Converts timestamps to "2h ago" format
- `GroupManager.exportGroupActivity()` - CSV export functionality

**CSS Styling:**
- `.activity-item` - Card styling with hover effects
- `.activity-icon` - Circular icon containers
- `.timeline-container` - Scrollable container with custom scrollbar
- Dark mode support for all elements

## Use Cases

### Scenario 1: Audit Member Changes
**Goal:** Review who was added/removed from a group in the last 30 days

1. Open the group's activity timeline
2. Keep default "Last 30 days" filter
3. Scroll through member addition/removal activities
4. Export for record-keeping if needed

### Scenario 2: Track Document Uploads
**Goal:** See all documents uploaded to a group this week

1. Open the group's activity timeline
2. Select "Last 7 days" filter
3. Identify all document creation activities (green file icons)
4. Review file names, sizes, and who uploaded them

### Scenario 3: Investigate Status Changes
**Goal:** Determine when and why a group was locked

1. Open the group's activity timeline
2. Select "Last 90 days" or "All time"
3. Find status change activities (shield lock icons)
4. See the transition (e.g., Active → Locked)
5. Note the admin who made the change

### Scenario 4: Generate Activity Report
**Goal:** Create a report of all group activities for compliance

1. Open the group's activity timeline
2. Select appropriate time range
3. Click "Export Activity" button
4. Open CSV in spreadsheet software
5. Filter, sort, and analyze as needed

## Benefits

### For Administrators
- **Quick Insights**: See at a glance what's happening in a group
- **Accountability**: Know who performed what actions and when
- **Troubleshooting**: Identify when issues occurred based on timeline
- **Compliance**: Export data for audit purposes

### For Group Owners
- **Transparency**: Clear visibility into group operations
- **Member Management**: Track membership changes over time
- **Resource Usage**: Monitor document uploads and activity levels

### For Security Teams
- **Audit Trail**: Complete history of group operations
- **Investigation**: Timeline format makes it easy to trace events
- **Compliance**: Exportable records for regulatory requirements

## Performance Considerations

- **Efficient Queries**: Uses partition keys and indexes for fast retrieval
- **Pagination**: Backend supports time-based filtering to limit data volume
- **Client-Side Rendering**: Timeline built dynamically for smooth UX
- **Lazy Loading**: Only fetches data when modal is opened

## Future Enhancements

Potential improvements for future versions:
- Filter by activity type (e.g., only show document activities)
- Search within activity descriptions
- Real-time updates (WebSocket integration)
- Activity analytics and charts
- Compare activity between groups
- Integration with notification system

## Related Features

- **Control Center** - Parent feature for admin management
- **Group Management** - Related to managing group settings
- **Activity Logging** - Source of timeline data
- **Document Management** - Related document operation tracking

## Support

For issues or questions about the Group Activity Timeline:
1. Check the Control Center documentation
2. Review activity logging documentation
3. Contact your system administrator

---

**Note:** Activity data retention is controlled by your Cosmos DB retention policies. Historical data availability depends on your database configuration.
