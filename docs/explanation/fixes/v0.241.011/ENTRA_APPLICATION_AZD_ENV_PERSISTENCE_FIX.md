# Entra Application AZD Environment Persistence Fix

Fixed/Implemented in version: **0.241.011**

Related config.py update: `VERSION = "0.241.011"`

## Issue Description

After running `Initialize-EntraApplication.ps1`, users had to copy the app registration client ID, client secret, and service principal ID into a separate text file and paste them back into `azd up` prompts later.

## Root Cause Analysis

The Entra registration script created the values needed by `deployers/bicep/main.parameters.json`, but it only printed them to the terminal. It did not persist those values through `azd env set`, so the AZD environment could not supply `ENTERPRISE_APP_CLIENT_ID`, `ENTERPRISE_APP_CLIENT_SECRET`, or `ENTERPRISE_APP_SERVICE_PRINCIPAL_ID` automatically during provisioning.

## Technical Details

### Files Modified

- `deployers/Initialize-EntraApplication.ps1`
- `application/single_app/config.py`
- `README.md`
- `deployers/bicep/README.md`
- `functional_tests/test_entra_application_graph_mfa_auth.py`
- `functional_tests/test_entra_application_azd_env_persistence.py`

### Code Changes Summary

- Added `-AzdEnvironmentName` to explicitly choose the target AZD environment.
- Added `-SkipAzdEnvironmentUpdate` for standalone/manual app registration workflows.
- Added AZD environment resolution using `AZURE_ENV_NAME`, `.azure/config.json` `defaultEnvironment`, and then the deployment `Environment` value.
- Persisted app registration outputs with `azd env set --environment ...` after the client secret is generated.
- Kept persistence failures non-fatal so successful app registration creation still completes and prints manual recovery guidance.

## Validation

- Functional test: `functional_tests/test_entra_application_azd_env_persistence.py`
- Functional test: `functional_tests/test_entra_application_graph_mfa_auth.py`
- PowerShell parser validation for `deployers/Initialize-EntraApplication.ps1`
- Expected outcome: once the registration script completes, `azd up` can read the saved app registration values from the selected AZD environment and no longer prompts for those fields.