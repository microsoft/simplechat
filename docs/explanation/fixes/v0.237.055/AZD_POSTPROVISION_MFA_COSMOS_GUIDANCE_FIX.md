# AZD Postprovision MFA Cosmos Guidance Fix

Fixed/Implemented in version: **0.237.055**

## Issue Description

`azd up` and `azd provision` could fail during Cosmos DB postprovision steps with a generic message that implied the required role assignments or firewall updates might already exist, even when Azure CLI was actually blocked by a multi-factor authentication or claims challenge.

## Root Cause Analysis

The postprovision flow treated several Azure CLI failures as benign and discarded the original error output. That hid the real cause and gave the user no actionable recovery path when Azure required another MFA prompt.

## Technical Details

### Files Modified

- `deployers/azure.yaml`
- `deployers/bicep/cosmosDb-postDeployPerms.sh`
- `functional_tests/test_azd_windows_hooks.py`
- `application/single_app/config.py`

### Code Changes Summary

- Added explicit MFA and claims-challenge detection for Cosmos DB control-plane and data-plane role assignment steps.
- Replaced ambiguous "may already exist" handling with differentiated logic for existing assignments versus MFA failures.
- Added a manual recovery message that tells the user to add the detected runner IP to the new Cosmos DB account firewall when the automated firewall update is blocked by MFA.
- Added explicit guidance to rerun `az login --scope https://management.azure.com//.default` when Azure CLI cannot read the Cosmos DB key because of MFA.

## Validation

- Functional test: `functional_tests/test_azd_windows_hooks.py`
- Expected outcome: Windows postprovision failures now surface actionable MFA guidance instead of masking the root cause.