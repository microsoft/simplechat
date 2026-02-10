# Admin Activity Logging (v0.236.017)

## Overview and Purpose
This feature adds a general-purpose activity log entry for admin actions so operational changes show up in the activity timeline.

## Version Implemented
Fixed/Implemented in version: **0.236.017**

## Dependencies
- Activity logs Cosmos container
- Application Insights for telemetry

## Technical Specifications
### Architecture Overview
- A helper function constructs a standardized activity record and writes it to the activity logs container.
- Records include admin identity fields and a description for display in the UI timeline.

### Configuration Options
- None

### File Structure
- Logging helper: application/single_app/functions_activity_logging.py
- Functional test: functional_tests/test_admin_action_activity_log.py

## Usage Instructions
### How to Log
Call `log_general_admin_action()` with the admin user ID, admin email, and action string.
Optionally pass a human-readable description and additional context.

### Example
- Action: "settings_updated"
- Description: "Admin updated AI model settings"

## Testing and Validation
- Functional test: functional_tests/test_admin_action_activity_log.py

## Known Limitations
- Caller is responsible for invoking the helper when admin actions occur.

## Reference to Config Version Update
- Version updated in application/single_app/config.py to **0.236.017**.
