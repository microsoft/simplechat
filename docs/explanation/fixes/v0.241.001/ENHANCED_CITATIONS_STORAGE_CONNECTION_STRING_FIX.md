# Enhanced Citations Storage Connection String Fix

Fixed/Implemented in version: **0.240.003**

## Issue Description

`azd` deployments could provision the Azure Storage account used for Enhanced Citations, enable the feature in application settings, and still leave the storage connection string blank.

That produced an incomplete admin configuration for key-based storage authentication, leaving Enhanced Citations enabled but not fully usable until an administrator manually added the connection string.

## Root Cause Analysis

The `deployers/bicep/postconfig.py` script enabled Enhanced Citations and stored the blob endpoint, but it never retrieved and persisted the storage account connection string required by the application when `office_docs_authentication_type` is `key`.

As a result, the deployment pipeline populated only part of the required storage configuration.

## Technical Details

### Files Modified

- `deployers/bicep/postconfig.py`
- `application/single_app/config.py`
- `functional_tests/test_core_service_key_deployment_path.py`
- `functional_tests/test_enhanced_citations_storage_deployment_fix.py`

### Code Changes Summary

- Added Azure CLI retrieval of the storage account connection string during post-provision configuration.
- Persisted `office_docs_storage_account_url` into the Cosmos DB `app_settings` document when Enhanced Citations uses key authentication.
- Cleared the stored connection string when deployment config uses managed identity to avoid stale key-auth values.
- Added regression coverage for the new storage deployment path.
- Bumped the application version to `0.240.003`.

### Testing Approach

- Added `functional_tests/test_enhanced_citations_storage_deployment_fix.py`.
- Updated `functional_tests/test_core_service_key_deployment_path.py` to align with the current version.

## Validation

### Before

- `azd` post-provision enabled Enhanced Citations.
- the storage blob endpoint was written to app settings.
- the storage connection string remained blank for key-auth deployments.

### After

- `azd` post-provision still enables Enhanced Citations.
- the blob endpoint is preserved.
- the storage connection string is now written automatically for key-auth deployments, so the feature has the settings it needs immediately after provisioning.

### Impact Analysis

This fix is scoped to deployment-time population of Enhanced Citations storage settings.

- it improves first-run reliability for `azd up` and `azd provision`
- it removes the need for manual admin repair of the storage connection string after provisioning
- it preserves the managed identity path by keeping the connection-string field empty when key authentication is not used