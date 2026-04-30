# AZD Postprovision Cosmos Firewall Runner Access Fix

Fixed/Implemented in version: **0.237.054**

## Issue Description

`azd provision` and `azd up` could still fail in `postprovision` after the Cosmos DB key fallback was added, because the deployment runner itself was not allowed through the Cosmos DB firewall.

## Root Cause Analysis

When private networking is enabled and the deployment runner is outside the private network path, Cosmos DB can block the local post-deployment settings update even when the script uses the primary key. The request still originates from the runner's public egress IP and must be allowed by the Cosmos DB firewall.

## Technical Details

### Files Modified

- `deployers/azure.yaml`
- `functional_tests/test_azd_windows_hooks.py`
- `application/single_app/config.py`

### Code Changes Summary

- Added postprovision helper logic to detect the deployment runner public IP through `api.ipify.org`.
- Added hook logic to merge that IP into the existing Cosmos DB IP rules before `postconfig.py` connects.
- Kept the Cosmos DB key fallback so the deployment remains independent of Cosmos RBAC propagation timing.

## Validation

- Functional test: `functional_tests/test_azd_windows_hooks.py`
- Expected outcome: repeated `azd up` and `azd provision` runs can seed Cosmos DB settings from a public deployment runner without manual Cosmos firewall edits.