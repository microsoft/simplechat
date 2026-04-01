# ACR Predeploy Temporary Firewall Open Fix

Fixed/Implemented in version: **0.237.061**

## Issue Description

`azd up` could still fail during `predeploy` because `az acr build` runs through Azure Container Registry Tasks and the registry firewall denied the Azure-hosted build worker IP.

## Root Cause Analysis

The registry remained in a deny-by-default state during the predeploy cloud build step. Even with explicit runner IP handling and trusted Azure services bypass configured, the ACR Tasks worker still could not always authenticate through the registry firewall in this deployment flow.

## Technical Details

### Files Modified

- `deployers/azure.yaml`
- `functional_tests/test_acr_trusted_services_bypass.py`
- `application/single_app/config.py`

### Code Changes Summary

- Added predeploy helper logic to temporarily switch the ACR firewall default action to `Allow` during `az acr build` when private networking is enabled.
- Added restoration logic to return the ACR firewall default action to `Deny` after the build and during predeploy cleanup if the build fails.
- Kept the final `postup` step that disables ACR public access entirely after deployment finishes.

## Validation

- Functional test: `functional_tests/test_acr_trusted_services_bypass.py`
- Expected outcome: `az acr build` can complete during predeploy, and the registry returns to a restricted state after the build finishes or fails.