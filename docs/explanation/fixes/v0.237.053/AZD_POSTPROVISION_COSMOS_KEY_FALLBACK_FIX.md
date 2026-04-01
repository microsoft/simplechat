# AZD Postprovision Cosmos Key Fallback Fix

Fixed/Implemented in version: **0.237.053**

## Issue Description

`azd up` and `azd provision` could repeatedly fail in the `postprovision` hook when `deployers/bicep/postconfig.py` attempted to read Cosmos DB settings through native RBAC before the data-plane role assignment was fully effective.

## Root Cause Analysis

The post-provision hook granted Cosmos DB data-plane access and then immediately invoked `postconfig.py`. Even when the role assignment command succeeded, Cosmos DB RBAC propagation could lag behind the next metadata read, causing the deployment to fail nondeterministically.

## Technical Details

### Files Modified

- `deployers/azure.yaml`
- `deployers/bicep/postconfig.py`
- `functional_tests/test_postconfig_azurecli_credential.py`
- `functional_tests/test_azd_windows_hooks.py`
- `application/single_app/config.py`

### Code Changes Summary

- Updated the AZD postprovision hooks to resolve the Cosmos DB primary key before running `postconfig.py`.
- Updated `postconfig.py` to use the deployment-time Cosmos DB key when present, while retaining Azure CLI credentials for Key Vault access and for Cosmos DB fallback behavior.
- Added regression coverage so the postconfig script and Windows hook definitions continue to include the deployment-time Cosmos key path.

## Validation

- Functional test: `functional_tests/test_postconfig_azurecli_credential.py`
- Functional test: `functional_tests/test_azd_windows_hooks.py`
- Expected outcome: AZD postprovision runs succeed repeatedly without depending on Cosmos DB RBAC propagation timing for the deployment-time settings update.