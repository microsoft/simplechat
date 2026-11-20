# Cosmos Container Creation Under Managed Identity Fix

## Issue

A release that adds a Cosmos DB container can fail to start after `azd deploy` when the app uses managed identity.

At startup `config.py` calls `create_container_if_not_exists` for every container. With key authentication that creates any missing container. With managed identity, Cosmos DB rejects container creation on its data-plane endpoint (HTTP 403, substatus 5300) whatever data-plane role the identity holds, so a missing container raised during import and the app did not start.

`azd deploy` only builds and rolls out the image; it does not re-run Bicep. Containers declared in Bicep therefore appear only after `azd provision` or `azd up`, and 11 containers the app uses were not declared in Bicep at all.

## Root Cause

- The app created containers only through the Cosmos data plane, which never allows it for Entra-authenticated callers.
- The deployers had fallen behind the app's container list. Bicep was missing 11 containers; Terraform was missing the same 11 plus `custom_pages`, `governance_policies` and `governance_item_policies`.

The app identity already had the right permission in a different place: the deployers give it Azure **Contributor** on the Cosmos account, which includes `Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers/write` through Azure Resource Manager (ARM). The app never used ARM for this.

## Version

Fixed in **0.261.475**. Deployers version **1.0.41**.

## Technical Details

### Files Modified

| File | Change |
|------|--------|
| `application/single_app/functions_cosmos_container_provisioning.py` | New. Creates a container through ARM: looks it up first, creates it with `PUT` when missing, and on HTTP 202 polls the container resource until it exists. |
| `application/single_app/config.py` | The container-creation wrapper falls back to ARM when the data-plane create returns 403 under managed identity. Key authentication is unchanged. |
| `deployers/bicep/modules/cosmosDb.bicep`, `deployers/bicep/main.json` | Declare the 11 missing containers. `main.json` rebuilt with Bicep 0.44.1. |
| `deployers/terraform/main.tf` | Declare the 14 missing containers; set `AZURE_SUBSCRIPTION_ID`, `AZURE_RESOURCE_GROUP` and `AZURE_COSMOS_ACCOUNT_NAME`. |
| `deployers/azurecli/deploy-simplechat.ps1` | Set `AZURE_SUBSCRIPTION_ID`, `AZURE_RESOURCE_GROUP` and `AZURE_COSMOS_ACCOUNT_NAME`. |
| `deployers/Grant-CosmosContainerCreatePermission.ps1` | New admin script that grants the identity permission to create containers through ARM. |
| `deployers/version.txt` | 1.0.40 → 1.0.41. |

### ARM Fallback

- Triggers only when `AZURE_COSMOS_AUTHENTICATION_TYPE=managed_identity` and the data-plane create fails with HTTP 403.
- The target comes from `AZURE_SUBSCRIPTION_ID`, `AZURE_RESOURCE_GROUP` and `AZURE_COSMOS_ACCOUNT_NAME` (or the account name in `AZURE_COSMOS_ENDPOINT`). All three deployers now set them. When the subscription or resource group setting is absent, for example on a deployment provisioned before these settings existed and updated only with `azd deploy`, the app uses its own App Service subscription and resource group from the platform variables `WEBSITE_OWNER_NAME` and `WEBSITE_RESOURCE_GROUP`. No admin input is needed, because every deployer puts the Cosmos account in the app's resource group.
- If the Cosmos database is not found there (the account lives elsewhere), the app creates nothing and logs that `AZURE_RESOURCE_GROUP` and `AZURE_SUBSCRIPTION_ID` must be set.
- The resource manager endpoint and authority follow `AZURE_ENVIRONMENT`, so US Government and custom clouds work.
- The container keeps the definition the app asked for: partition key, `default_ttl` and `indexing_policy`. Any other option raises instead of being dropped.
- If ARM already has the container (another instance created it first) nothing is written.
- It waits on the container resource rather than Cosmos's async-operation URL, because that URL sits at subscription scope and an account-scoped role cannot read it.
- The container is created without its own throughput setting, the same as a data-plane create. Use the Cosmos throughput settings or `New-CosmosContainerDynamicRUs.ps1` to put it on autoscale.
- On failure the app logs `[CosmosContainers] Could not create a missing Cosmos container under managed identity.` with the container name and reason, then raises. A 401/403 from ARM names the grant script.

### Grant Script

`deployers/Grant-CosmosContainerCreatePermission.ps1` is for deployments where the identity does not have Contributor on the Cosmos account (for example manual deployments, or after Contributor was removed). It needs the Azure CLI and rights to create role definitions and role assignments.

```powershell
.\deployers\Grant-CosmosContainerCreatePermission.ps1 -ResourceGroupName "<rg>" -CosmosAccountName "<cosmos account>" -WebAppName "<app service>"
```

- By default it creates the custom role `SimpleChat Cosmos Container Creator <rg>` with only `databaseAccounts/read`, `sqlDatabases/read`, `sqlDatabases/containers/read` and `sqlDatabases/containers/write`, and assigns it on the Cosmos account. That role grants no key, item or account-settings access.
- `-UseBuiltInRole` assigns `DocumentDB Account Contributor` instead (broader, including key listing).
- `-PrincipalId` targets a user-assigned identity. `-WhatIf` shows the changes without making them.
- Restart the App Service afterwards so it retries creating missing containers.

Cosmos data-plane roles cannot be extended to allow container creation, so an ARM role is the only way to grant this to a managed identity.

## Validation

- `functional_tests/test_cosmos_container_arm_provisioning.py` checks that every container the app creates is declared with the same partition key in `cosmosDb.bicep`, `main.json` and Terraform, and covers the ARM fallback: existing container left alone, creation with the requested definition, waiting on 202, the 403 message, missing settings, unsupported options, and that only 403 triggers it. It also checks the App Service platform-variable fallback, the error for an account in another resource group, and that all three deployers set the location settings.
- Not yet verified against a live managed-identity deployment.

### Before / After

| Scenario | Before | After |
|----------|--------|-------|
| Key auth, new container, `azd deploy` | Created at startup | Unchanged |
| Managed identity, new container, `azd deploy` | 403 at startup; app fails to start | Created through ARM at startup |
| Managed identity, identity lacks ARM container write | 403 at startup | Fails with a log naming the grant script |
| `azd provision` | 11 containers missing from Bicep | All containers declared |
| Older deployment without `AZURE_SUBSCRIPTION_ID` / `AZURE_RESOURCE_GROUP`, `azd deploy` only | — | Found from App Service platform variables |
