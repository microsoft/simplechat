# Core Service Key Deployment Fix

Fixed/Implemented in version: **0.240.002**

## Issue Description

Fresh Azure deployments using `authenticationType == key` could complete successfully while still leaving core runtime settings incomplete.

The most visible failure was Redis cache startup, where the application attempted to use key-based Redis authentication but the deployment had not populated `redis_key` into the `app_settings` document.

## Root Cause Analysis

The `deployers/bicep/postconfig.py` workflow was reading core service secrets from Key Vault after provisioning.

That created two problems:

- the deployer identity running `azd up` needed Key Vault secret-read permissions for all core services
- deployment-time failures to read those secrets were logged as warnings and the script still upserted partial settings into Cosmos DB

This conflicted with the intended architecture, where core application service keys should be obtained directly from Azure resources during deployment and only Semantic Kernel or plugin secrets should remain Key Vault-backed.

## Technical Details

### Files Modified

- `deployers/bicep/postconfig.py`
- `deployers/bicep/modules/appService.bicep`
- `deployers/bicep/modules/azureContainerRegistry.bicep`
- `deployers/bicep/modules/contentSafety.bicep`
- `deployers/bicep/modules/cosmosDb.bicep`
- `deployers/bicep/modules/documentIntelligence.bicep`
- `deployers/bicep/modules/openAI.bicep`
- `deployers/bicep/modules/redisCache.bicep`
- `deployers/bicep/modules/search.bicep`
- `deployers/bicep/modules/speechService.bicep`
- `application/single_app/config.py`
- `functional_tests/test_core_service_key_deployment_path.py`

### Code Changes Summary

- Refactored `postconfig.py` to retrieve core service keys directly from Azure resources through Azure CLI commands instead of Key Vault secret reads.
- Updated App Service key-auth environment wiring to use direct `listKeys()` and `listCredentials()` values for Cosmos DB, Azure AI Search, Document Intelligence, and ACR.
- Removed deployment-time Key Vault secret creation for core service keys from the relevant Bicep modules.
- Added regression coverage to ensure the deployment path stays aligned with the intended core-service-versus-plugin secret boundary.
- Bumped the application version to `0.240.002`.

### Testing Approach

- Added `functional_tests/test_core_service_key_deployment_path.py`.
- The regression test verifies that:
  - `postconfig.py` uses direct Azure resource key retrieval
  - App Service core key-auth settings are direct resource values
  - core Bicep modules no longer store deployment-time core secrets in Key Vault
  - `config.py` reflects the implementation version

## Validation

### Before

- key-auth deployments depended on Key Vault reads for core service settings
- deployer RBAC failures could leave Redis, Search, OpenAI, Document Intelligence, Speech, or Content Safety keys unset
- App Service still referenced several core key-auth values through Key Vault secrets

### After

- key-auth deployments collect core service keys directly from the provisioned Azure resources
- App Service receives direct core key-auth values where runtime environment variables still require them
- only plugin and Semantic Kernel secret flows remain intended Key Vault consumers

### Impact Analysis

This fix is intentionally scoped to deployment-time core service configuration.

- it improves first-run deployment reliability for `azd up`
- it preserves the ability for admins to later choose alternate auth modes in application settings
- it does not change the plugin or Semantic Kernel Key Vault secret model