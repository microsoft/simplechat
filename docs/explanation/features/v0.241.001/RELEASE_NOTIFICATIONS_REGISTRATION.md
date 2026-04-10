# Release Notifications Registration (v0.240.011)

Documentation Version: 0.240.011
Version Implemented: 0.240.011
Fixed/Implemented in version: **0.240.011**
Safe logging updated in version: **0.240.002**

## Overview

This feature adds a registration workflow to Admin Settings so administrators can register their deployment for:

- Latest SimpleChat release notifications
- SimpleChat community call notifications

The workflow is intentionally aligned with the existing Send Feedback mailto behavior. Admin Settings persists the registration state locally, then opens a prefilled email draft addressed to simplechat@microsoft.com.

## Dependencies

- Admin Settings page in application/single_app/templates/admin_settings.html
- Admin settings JavaScript in application/single_app/static/js/admin/admin_settings.js
- Settings persistence in application/single_app/functions_settings.py
- Admin settings backend route in application/single_app/route_backend_settings.py
- Activity logging in application/single_app/functions_activity_logging.py
- Current config.py version: 0.240.011

## Technical Specifications

### Persisted Settings

The registration state is stored in Admin Settings using these keys:

- release_notifications_registered
- release_notifications_name
- release_notifications_email
- release_notifications_org
- release_notifications_registered_at
- release_notifications_updated_at

### UI Behavior

- A registered or unregistered badge appears at the top of Admin Settings, to the left of the version display.
- Selecting the badge opens a modal.
- If the deployment is unregistered, the modal opens directly in edit mode.
- If the deployment is registered, the modal opens in read mode and shows the stored registration details with timestamps.
- Registered deployments can switch into edit mode and submit updated details.

### Email Workflow

- Submissions post to /api/admin/settings/release_notifications_registration.
- The backend persists the registration details in settings before returning mailto metadata.
- The frontend opens a prefilled email draft addressed to simplechat@microsoft.com.
- The subject line identifies the request as a SimpleChat registration for release and community call notifications.

### Activity Logging

Each registration submission intent is written to the activity log using activity_type admin_release_notifications_registration.
The stored activity metadata is limited to registration state, timestamps, recipient email, and reduced contact metadata instead of full contact fields in telemetry.

### Error Handling

- Unexpected backend failures are logged through `log_event` with traceback capture.
- The client receives a generic error response instead of raw exception text.

## Usage Instructions

1. Open Admin Settings.
2. Select the Registered or Unregistered badge near the version number.
3. Enter or review the deployment contact details:
   - Your Name
   - Email
   - Organization
4. Submit the registration.
5. Confirm that your local mail client opens a prefilled draft to simplechat@microsoft.com.

## File Structure

- application/single_app/templates/admin_settings.html
- application/single_app/static/js/admin/admin_settings.js
- application/single_app/route_backend_settings.py
- application/single_app/route_frontend_admin_settings.py
- application/single_app/functions_settings.py
- application/single_app/functions_activity_logging.py
- functional_tests/test_admin_release_notifications_registration.py

## Testing And Validation

- Functional coverage exists in functional_tests/test_admin_release_notifications_registration.py.
- The test validates template markers, JavaScript hooks, backend endpoint markers, activity logging markers, and documentation presence.
- The hidden admin form fields are synchronized after asynchronous registration so later full Admin Settings saves do not overwrite the stored registration state.

## Known Limitations

- The workflow uses a mailto draft, so actual delivery depends on a local mail client being configured.
- Attachments are not included automatically; this workflow is intended for contact registration metadata only.