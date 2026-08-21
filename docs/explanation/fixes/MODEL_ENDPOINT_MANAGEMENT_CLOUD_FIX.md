# Model Endpoint Management Cloud Fix

Fixed/Implemented in version: **0.250.004**

## Issue Description

Model endpoint saves could persist `auth.management_cloud` as `public` when the Management Cloud selector was hidden in the UI. This primarily affected managed identity configurations, where cloud selection should be owned by the app hosting environment instead of a user-editable endpoint setting.

In Azure Government or custom-cloud deployments, a hidden `public` value could later drive the wrong token audience or Foundry scope for model endpoint calls.

## Root Cause Analysis

The frontend defaulted the hidden Management Cloud field to `public`. The backend accepted that posted value as endpoint configuration even when the user could not actually choose the field and when managed identity cannot be used as a cross-cloud credential.

## Technical Details

Files modified:

- `application/single_app/functions_settings.py`
- `application/single_app/functions_model_endpoint_runtime.py`
- `application/single_app/route_backend_models.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/semantic_kernel_loader.py`
- `application/single_app/functions_workflow_runner.py`
- `application/single_app/config.py`
- `functional_tests/test_model_endpoint_management_cloud_environment.py`

Code changes summary:

- Added backend-owned normalization for model endpoint `auth.management_cloud` values.
- Derived non-editable cloud values from `AZURE_ENVIRONMENT` for `public`, `usgovernment`, and `custom` deployments.
- Preserved explicit cross-cloud values for Foundry service-principal endpoints where the UI intentionally exposes Management Cloud.
- Added shared Foundry scope resolution for model endpoint runtime paths.
- Added custom-cloud defaults for inherited authority and Foundry scope when model endpoint cloud is backend-owned.

## Testing Approach

Added `functional_tests/test_model_endpoint_management_cloud_environment.py` to validate:

- Managed identity endpoints in Azure Government normalize from hidden `public` to `government`.
- Managed identity endpoints in custom cloud inherit `custom`, app-level authority, and configured scope.
- Foundry service-principal endpoints preserve explicit cross-cloud selections.
- Blank service-principal cloud values receive the environment default.
- Custom cloud Foundry scope resolution fails closed when no custom scope is configured.

## Validation

Focused regression test result:

```text
All model endpoint management cloud normalization tests passed.
```

## Impact Analysis

Managed identity model endpoint configuration is now aligned with the app deployment cloud. Service principal endpoints retain intentional cross-cloud behavior only where the UI exposes the setting. Existing saved endpoints are normalized when loaded through existing model endpoint normalization paths.

Reference to config version update: `application/single_app/config.py` was updated to version `0.250.004`.