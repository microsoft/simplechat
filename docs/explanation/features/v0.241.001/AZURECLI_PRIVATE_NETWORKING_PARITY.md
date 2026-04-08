# Azure CLI Private Networking Parity

Fixed/Implemented in version: **0.237.023**

## Overview

This feature extends the Azure CLI deployer so it can support the same core private networking flow already available in the Bicep deployer for the services provisioned by `deploy-simplechat.ps1`.

The Azure CLI deployment script can now:

- Create a new deployment VNet when private networking is enabled
- Reuse an existing VNet by supplying existing subnet resource IDs
- Require separate App Service integration and private endpoint subnets when reusing enterprise networking
- Submit the application container build to Azure Container Registry with `az acr build` instead of requiring a local Docker build step in the Azure CLI deployment path
- Create private endpoints for the main Simple Chat dependencies
- Create private DNS zones automatically when customer-managed zones are not supplied
- Reuse existing private DNS zones by resource ID
- Create or skip private DNS VNet links on a per-zone basis
- Disable public network access on the private-networked resources after private endpoint configuration

## Dependencies

- Azure CLI with support for networking, web app, private endpoint, and private DNS commands
- PowerShell
- Rights to manage:
  - Virtual networks and subnets
  - Private endpoints
  - Private DNS zones
  - Private DNS VNet links
  - Target application resources such as App Service, Storage, Search, Key Vault, Cosmos DB, and Cognitive Services

## Technical Specifications

### Architecture Overview

The Azure CLI script now follows the same general private networking shape as the Bicep deployer:

1. Dedicated subnet for App Service regional VNet integration
2. Dedicated subnet for private endpoints
3. Private DNS zones per service, with optional zone reuse
4. VNet links per private DNS zone, with optional suppression when central IT manages links separately
5. Private endpoints for:
   - Key Vault
   - Cosmos DB
   - Azure Container Registry
   - Azure AI Search
   - Azure OpenAI
   - Document Intelligence
   - Storage
   - App Service

### Configuration Options

Key script settings added or expanded in `deploy-simplechat.ps1`:

- `param_BuildContainerImageWithAcr`
- `param_DockerfilePath`
- `param_DockerBuildContextPath`
- `param_PublishLatestImageTag`
- `param_EnablePrivateNetworking`
- `param_ExistingVirtualNetworkId`
- `param_ExistingAppServiceSubnetId`
- `param_ExistingPrivateEndpointSubnetId`
- `param_PrivateNetworkAddressPrefixes`
- `param_AppServiceIntegrationSubnetAddressPrefixes`
- `param_PrivateEndpointSubnetAddressPrefixes`
- `param_AllowedIpAddresses`
- `param_PrivateDnsZoneConfigs`
- `param_ShowPrivateNetworkingChecklist`
- `param_ConfirmPrivateNetworkingPlan`

### File Structure

Primary files involved:

- `deployers/azurecli/deploy-simplechat.ps1`
- `deployers/azurecli/destroy-simplechat.ps1`
- `deployers/azurecli/README.md`
- `application/single_app/config.py`

## Usage Instructions

### New VNet Flow

Set:

- `param_EnablePrivateNetworking = $true`
- Leave the existing VNet and subnet ID values blank

The script will create:

- A VNet
- An `AppServiceIntegration` subnet
- A `PrivateEndpoints` subnet
- Private DNS zones when overrides are not provided
- Private endpoints for the supported services

### Existing VNet Flow

Set:

- `param_EnablePrivateNetworking = $true`
- `param_ExistingVirtualNetworkId` (optional if both subnet IDs already imply the same VNet)
- `param_ExistingAppServiceSubnetId`
- `param_ExistingPrivateEndpointSubnetId`

The script validates that:

- Both subnet IDs are provided
- Both subnets belong to the same VNet
- The App Service subnet is delegated to `Microsoft.Web/serverFarms`

### Private DNS Zone Reuse

Use `param_PrivateDnsZoneConfigs` to reuse enterprise-managed zones and optionally skip VNet link creation.

### Container Build Flow

By default, the Azure CLI deployer now submits the container build to ACR Tasks before the web app is created.

This allows administrators to use the Azure CLI deployment path without building the image locally first, as long as:

- the target ACR already exists
- the deployment identity can run `az acr build`
- the configured build context includes the repository files required by `application/single_app/Dockerfile`

## Testing and Validation

### Validation Approach

Validation performed for this change included:

- PowerShell parser and workspace error checks on the updated script
- Review of the Azure CLI deployer README and supporting documentation
- Cross-checking the Azure CLI logic against the Bicep deployer private networking structure

### Known Limitations

- The Azure CLI deployer now covers the core private networking scenario for the services it provisions, but the Bicep deployer remains the most complete deployment path across the repository.
- Azure OpenAI private endpoint automation still requires a resolvable Azure resource ID. Endpoint-only reuse does not provide enough metadata for that automation.
- Private networking in enterprise environments still depends on customer DNS architecture, routing, and access controls outside the script.

## Cleanup Behavior

- The Azure CLI destroy script now better reflects the private networking deployment model.
- Resource group deletion removes networking resources only when they were created inside the deployment resource group.
- Reused enterprise VNets, shared subnets, and customer-managed private DNS zones outside the deployment resource group are intentionally left in place.
- The cleanup script also removes the full set of Entra security groups created by the Azure CLI deployer, including the public workspace creation group.
