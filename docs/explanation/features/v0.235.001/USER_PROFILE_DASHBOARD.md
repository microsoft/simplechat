# User Profile Dashboard

## Overview
Complete redesign of the user profile page into a modern, dashboard-style interface with personalized analytics and visualizations. The new profile provides users with comprehensive insights into their SimpleChat activity, storage usage, and engagement metrics.

**Version Implemented:** 0.234.068

## Purpose
Transform the basic profile page into an engaging, data-rich dashboard that gives users visibility into their SimpleChat usage patterns, similar to the admin Control Center but personalized for individual users.

## Dependencies
- **Frontend:** Bootstrap 5, Chart.js 4.4.1
- **Backend:** Flask, Azure Cosmos DB
- **Data Sources:** 
  - `user_settings` container (cached metrics)
  - `activity_logs` container (login, token usage)
  - `conversations` container (chat activity)
  - `documents` container (file uploads)
  - `messages` container (message counts)

## Technical Specifications

### Architecture Overview
The profile dashboard follows a client-server architecture with:
1. **Frontend UI**: Modern card-based layout with responsive design
2. **API Endpoints**: RESTful endpoints for metrics and activity trends
3. **Data Aggregation**: Real-time queries with 30-day time-series data
4. **Caching**: Metrics cached in user_settings for performance

### File Structure

#### Modified Files
- [route_frontend_profile.py](../../application/single_app/route_frontend_profile.py)
  - Added `/api/user/activity-trends` endpoint (time-series data)
  - Added `/api/user/settings` endpoint (user metrics)
- [profile.html](../../application/single_app/templates/profile.html)
  - Complete redesign with modern dashboard layout
  - Chart.js integration for visualizations

#### Key Components

**Backend Endpoints:**
```python
# Get user metrics and settings
GET /api/user/settings
Response: {
  "success": true,
  "metrics": {
    "login_metrics": {"total_logins": 45, "last_login": "2025-01-15T10:30:00Z"},
    "chat_metrics": {"total_conversations": 23, "total_messages": 156},
    "document_metrics": {"total_documents": 12, "ai_search_size": 168591360}
  },
  "retention_policy": {"enabled": false, "days": 30}
}

# Get 30-day activity trends
GET /api/user/activity-trends
Response: {
  "success": true,
  "logins": [{"date": "2025-01-01", "count": 3}, ...],
  "conversations": [{"date": "2025-01-01", "count": 2}, ...],
  "documents": [{"date": "2025-01-01", "count": 1}, ...],
  "tokens": [{"date": "2025-01-01", "tokens": 15000}, ...],
  "storage": {"ai_search_size": 168591360, "storage_account_size": 178052840}
}
```

**Frontend UI Structure:**
1. **Hero Section** - Large profile image (200px), gradient background, name/email
2. **Quick Stats Cards** - 4 key metrics with icons and trend indicators
3. **Activity Charts** - 5 visualizations (login, conversation, document, token, storage)
4. **Account Information** - User details and last login
5. **Retention Settings** - Workspace retention policy configuration

### API Endpoints

#### `/api/user/settings` (GET)
**Authentication:** `@login_required`, `@user_required`

**Purpose:** Fetch user settings including cached metrics

**Response Format:**
```json
{
  "success": true,
  "metrics": {
    "calculated_at": "2025-01-15T12:00:00Z",
    "login_metrics": {
      "total_logins": 45,
      "last_login": "2025-01-15T10:30:00Z"
    },
    "chat_metrics": {
      "total_conversations": 23,
      "total_messages": 156,
      "total_message_size": 524288
    },
    "document_metrics": {
      "total_documents": 12,
      "ai_search_size": 168591360,
      "storage_account_size": 178052840
    }
  },
  "retention_policy": {
    "enabled": false,
    "days": 30
  },
  "profile_image": "data:image/jpeg;base64,...",
  "display_name": "John Doe",
  "email": "john.doe@example.com"
}
```

#### `/api/user/activity-trends` (GET)
**Authentication:** `@login_required`, `@user_required`

**Purpose:** Fetch 30-day time-series activity data for charts

**Query Logic:**
- **Date Range:** Last 30 days from current date
- **Data Sources:**
  - Logins: `activity_logs` container (activity_type='user_login')
  - Conversations: `conversations` container (created_at timestamps)
  - Documents: `documents` container (uploaded_at timestamps)
  - Tokens: `activity_logs` container (activity_type='token_usage')
  - Storage: Cached in `user_settings.metrics.document_metrics`

**Response Format:**
```json
{
  "success": true,
  "logins": [
    {"date": "2025-01-01", "count": 3},
    {"date": "2025-01-02", "count": 2},
    ...
  ],
  "conversations": [
    {"date": "2025-01-01", "count": 2},
    ...
  ],
  "documents": [
    {"date": "2025-01-01", "count": 1},
    ...
  ],
  "tokens": [
    {"date": "2025-01-01", "tokens": 15000},
    ...
  ],
  "storage": {
    "ai_search_size": 168591360,
    "storage_account_size": 178052840
  }
}
```

### Configuration Options

**Chart Configuration:**
- **Theme Detection:** Automatically detects dark mode and adjusts colors
- **Responsive:** Charts resize based on container width
- **Tooltips:** Formatted with custom callbacks (K/M suffixes, bytes)
- **Animation:** Smooth transitions on data updates

**Color Scheme:**
- **Primary Gradient:** `linear-gradient(135deg, #667eea 0%, #764ba2 100%)`
- **Card Hover:** Scale transform with subtle shadow
- **Chart Colors:**
  - Login: `rgba(102, 126, 234, 0.8)` (purple)
  - Conversation: `rgba(52, 211, 153, 0.8)` (green)
  - Document: `rgba(251, 146, 60, 0.8)` (orange)
  - Token: `rgba(239, 68, 68, 0.8)` (red)
  - Storage: Doughnut with two segments

## Usage Instructions

### User Workflow

1. **Access Profile**
   - Navigate to `/profile` route
   - View hero section with profile image and name

2. **Review Quick Stats**
   - See 4 key metrics in card format:
     - Total Conversations
     - Total Messages
     - Total Documents
     - Login Count

3. **Analyze Activity Trends**
   - **Login Activity:** Line chart showing daily login frequency
   - **Conversation Trends:** Bar chart of new conversations created
   - **Document Uploads:** Bar chart of files uploaded
   - **Token Usage:** Line chart of API token consumption
   - **Storage Usage:** Doughnut chart of AI Search vs Storage Account size

4. **Manage Account Settings**
   - View account information (email, last login, join date)
   - Configure retention policy per workspace type
   - Refresh profile image from Microsoft Graph

### Integration Points

**Data Flow:**
1. User navigates to profile page → `profile()` route renders template
2. Frontend loads metrics → Calls `/api/user/settings`
3. Frontend loads charts → Calls `/api/user/activity-trends`
4. Backend queries Cosmos DB → Aggregates data by date
5. Frontend receives JSON → Updates Chart.js visualizations

**Retention Policy Integration:**
- Settings displayed in card format
- Checkboxes for Personal/Group/Public workspace retention
- Execution hour dropdown (0-23)
- Next scheduled execution timestamp
- Updates save to `settings` container

## Testing and Validation

### Test Coverage
- **Unit Tests:** Endpoint authentication and authorization
- **Integration Tests:** Data aggregation from multiple containers
- **UI Tests:** Chart rendering and responsiveness

### Performance Considerations
- **Metrics Caching:** User metrics cached in `user_settings` (refreshed daily)
- **Query Optimization:** Date-filtered queries with partition key where possible
- **Time Range:** Limited to 30 days to prevent excessive data loading
- **Lazy Loading:** Charts load data asynchronously after page render

### Known Limitations
1. **30-Day Window:** Activity trends limited to last 30 days
2. **Cached Metrics:** Quick stats show cached data (may be up to 24 hours old)
3. **Token Estimation:** Token usage estimated from message length, not actual API calls
4. **Cross-Partition Queries:** Some queries require cross-partition scans (higher RU cost)

## User Experience Improvements

### Before
- Small profile image (50px)
- Basic table layout with key-value pairs
- No visual representation of activity
- Retention settings in plain list format
- Limited user engagement

### After
- Large profile image (200px) in gradient hero section
- Modern card-based dashboard layout
- 5 interactive charts with activity visualizations
- Color-coded stat cards with icons and trends
- Professional, data-rich interface similar to Control Center

### Visual Design
- **Hero Section:** Purple gradient background with large profile image
- **Stat Cards:** White cards with hover effects and colored icons
- **Charts:** Consistent styling with theme detection (light/dark mode)
- **Responsive Design:** Mobile-friendly layout with stacked cards
- **Animations:** Smooth transitions and hover effects

## Maintenance

### When to Update
- **New Activity Types:** Add tracking for new user actions
- **Chart Additions:** Extend with additional visualizations
- **Metric Changes:** Update if metrics schema changes in `user_settings`
- **UI Enhancements:** Refine layout or add new sections

### Related Files
- [route_backend_control_center.py](../../application/single_app/route_backend_control_center.py) - Metrics calculation and caching logic
- [functions_settings.py](../../application/single_app/functions_settings.py) - User settings management
- [functions_activity_logging.py](../../application/single_app/functions_activity_logging.py) - Activity logging utilities

## Future Enhancements
1. **Customizable Time Ranges:** Allow users to select date ranges (7/30/90 days)
2. **Export Functionality:** Download activity data as CSV/PDF reports
3. **Goal Setting:** Set personal targets for document uploads or conversation creation
4. **Comparison View:** Compare current period vs previous period
5. **Activity Heatmap:** Calendar view showing activity intensity by day
6. **Plugin Usage Stats:** Track which plugins/actions are used most frequently
7. **Collaboration Metrics:** Show group and public workspace participation
