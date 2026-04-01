# Simple Chat - Deployment using Azure CLI + PowerShell

[Return to Main](../README.md)

## Overview

This deployment path uses [deploy-simplechat.ps1](deploy-simplechat.ps1) to provision the core Simple Chat resources with Azure CLI and PowerShell.

This option is useful when you want a script-driven deployment flow without using AZD or Terraform.

It is also useful when you want more script-level control over deployment sequencing and post-deployment recovery steps than the native AZD workflow provides.

For day-to-day work on this deployer, Visual Studio Code and Dev Containers are recommended so the script, repository layout, and Docker build context stay consistent across environments.

## What this deployer does

The Azure CLI deployer provisions the main Simple Chat application resources, including:

- container image build in Azure Container Registry via `az acr build` when enabled
- Resource group
- App Service plan and web app
- Azure Container Registry integration
- Cosmos DB
- Azure OpenAI account creation or reuse
- Azure OpenAI default GPT and embedding model deployments
- Azure AI Search
- Document Intelligence
- Key Vault
- Application Insights and Log Analytics
- Optional Entra security groups

## Private networking support

This deployer now supports the same core private networking flow as the Bicep deployer for the services it provisions.

It can:

- create a new VNet with dedicated App Service integration and private endpoint subnets
- reuse an existing VNet by supplying existing subnet resource IDs
- create private endpoints for Key Vault, Cosmos DB, Azure Container Registry, Azure AI Search, Azure OpenAI, Document Intelligence, Storage, and the App Service
- create private DNS zones automatically
- reuse customer-managed private DNS zones by resource ID
- create or skip private DNS VNet links on a per-zone basis

If you provide only external endpoint information without Azure resource metadata, the script cannot automate Azure OpenAI private endpoint creation for that endpoint.

## Files in this folder

- [deploy-simplechat.ps1](deploy-simplechat.ps1) - Main deployment script
- [destroy-simplechat.ps1](destroy-simplechat.ps1) - Cleanup script
- [appRegistrationRoles.json](appRegistrationRoles.json) - App role definition source
- [ai_search-index-group.json](ai_search-index-group.json) - Group search index definition
- [ai_search-index-user.json](ai_search-index-user.json) - User search index definition

## Prerequisites

Before running the deployment:

1. Install Azure CLI
2. Install PowerShell
3. Sign in to the target Azure cloud and subscription
4. Make sure an Azure Container Registry already exists
5. Make sure Azure OpenAI is already available if you plan to reuse an existing instance
6. Make sure you have permission to create resources in the target subscription and tenant
7. If private networking is enabled, make sure you can manage VNets, subnets, private endpoints, private DNS zones, and private DNS VNet links
8. If `param_BuildContainerImageWithAcr = $true`, make sure the target source context contains [application/single_app/Dockerfile](application/single_app/Dockerfile) and the rest of the repository files needed by that Docker build

Platform note:

- Windows users can run the examples directly in PowerShell.
- Linux and macOS users should run the same script with `pwsh`.
- Keep PowerShell variable syntax in PowerShell. This deployer is PowerShell-first, even when Azure CLI commands are part of the workflow.

For Azure Government:

```azurecli
az cache purge
az account clear
az cloud set --name AzureUSGovernment
az login --scope https://management.core.usgovcloudapi.net//.default
az login --scope https://graph.microsoft.us//.default
az account set -s "<subscription-id>"
```

For Azure Commercial:

```azurecli
az cache purge
az account clear
az cloud set --name AzureCloud
az login --scope https://management.azure.com//.default
az login --scope https://graph.microsoft.com//.default
az account set -s "<subscription-id>"
```

## Quick start

1. Open [deploy-simplechat.ps1](deploy-simplechat.ps1)
2. Update the configuration variables near the top of the script
3. Decide whether the script should build the image in ACR by setting `param_BuildContainerImageWithAcr`
4. Run the script from PowerShell

Example:

```powershell
cd deployers/azurecli
.\deploy-simplechat.ps1
```

Linux or macOS example:

```bash
cd deployers/azurecli
pwsh ./deploy-simplechat.ps1
```

## Configuration areas to review

The script contains editable configuration variables for:

- `globalWhichAzurePlatform`
- `paramTenantId`
- `paramLocation`
- `paramEnvironment`
- `paramBaseName`
- `ACR_NAME`
- `IMAGE_NAME`
- `param_BuildContainerImageWithAcr`
- `param_DockerfilePath`
- `param_DockerBuildContextPath`
- `param_PublishLatestImageTag`
- existing Azure OpenAI resource settings
- `param_DeployAzureOpenAiModels`
- `param_AzureOpenAiDeploymentType`
- Azure OpenAI GPT and embedding model names, versions, deployment names, and capacities
- optional Entra security group creation
- `param_EnablePrivateNetworking`
- `param_ExistingVirtualNetworkId`
- `param_ExistingAppServiceSubnetId`
- `param_ExistingPrivateEndpointSubnetId`
- `param_PrivateNetworkAddressPrefixes`
- `param_AppServiceIntegrationSubnetAddressPrefixes`
- `param_PrivateEndpointSubnetAddressPrefixes`
- `param_PrivateDnsZoneConfigs`

Review those values before running the script.

## Azure OpenAI deployment types and quota handling

The Azure CLI deployer can now create the default GPT and embedding model deployments for the Azure OpenAI account it creates or reuses. The Azure OpenAI account still uses the Cognitive Services account SKU, but the model deployments themselves use `Standard`, `DatazoneStandard`, or `GlobalStandard`.

For Azure Commercial, leave `param_AzureOpenAiDeploymentType` blank to be prompted during deployment, or set it explicitly in the script before you run it. For Azure Government, the script automatically uses `Standard`.

If a model deployment fails because of quota or regional availability, the script lets you retry that deployment with a different deployment type. If the retry still fails, request additional quota, lower the configured capacity, or set `param_DeployAzureOpenAiModels = $false` and reuse existing Azure OpenAI deployments instead.

Default model behavior:

- GPT deployment defaults to `gpt-4o`
- GPT model version defaults to `2024-11-20` in Azure Commercial and `2024-05-13` in Azure Government
- Embedding deployment defaults to `text-embedding-3-small` in Azure Commercial and `text-embedding-ada-002` in `usgovvirginia`
- Deployment capacities default to `100` for GPT and `80` for embeddings

After the infrastructure deployment completes, review the resulting Azure OpenAI deployments in the Simple Chat UI under `Admin Settings` > `AI Models` > `GPT Configuration` and `Embeddings Configuration`. For the full manual path, see `docs/setup_instructions_manual.md` and `docs/admin_configuration.md`.

## Container build behavior

By default, the Azure CLI deployer now builds the container image in ACR instead of assuming you already built and pushed it locally.

Default behavior:

- `param_BuildContainerImageWithAcr = $true`
- the script submits the build to ACR Tasks with `az acr build`
- the script uses [application/single_app/Dockerfile](application/single_app/Dockerfile)
- the build context defaults to the repository root via `..\..`

If you want to skip the image build and deploy an image that already exists in ACR:

- set `param_BuildContainerImageWithAcr = $false`
- set `IMAGE_NAME` to the repository and tag you want the App Service to pull

Example:

```powershell
$IMAGE_NAME = "simplechat:2026-03-11_main_42"
$param_BuildContainerImageWithAcr = $true
$param_DockerfilePath = "application/single_app/Dockerfile"
$param_DockerBuildContextPath = "..\.."
```

## Private DNS questions to answer before running

If `param_EnablePrivateNetworking = $true`, decide the following before you run the script:

- Will the script create private DNS zones, or will you reuse existing zones?
- If you reuse zones, what are the full resource IDs for those zones?
- Should the script create the VNet links, or are those links already managed by central networking?

Supported zone keys in `param_PrivateDnsZoneConfigs`:

- `keyVault`
- `cosmosDb`
- `containerRegistry`
- `aiSearch`
- `blobStorage`
- `cognitiveServices`
- `openAi`
- `webSites`

Example:

```powershell
$param_PrivateDnsZoneConfigs = @{
	openAi = @{
		zoneResourceId = "/subscriptions/<sub>/resourceGroups/<dns-rg>/providers/Microsoft.Network/privateDnsZones/privatelink.openai.azure.com"
		createVNetLink = $false
	}
	webSites = @{
		zoneResourceId = "/subscriptions/<sub>/resourceGroups/<dns-rg>/providers/Microsoft.Network/privateDnsZones/privatelink.azurewebsites.net"
	}
}
```

## Post-deployment tasks

After deployment, you should still complete the manual steps described in [deploy-simplechat.ps1](deploy-simplechat.ps1), including:

- App Service authentication provider setup
- Entra admin consent for Graph permissions
- Azure OpenAI model deployment review or existing-endpoint configuration
- Azure AI Search index deployment
- App settings review in the web UI
- Security group membership assignment, if used

## When to use another deployer

Choose a different deployer when:

- You want the broadest deployment coverage and the most mature deployment path → use [../bicep/README.md](../bicep/README.md)
- You want Terraform-managed infrastructure → use [../terraform/ReadMe.md](../terraform/ReadMe.md)
- You want an AZD-first deployment experience → use [../bicep/README.md](../bicep/README.md)

## Cleanup

To remove a deployment created with this folder, review and run [destroy-simplechat.ps1](destroy-simplechat.ps1).

Cleanup behavior:

- The destroy script deletes the Simple Chat deployment resource group.
- That removes private endpoints, private DNS zones, and the deployment VNet only when those resources were created inside that deployment resource group.
- If the deployment reused an existing VNet, existing subnets, or customer-managed private DNS zones outside the deployment resource group, those shared resources are not deleted.
- The destroy script also removes the Entra application registration and the Simple Chat security groups created by the Azure CLI deployer.

## Runtime Startup Behavior

- This deployer configures Azure App Service to run the published **container image**.
- Gunicorn is already started by the container entrypoint in `application/single_app/Dockerfile`.
- You do **not** need to add anything to App Service Stack Settings Startup command when using this deployer.
- If you manually switch to a native Python App Service deployment instead of containers, deploy the `application/single_app` folder and use:

```bash
python -m gunicorn -c gunicorn.conf.py app:app
```