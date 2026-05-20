# SimpleChat Background Tasks Deployment Fix

Fixed in version: **0.241.057**

Deployer version: **1.0.2**

## Issue Description

Deployed containers could start with `SIMPLECHAT_RUN_BACKGROUND_TASKS` disabled, which prevented the in-app scheduler loops from running after startup. Long-running tabular generated-output jobs could still begin from the original request executor, but queued retry runs were not automatically picked up later.

## Root Cause Analysis

The application supports `SIMPLECHAT_RUN_BACKGROUND_TASKS` as an environment switch, but the deployer did not explicitly set it in App Service app settings. When the deployment environment carried the value as disabled, every web-process initialization logged `Background tasks disabled for this web process`, leaving queued retry jobs dependent on manual recovery.

## Version Implemented

Fixed in application version: **0.241.057**

Fixed in deployer version: **1.0.2**

## Technical Details

### Files Modified

- `deployers/bicep/modules/appService.bicep`
- `deployers/bicep/main.json`
- `deployers/azure.yaml`
- `deployers/azurecli/deploy-simplechat.ps1`
- `deployers/version.txt`
- `functional_tests/test_deployer_background_tasks_app_setting.py`

### Code Changes Summary

- Added `SIMPLECHAT_RUN_BACKGROUND_TASKS=1` to the Bicep App Service app settings used by `azd provision` and `azd up`.
- Added the same setting to the shipped ARM template used by one-click deploy.
- Added an `azd deploy` predeploy guard that sets `SIMPLECHAT_RUN_BACKGROUND_TASKS=1` before restarting the web app, covering image-only redeploys.
- Added the same setting to the legacy Azure CLI deployment script.
- Bumped `deployers/version.txt` from `1.0.1` to `1.0.2`.

### Testing Approach

- Added a functional source-level regression that verifies all deployment paths configure the background task setting.
- Compiled the new functional test.

## Impact Analysis

Fresh `azd up` deployments and subsequent `azd deploy` runs now explicitly enable SimpleChat background scheduler loops in the App Service container. This allows queued retry jobs, stale run cleanup, workflow scheduling, file sync scheduling, and similar app-managed loops to run after deployment.

## Validation

### Before

- App Service could retain or receive `SIMPLECHAT_RUN_BACKGROUND_TASKS=0` or `false`.
- Logs showed `Background tasks disabled for this web process`.
- Queued tabular retry runs were not automatically resumed.

### After

- App Service app settings include `SIMPLECHAT_RUN_BACKGROUND_TASKS=1`.
- `azd deploy` reinforces the setting even when infrastructure is not reprovisioned.
- The container starts the in-app background task loops unless explicitly changed after deployment.

## Related Version Updates

- `deployers/version.txt` was updated to **1.0.2**.