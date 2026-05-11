# Postconfig Azure CLI Credential Fix

Fixed/Implemented in version: **0.237.052**

## Issue Description

Windows `azd provision` runs could still fail in the `postprovision` hook after Cosmos DB role assignments succeeded.

## Root Cause Analysis

The Windows hook granted Cosmos DB permissions to the signed-in Azure CLI user, but `deployers/bicep/postconfig.py` used `DefaultAzureCredential`. On developer workstations, that credential chain can prefer a different identity source than the Azure CLI session, which caused Cosmos DB to reject the metadata read request with a native RBAC authorization error.

## Technical Details

### Files Modified

- `deployers/bicep/postconfig.py`
- `functional_tests/test_postconfig_azurecli_credential.py`
- `application/single_app/config.py`

### Code Changes Summary

- Replaced `DefaultAzureCredential` with `AzureCliCredential` in `deployers/bicep/postconfig.py`.
- Kept the deployment-time token preflight so authentication failures still surface early.
- Added regression coverage to ensure the post-configuration script continues using the Azure CLI credential path.

## Validation

- Functional test: `functional_tests/test_postconfig_azurecli_credential.py`
- Expected outcome: the AZD Windows `postprovision` hook uses the same Azure CLI identity for Cosmos DB and Key Vault access that the hook granted permissions to earlier in the workflow.