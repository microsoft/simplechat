# AZD Windows Resource Group Name Resolution Fix

Fixed/Implemented in version: **0.237.050**

## Issue Description

Windows AZD hooks in `deployers/azure.yaml` could fail when `var_rgName` was stale or missing, which caused Cosmos DB role assignment, web app restart, and post-up resource updates to target a resource group that did not exist.

## Root Cause Analysis

The Windows hook implementations relied directly on the AZD environment variable `var_rgName` without validating it against Azure or falling back to discover the actual resource group for the deployed resources.

## Technical Details

### Files Modified

- `deployers/azure.yaml`
- `functional_tests/test_azd_windows_hooks.py`
- `application/single_app/config.py`
- `docs/explanation/release_notes.md`

### Code Changes Summary

- Added a `Resolve-ResourceGroupName` helper to the Windows `postprovision`, `predeploy`, and `postup` hooks.
- The helper validates `var_rgName`, falls back to Azure lookups through Cosmos DB and the web app, and writes the resolved value back to `var_rgName` for downstream steps such as `postconfig.py`.
- Extended regression coverage to verify the fallback logic remains present in `deployers/azure.yaml`.

## Validation

- Workspace validation confirms the updated YAML, test, documentation, and version metadata are syntactically valid.
- Functional regression coverage confirms the Windows hooks now include resource group fallback logic.

## Impact Analysis

- Fixes Windows AZD deployment failures caused by stale environment state.
- Keeps the Windows hook flow working even when the original resource group output is missing or out of date.