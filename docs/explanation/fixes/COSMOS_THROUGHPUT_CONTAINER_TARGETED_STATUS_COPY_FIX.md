# Cosmos Throughput Container-Targeted Status Copy Fix

Fixed/Implemented in version: **0.241.184**

## Issue Description

The Admin Settings Cosmos DB Throughput card showed a yellow warning when the configured database did not have database-level throughput and SimpleChat correctly switched to container-targeted throughput. The wording said database-level throughput was not found, which made customers think a supported container-targeted setup was broken.

## Root Cause Analysis

The frontend used warning styling and absence-focused language for the normal `container` capacity scope. That state can be expected when containers have dedicated throughput, so it should be presented as informational unless permissions or per-container metrics fail.

## Technical Details

Files modified:

- `application/single_app/functions_cosmos_throughput.py`
- `application/single_app/static/js/admin/admin_settings.js`
- `application/single_app/config.py`
- `docs/explanation/features/v0.241.147/COSMOS_THROUGHPUT_AUTOSCALE.md`
- `functional_tests/test_cosmos_throughput_autoscale_logic.py`
- `ui_tests/test_admin_cosmos_throughput_settings_ui.py`

Code changes summary:

- Changed the normal container-targeted status alert from warning to info.
- Reworded the message to say container-targeted throughput is active and explain which containers can be scaled.
- Reworded the Validate Access database-throughput check to avoid “not found” language when dedicated container throughput checks are being used successfully.

## Validation

Test results:

- Functional coverage verifies the neutral Validate Access message for container-targeted throughput mode.
- UI coverage verifies the new informational frontend copy and guards against the old warning-like text.

Before/after comparison:

- Before: normal container-targeted capacity displayed as a yellow warning and said database-level throughput was not found.
- After: normal container-targeted capacity displays as informational and says container-targeted throughput is active.

Related config.py version update:

- Application version updated to `0.241.184` in `application/single_app/config.py`.