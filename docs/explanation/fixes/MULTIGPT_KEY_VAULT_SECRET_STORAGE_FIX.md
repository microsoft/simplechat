# MULTIGPT KEY VAULT SECRET STORAGE FIX

Fixed in version: **0.239.156**

## Overview

This fix adds Azure Key Vault support for MultiGPT model endpoint secrets across global, personal, and group endpoint configurations.

When `enable_key_vault_secret_storage` is enabled, endpoint secrets entered for MultiGPT connections are now stored in Key Vault instead of remaining in persisted endpoint payloads. Backend fetch, test, Foundry listing, and runtime execution paths now resolve the stored secret server-side so the UI does not need to receive plaintext secrets after the initial save.

Version `0.239.156` also fixes a follow-up regression in Foundry model discovery where sync fetch routes could import an async credential helper and fail with `'coroutine' object has no attribute 'token'` when requesting model lists.

## Issue Description

MultiGPT endpoint configuration supported secret-bearing auth fields such as:

- `auth.api_key`
- `auth.client_secret`

Those fields were not integrated with the existing Key Vault helper flow that already supported agents and plugins.

As a result:

- endpoint secrets could remain outside the existing Key Vault lifecycle
- admin and workspace editors depended on secrets being present in the browser to fetch models or test models
- reopening a saved endpoint without the plaintext secret could break fetch and test operations
- runtime consumers could fail if a saved endpoint only held a Key Vault reference and the execution path did not resolve it

## Root Cause Analysis

The original implementation had three separate gaps:

1. MultiGPT endpoint auth fields did not have endpoint-specific Key Vault save/get/delete helpers.
2. Fetch and test routes expected secrets in request payloads from the UI instead of merging with persisted endpoint configuration and resolving stored secrets on the server.
3. Runtime endpoint consumers, especially Semantic Kernel multi-endpoint resolution and Foundry endpoint enrichment, used saved endpoint auth directly without a consistent Key Vault resolution step.

The follow-up regression was caused by a fourth issue:

4. Sync Foundry model-discovery code reused an async credential helper from the Foundry runtime layer, so synchronous token retrieval returned a coroutine instead of a token object.

## Technical Details

### Files Modified

- `application/single_app/functions_keyvault.py`
- `application/single_app/functions_settings.py`
- `application/single_app/route_backend_models.py`
- `application/single_app/route_frontend_admin_settings.py`
- `application/single_app/semantic_kernel_loader.py`
- `application/single_app/foundry_agent_runtime.py`
- `application/single_app/static/js/admin/admin_model_endpoints.js`
- `application/single_app/static/js/workspace/workspace_model_endpoints.js`
- `application/single_app/config.py`
- `functional_tests/test_foundry_model_fetch_sync_credentials.py`
- `functional_tests/test_model_endpoints_key_vault_secret_storage.py`
- `functional_tests/test_workspace_multi_endpoints.py`
- `functional_tests/test_model_endpoint_normalization_backend.py`
- `functional_tests/test_model_endpoints_api_key_manual_models.py`

### Code Changes Summary

- Added a dedicated `model-endpoint` Key Vault source and endpoint-specific helper functions for save, get, delete, and cleanup of obsolete references.
- Added shared endpoint merge helpers so empty secret fields from the UI preserve stored secrets during edits.
- Updated endpoint normalization to strip UI-only secret-presence flags before persistence.
- Updated global, personal, and group endpoint save flows to store endpoint secrets in Key Vault when enabled.
- Updated fetch/test request handling so saved endpoint auth is resolved server-side by endpoint ID and scope.
- Updated Foundry agent listing and Semantic Kernel runtime endpoint selection to resolve Key Vault-backed endpoint auth before execution.
- Split Foundry credential construction so runtime invocation keeps async credentials while sync model discovery and project SDK flows use sync Azure credentials.
- Updated admin and workspace endpoint editors to use placeholder behavior for stored secrets and to include endpoint IDs in fetch/test requests.

### Secret Handling Behavior

- New or edited endpoint secrets are saved to Key Vault when Key Vault is enabled.
- Existing saved endpoint secrets are not backfilled automatically.
- Saved endpoint edits preserve stored secrets unless the auth type changes or a new secret is provided.
- Obsolete endpoint Key Vault references are deleted when endpoint auth configuration changes or when an endpoint is removed.

## Testing Approach

### Functional Tests

- `functional_tests/test_model_endpoints_key_vault_secret_storage.py`
- `functional_tests/test_foundry_model_fetch_sync_credentials.py`
- `functional_tests/test_workspace_multi_endpoints.py`
- `functional_tests/test_model_endpoint_normalization_backend.py`
- `functional_tests/test_model_endpoints_api_key_manual_models.py`

### Validation Covered

- Key Vault save, placeholder fetch, value fetch, and cleanup for endpoint auth secrets
- sync Foundry credential builders returning token objects instead of coroutine values
- frontend sanitization of endpoint secrets and secret-presence flags
- backend normalization of endpoint payloads without persisting UI-only flags
- admin and workspace request wiring for endpoint-ID-based stored-secret resolution

## Impact Analysis

### Before

- MultiGPT endpoint secrets were not handled by the existing Key Vault helper pattern.
- Saved endpoint tests could fail after reopening the editor because the browser no longer had the secret value.
- Runtime endpoint consumers did not consistently resolve Key Vault-backed endpoint auth.

### After

- MultiGPT endpoint secrets follow the same secure storage pattern as other Key Vault-backed secret types.
- Endpoint fetch/test flows work with stored secrets without rehydrating plaintext values into the UI.
- Foundry model discovery works again for sync fetch routes because sync token acquisition no longer uses async credentials.
- Runtime consumers resolve endpoint secrets server-side before model access.

## Validation Results

Validated with targeted functional test runs for:

- endpoint Key Vault lifecycle
- workspace endpoint sanitization
- endpoint normalization
- API key manual model entry and per-model test wiring