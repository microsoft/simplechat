# Latest Features Action Links (v0.241.003)

## Overview
This update turns the earlier Previous Release feature cards into direct in-app entry points. Users can now jump from Support > Latest Features into the matching Chat, Workspace, and Profile workflows instead of stopping at a descriptive card.

Version Updated: 0.241.003

## Dependencies
- `application/single_app/support_menu_config.py`
- `application/single_app/functions_settings.py`
- `application/single_app/route_frontend_admin_settings.py`
- `application/single_app/templates/admin_settings.html`
- `application/single_app/static/js/chat/chat-onload.js`
- `application/single_app/static/js/chat/chat-documents.js`
- `application/single_app/static/js/workspace/workspace-init.js`
- `application/single_app/static/js/workspace/workspace-tags.js`
- `application/single_app/templates/profile.html`
- `functional_tests/test_latest_features_action_links.py`
- `ui_tests/test_latest_features_action_launchers.py`

## Implemented in version: **0.241.003**

## Technical Specifications

### Action Metadata
- Previous-release Latest Features cards now include direct in-app buttons for:
  - conversation export
  - retention settings
  - workspace tag management
  - workspace grid view
  - chat scope management
  - chat tag filtering
- Public documentation guide buttons remain available through the same feature metadata, but they are now conditional.

### Admin-Controlled Guide Links
- A new General settings toggle named **Show Simple Chat Documentation Guide Links** controls whether public documentation buttons are shown on Latest Features cards.
- The setting defaults to `False` so users see only the in-app shortcuts unless an admin explicitly enables the external guide links.
- Admin preview cards use the same filtered action list, so the admin tab reflects what end users will actually see.

### Launch Intents
- Chat launch intents use the `feature_action` query parameter to:
  - open the first available conversation export workflow
  - open the multi-workspace scope selector
  - open the chat tag-filter controls
- Workspace launch intents use the same parameter to:
  - open the tag-management modal
  - switch directly into grid view
- Profile launch intents jump to the retention settings section and focus the retention control.

## Usage Instructions
- Open **Support > Latest Features** and expand **Previous Release Features**.
- Choose an in-app action button when you want to land directly in the related workflow.
- Open **Admin Settings > General > User-Facing Latest Features** when you want to enable or disable the public documentation guide buttons.

## Testing and Validation
- Confirm the new admin toggle is saved and restored correctly.
- Confirm previous-release cards still show their in-app action buttons when guide links are disabled.
- Confirm guide buttons appear only when the new admin toggle is enabled.
- Confirm workspace launch links open grid view or tag management directly.
- Confirm the profile launch link scrolls to retention settings.
- Confirm the chat launch links open grounded-search scope controls or the export workflow as expected.