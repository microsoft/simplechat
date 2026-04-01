# AZD Windows Postprovision Hook Fix

Fixed/Implemented in version: **0.237.049**

## Issue Description

Windows `azd provision` runs were failing after infrastructure creation with an invalid hook configuration error for `postprovision`.

## Root Cause Analysis

`deployers/azure.yaml` defined a Windows hook for `preprovision`, but `postprovision`, `predeploy`, and `postup` only defined `posix` hook blocks. On Windows, AZD requires a valid `windows` hook definition with a `run` command for hooks that will execute on that platform.

## Technical Details

### Files Modified

- `deployers/azure.yaml`
- `functional_tests/test_azd_windows_hooks.py`
- `application/single_app/config.py`

### Code Changes Summary

- Added a native `windows` `postprovision` hook that performs Cosmos DB role assignment, installs Python dependencies, runs post-configuration, and restarts the web app.
- Added native `windows` `predeploy` and `postup` hooks so the Windows deployment path remains valid beyond provisioning.
- Added a regression test that checks for required Windows hook coverage in `deployers/azure.yaml`.

## Validation

- Workspace validation confirms the updated YAML, Python test, and version metadata are syntactically valid.
- Functional regression coverage confirms the Windows hook definitions are present in `deployers/azure.yaml`.

## Impact Analysis

- Fixes Windows AZD deployments that previously failed immediately after provisioning completed.
- Prevents the next AZD lifecycle stage from failing for the same missing Windows hook pattern.