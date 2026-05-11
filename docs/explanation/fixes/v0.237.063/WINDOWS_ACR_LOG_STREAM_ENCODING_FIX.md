# Windows ACR Log Stream Encoding Fix

Fixed/Implemented in version: **0.237.063**

## Issue Description

`azd up` on Windows could fail during `predeploy` even when the ACR build itself was progressing, because Azure CLI crashed while streaming build logs containing characters that could not be encoded by the local `cp1252` console.

## Root Cause Analysis

The Windows predeploy hook called `az acr build` in streaming mode. Azure CLI attempted to render remote ACR Task log lines directly to the local console, and `colorama` raised a `UnicodeEncodeError` when the output included characters outside the active Windows code page.

## Technical Details

### Files Modified

- `deployers/azure.yaml`
- `functional_tests/test_acr_trusted_services_bypass.py`
- `application/single_app/config.py`

### Code Changes Summary

- Changed the Windows predeploy hook to queue ACR builds with `--no-logs` and capture the returned run ID.
- Added polling with `az acr task show-run` until the remote build completes, fails, or times out.
- Preserved the existing POSIX streaming behavior and the deployment-time ACR public access model.

## Validation

- Functional test: `functional_tests/test_acr_trusted_services_bypass.py`
- Expected outcome: Windows `azd up` no longer fails because Azure CLI cannot render Unicode ACR build logs to the local console.