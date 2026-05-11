# Cosmos Firewall CIDR and Propagation Fix

Fixed/Implemented in version: **0.237.059**

## Issue Description

`azd up` could still fail in `postprovision` after a manual Cosmos DB firewall change because the hook only recognized exact IP matches and did not tolerate propagation delay after the rule was configured.

## Root Cause Analysis

Manual firewall entries may be configured as CIDR ranges such as `/32`, and Cosmos DB firewall activation can lag behind the ARM configuration change. The hook treated those cases as missing rules and attempted another Azure CLI firewall update, which could be blocked by MFA.

## Technical Details

### Files Modified

- `deployers/azure.yaml`
- `functional_tests/test_azd_windows_hooks.py`
- `application/single_app/config.py`

### Code Changes Summary

- Added CIDR-aware runner IP matching for Cosmos DB firewall rules.
- Added a short propagation wait loop when the runner IP is already configured on the Cosmos DB firewall or has just been added.
- Preserved the explicit MFA guidance when the hook truly needs to perform a firewall update and Azure CLI blocks it.

## Validation

- Functional test: `functional_tests/test_azd_windows_hooks.py`
- Expected outcome: manual Cosmos DB firewall rules such as `x.x.x.x/32` no longer trigger an unnecessary MFA-gated update, and recent firewall changes are given time to propagate before the deployment fails.