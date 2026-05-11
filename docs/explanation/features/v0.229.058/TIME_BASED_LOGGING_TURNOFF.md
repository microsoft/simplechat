# Time-Based Logging Turnoff Feature

**Version:** 0.229.058

## Overview

The Time-Based Logging Turnoff feature provides administrators with the ability to enable debug logging and file process logging with automatic turnoff capabilities. This feature helps manage cost and risk by preventing accidental long-term logging that could impact application performance and storage costs.

## Purpose

- **Cost Management**: Prevents excessive logging costs by automatically disabling logging after specified time periods
- **Risk Mitigation**: Reduces security risks by ensuring debug logging (which may capture sensitive data) doesn't remain enabled indefinitely
- **Operational Safety**: Provides automatic cleanup of verbose logging without requiring manual intervention
- **User-Friendly**: Clear visibility of when logging will automatically turn off

## Technical Specifications

### Architecture Overview

The feature consists of four main components:

1. **Frontend UI Controls** - Admin settings interface with timer configuration
2. **Backend Logic** - Form handling and turnoff time calculation
3. **Background Monitoring** - Daemon thread that monitors and enforces timer expiration
4. **Settings Storage** - Database fields for timer configuration and turnoff timestamps

### Database Schema

New settings fields added to the application settings:

```json
{
  "debug_logging_timer_enabled": false,
  "debug_timer_value": 1,
  "debug_timer_unit": "hours",
  "debug_logging_turnoff_time": null,
  "file_processing_logs_timer_enabled": false,
  "file_timer_value": 1,
  "file_timer_unit": "hours",
  "file_processing_logs_turnoff_time": null
}
```

### File Structure

- **Frontend**: `templates/admin_settings.html` - UI controls and JavaScript
- **Backend**: `route_frontend_admin_settings.py` - Form handling and validation
- **Settings**: `functions_settings.py` - Default settings configuration
- **Background Task**: `app.py` - Timer monitoring daemon
- **Tests**: `functional_tests/test_time_based_logging_turnoff.py` - Validation tests

## Configuration Options

### Time Scopes

The feature supports the following time ranges for both debug logging and file processing logs:

| Unit | Range | Use Case |
|------|-------|----------|
| **Minutes** | 1-120 | Short-term debugging sessions |
| **Hours** | 1-24 | Standard debugging workflows |
| **Days** | 1-7 | Extended troubleshooting periods |
| **Weeks** | 1-52 | Long-term monitoring scenarios |

### Logging Types

#### Debug Logging
- **Scope**: All DEBUG print statements throughout the application
- **Data Captured**: Tokens, keys, and detailed execution information
- **Risk Level**: High (contains sensitive data)
- **Recommended Duration**: Minutes to hours for active debugging

#### File Processing Logs
- **Scope**: File processing events for debugging and auditing
- **Storage**: Cosmos DB file_processing container
- **Risk Level**: Medium (operational data)
- **Recommended Duration**: Hours to days for operational monitoring

## Usage Instructions

### Enabling Time-based Turnoff

1. **Navigate to Admin Settings**
   - Access `/admin/settings` with administrator privileges
   - Go to the "Logging" tab

2. **Configure Debug Logging Timer**
   - Enable "Debug Logging" if needed
   - Toggle "Enable Time-based Auto Turnoff"
   - Set duration value (1-120 for minutes, 1-24 for hours, etc.)
   - Select time unit from dropdown
   - View calculated turnoff time

3. **Configure File Processing Logs Timer**
   - Enable "File Processing Logs" if needed
   - Toggle "Enable Time-based Auto Turnoff"
   - Set duration and time unit
   - View calculated turnoff time

4. **Save Configuration**
   - Click "Save Settings" to activate timers
   - Logging will automatically disable at the specified time

### User Interface Features

#### Dynamic Controls
- Timer controls only appear when main logging toggle is enabled
- Timer inputs only appear when timer toggle is enabled
- Real-time validation of timer values within allowed ranges
- Display of calculated turnoff timestamp

#### Visual Feedback
- Clear indication of when logging will turn off
- Validation messages for out-of-range values
- Responsive UI that adapts to selections

## Implementation Details

### Frontend JavaScript Functions

```javascript
// Toggle visibility of time controls
function toggleTimeControls(type)

// Toggle visibility of timer input fields
function toggleTimerInputs(type)

// Validate timer values within limits
function updateTimerLimits(type)
```

### Backend Validation

```python
# Timer value limits by unit
timer_limits = {
    'minutes': (1, 120),
    'hours': (1, 24),
    'days': (1, 7),
    'weeks': (1, 52)
}
```

### Background Monitoring

The application runs a daemon thread that:
- Checks timer status every 60 seconds
- Compares current time with turnoff timestamps
- Automatically disables logging when timers expire
- Updates settings in the database
- Logs timer expiration events

### DateTime Handling

- Turnoff times calculated using Python `datetime` and `timedelta`
- Stored as ISO format strings for JSON serialization compatibility
- Parsed back to datetime objects for comparison operations

## Testing and Validation

### Functional Tests

The feature includes comprehensive tests covering:

1. **Timer Value Validation** - Ensures values stay within specified ranges
2. **DateTime Serialization** - Verifies JSON compatibility
3. **Turnoff Calculation** - Validates time calculation logic
4. **Background Timer Logic** - Tests expiration detection
5. **Settings Defaults** - Confirms proper default values

### Test Execution

```bash
cd functional_tests
python test_time_based_logging_turnoff.py
```

## Performance Considerations

### Background Task Impact
- Minimal CPU usage (60-second check intervals)
- No database queries when no timers are active
- Daemon thread doesn't block main application

### Storage Impact
- Negligible storage overhead for timer settings
- Automatic cleanup prevents log accumulation
- No additional database containers required

## Security Considerations

### Risk Mitigation
- Automatic turnoff prevents indefinite sensitive data logging
- Timer limits prevent excessively long logging periods
- No user input stored directly in timestamps (calculated server-side)

### Access Control
- Configuration requires administrator privileges
- Timer status visible in admin interface only
- Background task operates with application credentials

## Troubleshooting

### Common Issues

#### Timer Not Working
- Verify background task started (check logs for "Logging timer background task started")
- Confirm timer is enabled in settings
- Check that turnoff time is in the future

#### Settings Not Saving
- Ensure datetime objects are properly serialized to strings
- Verify form validation passes
- Check database connectivity

#### UI Controls Not Appearing
- Verify JavaScript functions are loaded
- Check browser console for errors
- Ensure main logging toggles are enabled first

### Debug Information

Monitor application logs for:
- Timer expiration messages
- Background task startup confirmation
- Settings update confirmations
- Any timer check errors

## Version History

### v0.229.043 (September 17, 2025)
- **Initial Implementation**: Complete time-based turnoff functionality
- **Features Added**:
  - UI controls for timer configuration
  - Background monitoring daemon
  - Automatic logging disable
  - Comprehensive validation
  - Functional test suite

## Dependencies

### Frontend
- Bootstrap 5.x for UI components
- JavaScript ES6 for dynamic interactions

### Backend
- Flask framework
- Python datetime module
- Threading module for background tasks

### Database
- Cosmos DB for settings storage
- JSON serialization compatibility

## Future Enhancements

### Potential Improvements
- Email notifications before timer expiration
- Audit log of timer activations and expirations
- Different timer scopes for different log levels
- Integration with monitoring systems
- Bulk timer management for multiple logging types

### Extensibility
The timer framework can be extended to support:
- Additional logging types
- Custom time ranges
- Conditional timers based on log volume
- Integration with external scheduling systems

## Related Documentation

- [Admin Configuration Guide](../admin_configuration.md)
- [Application Workflows](../application_workflows.md)
- [Fix Documentation](../fixes/)
- [Functional Tests](../../functional_tests/)

## Support

For issues or questions regarding the Time-Based Logging Turnoff feature:
1. Check the troubleshooting section above
2. Review functional test results
3. Examine application logs for timer-related messages
4. Verify administrator permissions and settings access