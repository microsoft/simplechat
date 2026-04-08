# ACR Deployment-Time Public Access Fix

Fixed/Implemented in version: **0.237.062**

## Issue Description

`azd up` could fail during `predeploy` because the hook attempted to change Azure Container Registry firewall settings live with Azure CLI, and that network mutation itself was blocked by MFA.

## Root Cause Analysis

The deployment flow relied on a privileged `az acr update` during predeploy to open the registry for `az acr build`. In environments with conditional access or MFA requirements, that update could fail before the build even started.

## Technical Details

### Files Modified

- `deployers/bicep/modules/azureContainerRegistry.bicep`
- `deployers/azure.yaml`
- `functional_tests/test_acr_trusted_services_bypass.py`
- `application/single_app/config.py`

### Code Changes Summary

- Changed the ACR deployment-time network rule default action to `Allow` when private networking is enabled.
- Removed the predeploy Azure CLI firewall toggle logic for ACR.
- Kept the final `postup` step that disables ACR public access after deployment completes.

## Validation

- Functional test: `functional_tests/test_acr_trusted_services_bypass.py`
- Expected outcome: `az acr build` can complete without requiring a live `az acr update` during predeploy, and the registry is still locked down in the final deployment step.