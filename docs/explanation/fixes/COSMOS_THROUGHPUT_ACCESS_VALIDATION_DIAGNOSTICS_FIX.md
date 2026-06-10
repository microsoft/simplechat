# Cosmos Throughput Access Validation Diagnostics Fix

Fixed/Implemented in version: **0.241.183**

## Issue Description

The Cosmos DB Throughput setup guide did not explicitly tell admins which Azure identity needed RBAC, which role to assign, or where to assign it. When admins clicked **Validate Access**, failures could collapse into a generic `Failed to validate Cosmos throughput access` or `Failed to load Cosmos throughput status` message instead of identifying the missing permission.

## Root Cause Analysis

The status helper allowed database-throughput ARM read failures to escape the status response, so the validation route returned a generic 500. The browser also flattened validation checks into one message and only highlighted failed checks, which made it hard to see what succeeded before the failure.

## Technical Details

Files modified:

- `application/single_app/functions_cosmos_throughput.py`
- `application/single_app/static/js/admin/admin_settings.js`
- `application/single_app/templates/admin_settings.html`
- `application/single_app/config.py`
- `docs/explanation/features/v0.241.147/COSMOS_THROUGHPUT_AUTOSCALE.md`
- `functional_tests/test_cosmos_throughput_autoscale_logic.py`
- `ui_tests/test_admin_cosmos_throughput_settings_ui.py`

Code changes summary:

- Database throughput read failures are now preserved in the status payload as `throughput_error` instead of forcing a generic route failure.
- Validate Access now reports resource configuration, database throughput read access, scalable target discovery, container discovery, and Azure Monitor metrics as separate pass/fail checks.
- The Admin Settings alert renders every validation check with safe DOM APIs and includes successful checks for context.
- The setup guide now names the Azure App Service managed identity service principal, the custom `SimpleChat Cosmos Throughput Operator` role, the recommended assignment scopes, and the required management-plane permissions.

## Validation

Test results:

- Functional tests cover partial ARM and Azure Monitor permission failures without live Azure resources.
- UI tests cover the explicit setup-guide text and detailed validation-result renderer.

Before/after comparison:

- Before: admins could see only a generic failure and had to inspect logs to infer whether Cosmos throughput, container discovery, or Azure Monitor metrics failed.
- After: admins see which checks passed, which failed, and the Azure error detail for the failing check.

Related config.py version update:

- Application version updated to `0.241.183` in `application/single_app/config.py`.