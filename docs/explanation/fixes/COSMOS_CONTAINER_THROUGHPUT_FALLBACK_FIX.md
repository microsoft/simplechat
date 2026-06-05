# Cosmos Container Throughput Fallback Fix

Fixed/Implemented in version: **0.241.148**

## Issue Description

The Admin Settings Scale tab could show `Failed to load Cosmos throughput status` when the configured `SimpleChat` database did not have a database-level `throughputSettings/default` resource. Azure returned a 404 for the database throughput request even though the Cosmos account and containers existed.

## Root Cause Analysis

The first Cosmos throughput implementation assumed the app would always manage database-level shared autoscale throughput. Some environments use dedicated container throughput or a mixed layout, so the database throughput ARM resource can be absent while container throughput resources are valid.

## Technical Details

Files modified:

- `application/single_app/functions_cosmos_throughput.py`
- `application/single_app/route_backend_settings.py`
- `application/single_app/route_frontend_admin_settings.py`
- `application/single_app/templates/admin_settings.html`
- `application/single_app/static/js/admin/admin_settings.js`
- `application/single_app/config.py`
- `functional_tests/test_cosmos_throughput_autoscale_logic.py`
- `ui_tests/test_admin_cosmos_throughput_settings_ui.py`
- `docs/explanation/features/v0.241.147/COSMOS_THROUGHPUT_AUTOSCALE.md`
- `docs/explanation/release_notes.md`

Code changes summary:

- Database throughput 404s now return a container-targeted status instead of failing the whole status endpoint.
- The backend discovers containers and reads each container's dedicated throughput settings.
- The Scale tab now shows container mode/current RU alongside utilization and request units.
- Added a Container Throughput Policies modal where admins can configure each container's min/max RU, scale-up/down thresholds, step sizes, cooldowns, and guardrail ignore flags.
- Manual scale requests can now target a specific container.
- Background autoscale can choose a dedicated container target when database throughput is absent.

## Validation

Test results:

- Python syntax validation for changed backend modules.
- JavaScript syntax validation for `admin_settings.js`.
- Functional autoscale logic coverage for database and container-targeted decisions.
- UI coverage for the Scale-tab Cosmos controls and container policy modal.

Before/after comparison:

- Before: a missing database-level throughput resource returned a 404 and the Cosmos throughput card failed to load.
- After: the card loads container status, identifies container-targeted capacity, and exposes per-container policy controls.

Related config.py version update:

- Application version updated to `0.241.148` in `application/single_app/config.py`.
