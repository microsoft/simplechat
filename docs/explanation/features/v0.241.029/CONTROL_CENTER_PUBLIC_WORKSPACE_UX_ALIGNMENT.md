# Control Center Public Workspace UX Alignment (v0.241.029)

Implemented in version: **0.241.029**

## Overview

The Control Center Public Workspace Management view now uses the same card-wrapped management table pattern as Group Management while intentionally omitting any public workspace creation disable control.

## Purpose

This enhancement makes public workspace administration feel consistent with group administration by aligning the table surface, sortable column affordances, loading copy, and pagination placement.

## Dependencies

- `application/single_app/config.py` version `0.241.029`
- `application/single_app/templates/control_center.html`
- `application/single_app/static/js/control-center.js`

## Technical Specifications

### Architecture Overview

Public workspace management remains backed by `/api/admin/control-center/public-workspaces`. The template now wraps the public workspace table and pagination in the same Bootstrap card structure used by group management.

### UI Behavior

- Public workspace search, status filtering, export, bulk action, refresh, and page-size controls remain unchanged.
- The table uses the shared `group-table` styling pattern for visual consistency with Group Management.
- Workspace name, owner, members, status, and documents columns expose sortable headers.
- No global disable switch or disable-creation button was added for public workspaces.

### File Structure

- Template: `application/single_app/templates/control_center.html`
- Client behavior: `application/single_app/static/js/control-center.js`
- Functional test: `functional_tests/test_control_center_management_pagination.py`
- UI test: `ui_tests/test_control_center_management_pagination.py`

## Usage Instructions

Administrators can open Control Center, switch to Public Workspace Management, and use the table like Group Management: search, filter, change page size, sort columns, select rows, export, refresh, and manage individual workspaces.

## Testing and Validation

- Source-level functional regression validates matching page-size options, server-side pagination parameters, sortable public workspace headers, and absence of a disable-creation control.
- Playwright UI regression validates the public workspace table card/sortable structure when UI environment variables are provided.
- JavaScript syntax validation is covered with `node --check` for `control-center.js`.

## Known Limitations

The shared sorter is client-side and sorts only the currently loaded page of public workspaces. Server-side paging remains the source of truth for larger result sets.

## Config Version Reference

The application version was updated in `application/single_app/config.py` to `0.241.029` for this enhancement.
