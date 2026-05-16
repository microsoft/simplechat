# Control Center Management ID Search (v0.241.030)

Implemented in version: **0.241.030**

## Overview

Control Center management searches now include IDs for users, groups, and public workspaces. The search placeholders were updated so administrators know they can search by ID as well as the existing readable labels.

## Purpose

Administrators often need to locate a specific record from logs, URLs, exports, or support requests where only an object ID is available. This enhancement makes the management tabs usable for that workflow without requiring manual database lookup.

## Dependencies

- `application/single_app/config.py` version `0.241.030`
- `application/single_app/route_backend_control_center.py`
- `application/single_app/templates/control_center.html`

## Technical Specifications

### Search Coverage

- User Management searches `id`, `email`, and `display_name`.
- Group Management searches `id`, `name`, `description`, and owner fields.
- Public Workspace Management searches `id`, `name`, `description`, and owner fields.

### API Endpoints

- `/api/admin/control-center/users`
- `/api/admin/control-center/groups`
- `/api/admin/control-center/public-workspaces`

## Usage Instructions

Open Control Center and use the existing search box on User Management, Group Management, or Public Workspace Management. Enter a full or partial ID to filter the table results.

## Testing and Validation

- Functional regression: `functional_tests/test_control_center_management_pagination.py`
- UI regression: `ui_tests/test_control_center_management_pagination.py`
- Validation includes ID-aware placeholders and backend search clauses.

## Known Limitations

Search remains a substring match against the fields included by each management API. It does not perform fuzzy matching or cross-tab lookup.

## Config Version Reference

The application version was updated in `application/single_app/config.py` to `0.241.030` for this enhancement.
