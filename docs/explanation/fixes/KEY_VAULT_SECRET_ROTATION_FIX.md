# Key Vault Secret Rotation Fix

Fixed in version: **0.250.121**

## Issue Description

When an existing action already had a secret stored in Key Vault, saving a new literal secret value could fail to update the Key Vault secret cleanly. A related edge case allowed the `Stored_In_KeyVault` placeholder to become a generated secret reference even when no existing Key Vault secret existed.

## Root Cause

The central Key Vault helper treated some failed writes as successful by returning the raw secret value, and placeholder preservation could generate a dead reference when no previous reference was available.

## Technical Details

### Files Modified

- `application/single_app/functions_keyvault.py`
- `application/single_app/functions_global_actions.py`
- `application/single_app/route_backend_plugins.py`
- `functional_tests/test_sql_plugin_key_vault_secret_storage.py`

### Code Changes Summary

- Literal replacement secrets now call `set_secret` and surface write failures.
- `Stored_In_KeyVault` only preserves an existing validated reference.
- Placeholder saves without an existing reference now return a validation error requiring the secret to be re-entered.
- Global action saves re-raise failures so admin routes can return actionable errors.
- Personal, group, and global action routes now surface Key Vault validation/write failures more clearly.

## Validation

- Added regression coverage for global, group, and personal action scopes.
- Added validation that Key Vault write failures do not fall back to raw secret persistence.
- Added validation that placeholder-only saves without existing references are rejected.

## Before/After

- **Before**: A failed Key Vault write could be saved as raw data or hidden behind a generic route failure.
- **After**: Key Vault writes fail hard, placeholders require a real existing reference, and routes surface the specific error.
