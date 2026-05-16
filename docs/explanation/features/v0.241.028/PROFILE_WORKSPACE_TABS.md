# Profile Workspace Tabs (v0.241.028)

## Overview and Purpose

Implemented in version: **0.241.028**

The Profile page now hosts the user's group workspace management and public workspace management as dedicated tabs. This keeps account-level workspace tasks in the same profile area as feedback and safety violations while preserving the legacy URLs as redirects.

## Dependencies

- Flask profile route and existing workspace APIs
- Bootstrap 5 tabs, modals, tables, and button groups
- Existing group workspace APIs under `/api/groups`
- Existing public workspace APIs under `/api/public_workspaces`

## Technical Specifications

### Architecture Overview

The `/profile` route accepts two new tab values: `groups` and `public-workspaces`. The route calculates small permission booleans for create buttons and passes those booleans to `profile.html` instead of sending raw settings to the browser.

The profile tab script renders workspace collections with safe DOM APIs. It supports pagination, search, list/card view switching, create forms, discover modals, request access actions, and active workspace selection through the existing backend APIs.

### API Endpoints

- `GET /api/groups`
- `POST /api/groups`
- `PATCH /api/groups/setActive`
- `GET /api/groups/discover`
- `POST /api/groups/<group_id>/requests`
- `GET /api/public_workspaces`
- `POST /api/public_workspaces`
- `PATCH /api/public_workspaces/setActive`
- `GET /api/public_workspaces/discover`
- `POST /api/public_workspaces/<workspace_id>/requests`

### Configuration Options

- `enable_group_workspaces`
- `enable_group_creation`
- `require_member_of_create_group`
- `enable_public_workspaces`
- `require_member_of_create_public_workspace`

### File Structure

- `application/single_app/route_frontend_profile.py`
- `application/single_app/route_frontend_groups.py`
- `application/single_app/route_frontend_public_workspaces.py`
- `application/single_app/templates/profile.html`
- `application/single_app/static/js/profile/profile-tabs.js`
- Navigation templates and workspace page redirects
- `functional_tests/test_profile_workspace_tabs.py`
- `ui_tests/test_profile_workspace_tabs.py`
- `application/single_app/config.py`

## Usage Instructions

Users can open Profile and switch to the Groups or Public Workspaces tab. Existing menu entries for My Groups and My Public Workspaces now deep-link to those tabs. Direct requests to `/my_groups` and `/my_public_workspaces` redirect to the corresponding profile tab.

Each tab includes list and card views. Users can search the collection, change page size, create new workspaces when permitted, find workspaces to join, request access, set the active workspace, and open the management page.

## Testing and Validation

### Test Coverage

- `functional_tests/test_profile_workspace_tabs.py` validates the static routing, template, JavaScript, menu link, documentation, and version contracts.
- `ui_tests/test_profile_workspace_tabs.py` validates that authenticated browser sessions can open the profile workspace tabs and switch between list and card views when the features are enabled.

### Performance Considerations

Workspace rows are loaded lazily only when a profile workspace tab is opened. Existing paginated APIs continue to control response size.

### Known Limitations

The UI test skips when no authenticated Playwright storage state is configured or when both workspace features are disabled in the environment.

## Version Tracking

Fixed/Implemented in version: **0.241.028**

The application version was updated in `application/single_app/config.py` to `0.241.028` for this feature. Related tests and documentation use the same version for traceability.
