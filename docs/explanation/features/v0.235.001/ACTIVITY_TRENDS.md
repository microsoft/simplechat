# ACTIVITY_TRENDS.md

**Feature**: Activity Trends in Control Center  
**Version**: 0.230.003  
**Implemented in**: 0.230.003

## Overview and Purpose

The Activity Trends feature provides administrators with visual analytics and insights into system usage patterns within the Simple Chat Control Center. This feature replaces the previous placeholder text with an interactive chart that displays daily activity metrics across different categories.

## Key Features

- **Interactive Line Chart**: Real-time visualization of daily activity data
- **Multiple Activity Categories**: Tracks chats, uploads, logins, and document actions
- **Flexible Time Periods**: 7-day, 30-day, and 90-day trend views
- **Real Data Integration**: Uses actual application data from existing containers
- **Sample Data Fallback**: Automatic fallback to realistic sample data when no real activity exists
- **Responsive Design**: Chart adapts to different screen sizes
- **Error Handling**: Graceful error handling with retry functionality

## Technical Specifications

### Architecture Overview

The Activity Trends feature consists of three main components:

1. **Backend API Endpoint** (`/api/admin/control-center/activity-trends`)
2. **Frontend Chart Integration** (Chart.js implementation)
3. **Real Data Integration** (Multiple Cosmos DB containers as data sources)

### API Endpoint

**Endpoint**: `GET /api/admin/control-center/activity-trends`

**Parameters**:
- `days` (optional): Number of days to retrieve (default: 30, max: 90)

**Response Structure**:
```json
{
  "activity_trends": [
    {
      "date": "2025-10-01",
      "chats": 45,
      "uploads": 12,
      "logins": 23,
      "document_actions": 8,
      "total": 88
    }
  ],
  "date_range": {
    "start_date": "2025-09-02T00:00:00Z",
    "end_date": "2025-10-02T00:00:00Z",
    "days": 30
  }
}
```

**Authentication**: Requires admin authentication (`@admin_required`)

### Data Sources

The activity trends use real data from existing application containers:

**Chat Activity**:
- `conversations` container - tracks conversation creation
- `messages` container - tracks individual message activity

**Upload Activity**:
- `user_documents` container - user document uploads
- `group_documents` container - group document uploads  
- `public_documents` container - public document uploads

**Document Actions**:
- `feedback` container - feedback submissions
- `safety` container - safety violation reports

**Login Activity** (estimated):
- `user_settings` container - user settings updates as proxy for activity

### File Structure

**Backend Files**:
- `route_backend_control_center.py` - API endpoint implementation
- `config.py` - Activity logs container configuration

**Frontend Files**:
- `templates/control_center.html` - Chart container and UI elements
- `static/js/control-center.js` - Chart rendering and interaction logic
- `static/js/chart.min.js` - Local Chart.js library (v4.4.0 UMD build)

**Test Files**:
- `functional_tests/test_activity_trends_implementation.py` - Comprehensive testing

## Usage Instructions

### How to Enable/Configure

The Activity Trends feature is automatically enabled when:

1. Admin user accesses the Control Center
2. The `activity_logs` container exists in Cosmos DB
3. Chart.js library is loaded (via CDN)

### User Workflows

1. **Viewing Trends**:
   - Navigate to Admin → Control Center
   - Activity Trends chart displays automatically on the Dashboard tab
   - Default view shows 30 days of data

2. **Changing Time Period**:
   - Click "7 Days", "30 Days", or "90 Days" buttons
   - Chart updates automatically with new data

3. **Interpreting Data**:
   - **Blue Line (Chats)**: Daily chat/message activity
   - **Green Line (Uploads)**: Daily file upload activity  
   - **Yellow Line (Logins)**: Daily user login activity
   - **Red Line (Documents)**: Daily document-related actions
   - Hover over data points for detailed information

### Integration Points

- **Control Center Dashboard**: Primary display location
- **Real Application Data**: Uses existing timestamped data from multiple containers
- **Sample Data Generation**: Fallback when no real activity exists in containers

## Testing and Validation

### Test Coverage

The implementation includes comprehensive functional tests:

1. **API Endpoint Testing**: Validates response structure and authentication
2. **Route Definition Testing**: Ensures backend routes are properly configured
3. **Frontend Integration Testing**: Verifies HTML template changes
4. **JavaScript Functionality Testing**: Confirms chart rendering capabilities
5. **Configuration Testing**: Validates Cosmos DB container setup

### Performance Considerations

- **Data Aggregation**: Daily aggregation reduces query complexity
- **Date Range Limits**: Maximum 90-day queries prevent performance issues
- **Client-side Caching**: Chart data cached until period change
- **Lazy Loading**: Chart loads after initial page render

### Known Limitations

1. **Historical Data**: Only displays data from when containers started being populated
2. **Real-time Updates**: Requires manual refresh for latest data
3. **Sample Data**: Falls back to generated data when no real activity exists
4. **Time Zone**: All dates displayed in user's local time zone

## Sample Data Generation

When no real activity data exists in containers, the system generates realistic sample data:

```javascript
// Sample daily activity ranges
chats: 20-80 per day
uploads: 5-30 per day  
logins: 10-50 per day
document_actions: 5-40 per day
```

This ensures the feature is functional even in new installations.

## Error Handling

The feature includes robust error handling:

- **API Failures**: Displays error message with retry button
- **Network Issues**: Graceful degradation to error state
- **Authentication Errors**: Proper HTTP status code handling
- **Data Parsing Errors**: Fallback to sample data generation

## Future Enhancements

Planned improvements for future versions:

- **Enhanced Data Mapping**: Better correlation between container data and activity types
- **Advanced Filters**: Filter by user, group, or activity type
- **Export Functionality**: Download trend data as CSV/PDF
- **Comparative Analytics**: Week-over-week and month-over-month comparisons
- **Alerting**: Notifications for unusual activity patterns

## Technical Dependencies

- **Chart.js**: ^4.4.0 UMD build (local file: `static/js/chart.min.js`)
- **Bootstrap**: ^5.0+ (for responsive UI elements)
- **Cosmos DB**: Multiple containers (conversations, messages, documents, feedback, safety, user_settings)
- **Flask**: Backend API framework
- **Authentication**: Admin role requirement

## Compatibility

- **Browser Support**: Modern browsers supporting ES6+
- **Mobile Responsive**: Optimized for tablet and mobile viewing
- **Accessibility**: Keyboard navigation and screen reader support

---

**Implementation Notes**: This feature replaces the previous placeholder implementation and provides a foundation for comprehensive activity analytics in future versions.