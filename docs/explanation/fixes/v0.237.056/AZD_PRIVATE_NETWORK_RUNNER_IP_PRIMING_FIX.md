# AZD Private Network Runner IP Priming Fix

Fixed/Implemented in version: **0.237.056**

## Issue Description

When private networking was enabled, deployment runners that needed temporary public access to Cosmos DB or Azure Container Registry could still fail during `postprovision` because their public IP was not present in the initial firewall rules created during provisioning.

## Root Cause Analysis

The deployment runner IP was only handled after infrastructure creation, which is too late for firewall rules that are established by the Bicep deployment itself. Manual firewall edits also caused confusion because propagation can take time after the portal update is saved.

## Technical Details

### Files Modified

- `deployers/bicep/validate_azd_prerequisites.py`
- `deployers/azure.yaml`
- `deployers/bicep/README.md`
- `functional_tests/test_azd_prerequisites_allowed_ip_auto_merge.py`
- `application/single_app/config.py`

### Code Changes Summary

- Added runner public IP detection to the preprovision prerequisite script.
- Added automatic persistence of the resolved IP into `ALLOWED_IP_RANGES` through `azd env set` before infrastructure provisioning starts.
- Added explicit guidance that manual Cosmos DB firewall updates can take up to 30 minutes to propagate before rerunning `azd up`.

## Validation

- Functional test: `functional_tests/test_azd_prerequisites_allowed_ip_auto_merge.py`
- Functional test: `functional_tests/test_azd_windows_hooks.py`
- Expected outcome: private-network deployments can carry the deployment runner IP into initial Cosmos DB and Azure Container Registry firewall rules without requiring a later manual retry.