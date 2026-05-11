# AZD Postprovision Cosmos Access Probe Fix

Fixed/Implemented in version: **0.237.057**

## Issue Description

`azd up` could still fail in `postprovision` with an MFA-gated Cosmos DB firewall update even after an administrator had already added the deployment runner IP manually.

## Root Cause Analysis

The postprovision hook tried to update the Cosmos DB firewall before proving whether the deployment runner already had Cosmos DB data-plane access. That caused an unnecessary write attempt through Azure CLI, which could still be blocked by conditional access and MFA requirements.

## Technical Details

### Files Modified

- `deployers/azure.yaml`
- `functional_tests/test_azd_windows_hooks.py`
- `application/single_app/config.py`

### Code Changes Summary

- Added a Cosmos DB data-plane access probe that runs after the primary key is retrieved.
- Short-circuited the firewall update step when the deployment runner can already reach Cosmos DB with the retrieved key.
- Updated the manual guidance to tell users that if they already added the IP manually, firewall propagation can still take up to 30 minutes.

## Validation

- Functional test: `functional_tests/test_azd_windows_hooks.py`
- Expected outcome: manual Cosmos DB firewall changes no longer trigger an unnecessary Azure CLI firewall update once the runner already has data-plane access.