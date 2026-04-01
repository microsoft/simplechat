# ACR Tasks Trusted Azure Services Fix

Fixed/Implemented in version: **0.237.058**

## Issue Description

`azd up` could fail during `predeploy` when `az acr build` submitted a cloud build to Azure Container Registry Tasks and the registry firewall denied the task worker IP.

## Root Cause Analysis

The registry network rules allowed only explicit IP addresses from `allowedIpAddresses`. That list is appropriate for deployment-runner access, but `az acr build` executes inside Azure through ACR Tasks, so the denied client IP is often an Azure-hosted worker rather than the local machine.

## Technical Details

### Files Modified

- `deployers/bicep/modules/azureContainerRegistry.bicep`
- `deployers/bicep/README.md`
- `functional_tests/test_acr_trusted_services_bypass.py`
- `application/single_app/config.py`

### Code Changes Summary

- Enabled `networkRuleBypassOptions: 'AzureServices'` for private-network Azure Container Registry deployments.
- Preserved the existing ACR network rule set and allowed IP list behavior.
- Documented that ACR build failures referencing an Azure-hosted IP are not solved by adding the workstation IP.

## Validation

- Functional test: `functional_tests/test_acr_trusted_services_bypass.py`
- Expected outcome: `az acr build` can authenticate through ACR Tasks on restricted registries once the updated registry configuration is provisioned.