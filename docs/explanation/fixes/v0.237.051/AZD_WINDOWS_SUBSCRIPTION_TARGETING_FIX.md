# AZD Windows Subscription Targeting Fix

Fixed in version: 0.237.051

## Issue

Windows `azd postprovision`, `predeploy`, and `postup` hooks could fail to resolve the deployment resource group even when the resource group existed.

## Root Cause

The Windows hook fallback logic validated `var_rgName` and queried Cosmos DB and Web App metadata by using the Azure CLI's current default subscription. If the local Azure CLI context was pointed at a different subscription than the active AZD environment, the helper incorrectly concluded that the resource group did not exist.

## Technical Details

- Updated the Windows hook logic in `deployers/azure.yaml` to resolve the target subscription from `AZURE_SUBSCRIPTION_ID` or `var_subscriptionId` before falling back to `az account show`.
- Added `--subscription $subscriptionId` to the Windows Azure CLI calls used for resource-group validation, Cosmos DB lookup, Web App lookup, role-definition lookup, web app restart/stop/start, ACR build, and private networking updates.
- Updated the Windows hook regression test to verify explicit subscription targeting.
- Updated `application/single_app/config.py` to version `0.237.051`.

## Validation

- Functional test: `functional_tests/test_azd_windows_hooks.py`
- Expected outcome: Windows AZD hooks resolve and operate on the deployment resources even when the local Azure CLI default subscription is different from the AZD target subscription.