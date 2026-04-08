# Send Feedback Admin Tab (v0.240.010)

## Overview
This feature adds a dedicated **Send Feedback** tab to Admin Settings so administrators can prepare bug reports and feature requests directly from the product.

Documentation Version: 0.240.010
Version Implemented: 0.240.005

## Dependencies
- `application/single_app/templates/admin_settings.html`
- `application/single_app/static/js/admin/admin_settings.js`
- `application/single_app/route_backend_settings.py`
- `application/single_app/functions_activity_logging.py`

## Implemented in version: **0.240.005**

## Updated in version: **0.240.010**

## Safe logging updated in version: **0.240.002**

## Technical Specifications

### Admin Settings Placement
- The **Send Feedback** tab appears as the last top-navigation tab in Admin Settings.
- In sidebar navigation mode, **Send Feedback** appears as the last admin menu item.
- The Latest Features tab includes a dedicated Send Feedback card so admins discover it from the release-summary surface as well.

### Submission Types
- **Report a Bug**
  - For issues where something is not working as expected.
- **Request a Feature**
  - For improvement ideas or new capability requests.

### Mailto Workflow
- Submitting either form calls an admin-only backend endpoint that records the action to the activity log.
- After the activity log entry is written, the browser opens a prefilled `mailto:` draft addressed to `simplechat@microsoft.com`.
- The feedback fields now include explicit `name` and `autocomplete` metadata so browser autofill extensions can classify them without tripping over null field metadata.
- The main Admin Settings form now opts out of common password-manager overlays with `autocomplete="off"`, `data-lpignore="true"`, `data-1p-ignore="true"`, and `data-bwignore="true"` to reduce non-login autofill scans across the page.
- The draft includes:
  - feedback type
  - reporter name
  - reporter email
  - organization
  - current app version
  - submission details
- This is intentionally a text-only email draft workflow to keep the experience simple and avoid implying browser-managed attachments.

### Activity Logging
- Each draft preparation logs an `admin_feedback_email_submission` activity event.
- The activity entry stores:
  - submission type
  - minimal contact metadata instead of full contact fields
  - recipient email
  - details length without storing a free-form preview in telemetry

### Error Handling
- Unexpected backend failures are logged through `log_event` with traceback capture.
- The client receives a generic error response instead of raw exception text.

## Usage Instructions
- Open **Admin Settings**.
- Select **Send Feedback**.
- Choose **Report a Bug** or **Request a Feature**.
- Fill in name, email, organization, and details.
- Submit the form to open the email draft.

## Testing and Validation
- Confirm Send Feedback appears as the last top-nav tab.
- Confirm Send Feedback appears as the last admin sidebar menu item.
- Confirm the Latest Features tab contains a Send Feedback card that links into the Send Feedback tab.
- Confirm bug report and feature request forms both open email drafts.
- Confirm the activity log endpoint is called before the draft opens.
- Confirm the email body contains the entered text fields and details only.
- Confirm the main Admin Settings form keeps the autofill-ignore attributes needed to reduce third-party overlay scanning.