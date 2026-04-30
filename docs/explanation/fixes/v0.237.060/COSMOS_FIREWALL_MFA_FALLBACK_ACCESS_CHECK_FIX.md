# Cosmos Firewall MFA Fallback Access Check Fix

Fixed/Implemented in version: **0.237.060**

## Issue Description

`azd up` could still fail immediately when Azure CLI hit an MFA challenge while trying to update the Cosmos DB firewall, even if the required firewall rule had already been added manually and only propagation remained.

## Root Cause Analysis

The postprovision hook treated an MFA-blocked `az cosmosdb update` as a terminal failure. That stopped the deployment before it could verify whether Cosmos DB data-plane access had already become available through an existing or newly propagated firewall rule.

## Technical Details

### Files Modified

- `deployers/azure.yaml`
- `functional_tests/test_azd_windows_hooks.py`
- `application/single_app/config.py`

### Code Changes Summary

- Changed the Cosmos DB firewall update path so MFA errors no longer fail immediately.
- Added a fallback check that probes and waits for real Cosmos DB data-plane access after the MFA-blocked update attempt.
- Preserved the manual remediation guidance when the runner still cannot access Cosmos DB after the wait window.

## Validation

- Functional test: `functional_tests/test_azd_windows_hooks.py`
- Expected outcome: an MFA challenge during the firewall update step no longer blocks deployments that already have the correct Cosmos DB firewall rule in place and only need propagation time.