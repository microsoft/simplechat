# Control Center Token Filters

Implemented in version: **0.239.164**

## Overview and Purpose

The Control Center dashboard now supports token-specific filtering so admins and control center users can explore token usage by the dimensions already captured in `token_usage` activity logs. This improves token analysis without requiring a separate analytics store.

## Dependencies

- `application/single_app/route_backend_control_center.py`
- `application/single_app/templates/control_center.html`
- `application/single_app/static/js/control-center.js`
- `application/single_app/functions_activity_logging.py`
- Cosmos `activity_logs` container token usage documents

## Technical Specifications

### Architecture Overview

The token chart continues to use `token_usage` entries from the activity log container. The backend now parses optional token filters, applies them only to the token query path, and reuses the same filter payload for chart data, CSV export, and chat-export flows.

### Supported Filters

- User
- Workspace type
- Group
- Public workspace
- Model deployment name
- Token type

### File Structure

- `route_backend_control_center.py`: token filter parsing, query helpers, token filter options endpoint, filtered export support
- `control_center.html`: token filter controls added above the token chart
- `control-center.js`: token filter state, filter option loading, request forwarding, and reset/apply behavior

## Usage Instructions

1. Open the Control Center dashboard.
2. In the Token Usage card, choose one or more token filters.
3. Click Apply to refresh the token chart with the selected scope.
4. Use Reset to return to the unfiltered token view.
5. Export activity trends to keep token CSV output aligned with the selected token filters.

## Testing and Validation

- Functional regression: `functional_tests/test_control_center_token_filters.py`
- UI regression: `ui_tests/test_control_center_token_filters.py`

## Known Limitations

- Endpoint-level token filtering is not included in this version because endpoint metadata is not yet persisted in `token_usage` activity log records.
- Token filters apply to the token chart and token export data only; the other dashboard charts remain global for the selected time range.