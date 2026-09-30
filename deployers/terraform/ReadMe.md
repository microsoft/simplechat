# Simple Chat - Deployment using Terraform

[Return to Main](../../README.md)

## Login to Azure CLI

```azurecli
az cache purge
az account clear
az cloud set --name AzureUSGovernment
az login --scope https://management.core.usgovcloudapi.net//.default --service-principal --username @SERVICE_PRINCIPAL_USERNAME --password @SERVICE_PRINCIPAL_PASSWORD --tenant @AZURE_TENANT_ID
az login --scope https://graph.microsoft.us//.default --service-principal --username @SERVICE_PRINCIPAL_USERNAME --password @SERVICE_PRINCIPAL_PASSWORD> --tenant @AZURE_TENANT_ID
az account set -s '@AZURE_SUBSCRIPTION_ID'
```

`global_which_azure_platform` now accepts `AzureCloud`, `AzureUSGovernment`, and `Custom`.

- `AzureCloud` deploys the commercial Video Indexer profile (`2025-04-01`).
- `AzureUSGovernment` deploys the government Video Indexer profile (`2024-01-01`).
- `Custom` currently supports custom runtime settings for Video Indexer, but Terraform blocks Video Indexer resource provisioning until provider-level custom cloud support is validated.

## Execute Initalize-AzureEnvironment.ps1

After logging into the target Azure subscription, execute the Initalize-AzureEnvironment.ps1 script.  This will configure items not set in the terraform script but is required for the remaining deployment steps.

```powershell
Initialize-AzureEnvironment.ps1 -ResourceGroupName "myResourceGroup" -AzureRegion "eastus" -ACRName "myACR" -OpenAiName "myOpenAI"
```

## Important Terraform Scope Notes

This Terraform deployer now supports the same core private networking flow as the Bicep deployer for these scenarios:

- Create a new VNet with the required App Service integration and private endpoint subnets.
- Reuse an existing VNet by supplying existing subnet resource IDs.
- Create private endpoints for Key Vault, Cosmos DB, Storage, Azure AI Search, Azure OpenAI, Document Intelligence, Container Registry, and the App Service.
- Create private DNS zones automatically, or reuse existing private DNS zones by resource ID.
- Create VNet links for each private DNS zone unless you explicitly opt out per zone.

The same OpenAI limitation still applies as in Bicep: endpoint-only reuse is valid for application configuration, but Terraform can only automate the Azure OpenAI private endpoint when it has Azure resource metadata from either a newly created OpenAI resource or an existing standard Azure OpenAI resource name/resource group.

If you plan to reuse enterprise-managed networking, make sure these prerequisites already exist:

- An existing VNet with separate subnets for App Service VNet integration and private endpoints
- Delegation of the App Service integration subnet to `Microsoft.Web/serverFarms`
- Required private DNS zones for services such as App Service, Cosmos DB, Storage, AI Search, Azure OpenAI, and Cognitive Services
- Correct VNet links for each required private DNS zone

For detailed networking guidance, see:

- [../bicep/README.md](../bicep/README.md)
- [../../docs/guides/enterprise-networking.md](../../docs/guides/enterprise-networking.md)

## Configure Terraform Secrets
 
Create a terraform.tfvars: Create a terraform.tfvars file (or provide via environment variables) for sensitive variables like ACR credentials:

```hcl
ACR_LOGIN_SERVER = "your_acr_servername"
ACR_USERNAME = "your_acr_username"
ACR_PASSWORD = "your_acr_password"

# Optionally override other defaults
# param_tenant_id = "your-actual-tenant-id"
# param_location = "usgovvirginia"
# param_search_sku = "standard"                       # Default: Standard S1. Use "free" only for short-lived MVP/evaluation.
# param_search_semantic_search_sku = "standard"       # Default: standard Semantic Ranker.
# param_cosmos_capacity_mode = "provisioned"          # Default: provisioned throughput. Use "serverless" only for short-lived MVP/evaluation.
# param_cosmos_autoscale_max_throughput = 1000        # Per-container autoscale max RU/s when Cosmos capacity mode is provisioned.
```

Terraform defaults to Azure AI Search Standard S1 with standard Semantic Ranker and Cosmos DB provisioned dedicated container autoscale throughput. Free Search and serverless Cosmos DB remain configurable for short-lived MVP phases, but they are not the repository defaults because they can hit semantic query, indexing, or request-unit limits during document-heavy testing.

Terraform also assigns the application managed identity the `SimpleChat Cosmos Throughput Operator` custom role on the deployed Cosmos account. It is limited to Cosmos account/database/container throughput discovery and mutation, throughput-operation reads, autoscale migration operations, and metrics reads; it does not replace Cosmos DB data-plane permissions. The optional Data Management source backup boost is capped at 10,000 RU/s and restores the captured capacity after completion, cancellation, failure, or durable recovery. Review the additional Cosmos cost before enabling it. Serverless, unsupported shared/dedicated throughput layouts, and capacity already above 10,000 RU/s remain portal-managed.

## Key Vault secret-management permissions

Implemented in application version **0.261.125** (`application/single_app/config.py`) and deployer version **1.0.32** (`deployers/version.txt`). Use Terraform **1.12.0 or later**, as required by `main.tf`.

This deployer uses Key Vault RBAC and grants **Key Vault Secrets Officer**, built-in role ID `b86a8fe4-44ce-4948-aee5-eccb2c155cd7`, at the **vault scope** to both supported application identities:

| Terraform resource | Runtime identity |
|---|---|
| `azurerm_role_assignment.kv_secrets_officer_app_service` | App Service **system-assigned** principal, used when the application's Key Vault client ID is blank and no credential override is configured |
| `azurerm_role_assignment.kv_secrets_officer_managed_identity` | The user-assigned identity attached by this deployment, used when its client ID is selected in the application's Key Vault settings |

The app has both identities attached; the template does not set an `AZURE_CLIENT_ID` override. Use a user-assigned identity's **client ID** to select it in the application, but its **principal/object ID** when checking IAM. The separate `kv_secrets_officer_current_user` grant is for the deploying user/service principal and is not a substitute for either runtime grant.

**Key Vault Secrets User** only allows reading secrets. Saving application credentials and running the write/read/delete connection probe require secret-management access, including get/list/set/delete. Officer supplies these operations without granting control over vault RBAC. Do not move the application assignments to resource-group or subscription scope. For a manually managed or code-only upgrade, assign Officer to the selected runtime identity under the vault's **Access control (IAM)**, leaving existing grants intact. This Terraform path does not configure legacy access policies; the Azure CLI deployer supports that mode.

### State migration and existing Officer assignments

The old `kv_secrets_user_managed_identity` resource is declared in a `removed` block with `destroy = false`. An upgrade forgets that read-only assignment from Terraform state **without deleting it in Azure**, and the new Officer resources have separate addresses. Do not move the old Secrets User state to an Officer resource: changing its role would require replacement of an immutable Azure assignment.

Terraform cannot discover and adopt an equivalent manually created grant automatically. Before planning an upgrade, inspect Officer assignment metadata for the vault and each runtime principal:

```powershell
$vaultId = az keyvault show --name "<vault-name>" --resource-group "<resource-group>" --query id --output tsv
$officerRoleId = "b86a8fe4-44ce-4948-aee5-eccb2c155cd7"
az role assignment list --scope $vaultId --role $officerRoleId `
    --fill-principal-name false --fill-role-definition-name false `
    --query "[].{id:id,principalId:principalId,scope:scope,condition:condition}" --output json
```

Compare the returned principal IDs with **App Service > Identity** and the deployed user-assigned identity's overview. Only import an unconditional Officer assignment for that principal at the exact vault scope. An inherited grant, a secret-level grant, or the deploying administrator's grant is not the same resource. Conditional grants need administrator review.

For each existing manual runtime grant, back up your Terraform state and import its **full role-assignment resource ID** into the corresponding new address. Run from `deployers\terraform`, using your normal variables file or `TF_VAR_*` environment:

```powershell
$systemOfficerAssignmentId = "<vault-resource-id>/providers/Microsoft.Authorization/roleAssignments/<system-officer-assignment-guid>"
$userOfficerAssignmentId = "<vault-resource-id>/providers/Microsoft.Authorization/roleAssignments/<user-officer-assignment-guid>"
terraform import -var-file=".\params\production.tfvars" azurerm_role_assignment.kv_secrets_officer_app_service $systemOfficerAssignmentId
terraform import -var-file=".\params\production.tfvars" azurerm_role_assignment.kv_secrets_officer_managed_identity $userOfficerAssignmentId
```

Import only assignments that already exist and are not already managed at the intended address. Assignment names are intentionally left provider-managed so an imported GUID remains stable instead of forcing replacement. If a grant is already tracked under another Terraform address, coordinate its state ownership rather than importing the same grant twice.

Review the next plan: the old User grant should be forgotten, not destroyed; imported Officer grants should not be replaced; missing Officer grants should be added. Keep manual grants rather than deleting them to work around `RoleAssignmentExists`. Neither an import nor these instructions authorizes applying an unreviewed infrastructure plan.

After a reviewed deployment and RBAC propagation, test the chosen identity under **Admin Settings > Secrets**. The probe uses a synthetic temporary secret and deletes it afterward; soft-deleted metadata may remain under vault retention. Network restrictions still apply independently of IAM.

Offline coverage in [test_deployer_key_vault_secret_permissions.py](../../functional_tests/test_deployer_key_vault_secret_permissions.py) checks both runtime assignments, vault scopes, and the non-destructive legacy state migration.

## Deploy initial container

Terraform does not build the container image itself. It expects `image_name` to point to an image tag that already exists in your Azure Container Registry.

Recommended options:

1. Build directly in ACR with Azure CLI:

```azurecli
az acr build --registry <acr-name> --file application/single_app/Dockerfile --image simple-chat:latest .
```

2. Use the repository's GitHub Actions image publish workflow if that matches your release process.

If you use `az acr build`, run it from the repository root so the Docker build context includes the files referenced by `application/single_app/Dockerfile`.

## Upgrading

- For **code-only** container updates, publish a new image to ACR and follow the existing App Service container rollout process instead of rerunning Terraform for every release.
- Use Terraform when you are intentionally changing infrastructure or configuration that belongs in Terraform state.
- See [../../docs/guides/upgrade-paths.md](../../docs/guides/upgrade-paths.md) for the native-vs-container upgrade guide and the ACR/image-only rollout notes.

## Terraform deployment

Initialize: Run terraform init to download the necessary providers.
Plan: Run terraform plan to see the resources that will be created.
Apply: Run terraform apply to provision the resources.

Login to Azure CLI (See instructions above)
terraform init
terraform init -upgrade

### .tfvars

#### Azure Environment Variables

global_which_azure_platform = "AzureUSGovernment"
param_tenant_id = "6bc5b33e-bc05-493c-b076-8f8ce1331511"
param_subscription_id = "4c1ccd07-9ebc-4701-b87f-c249066e0911"
param_location = "usgovvirginia"

#### ACR Variables

acr_name = "acr8000"
acr_resource_group_name = "sc-emma1-sbx1-rg"
acr_username = "acr8000"
acr_password = "@YOUR_ACR_PASSWORD"
image_name = "simplechat:latest"

#### SimpleChat Variables

param_environment = "sbx"
param_base_name = "rudy1"

#### Open AI Variables

param_use_existing_openai_instance = true
param_existing_azure_openai_resource_name = "gregazureopenai1"
param_existing_azure_openai_resource_group_name = "azureopenairg"
param_deploy_video_indexer_service = true
param_existing_azure_openai_subscription_id = "00000000-0000-0000-0000-000000000000"
# Optional endpoint override for existing Azure OpenAI or Azure AI Foundry-compatible endpoints
# param_existing_azure_openai_endpoint = "https://my-openai-resource.openai.azure.com/"

#### Private Networking Variables

param_enable_private_networking = true

# Option 1: let Terraform create the VNet and required subnets
# param_existing_virtual_network_id = ""
# param_existing_app_service_subnet_id = ""
# param_existing_private_endpoint_subnet_id = ""

# Option 2: reuse an existing VNet and existing subnets
# param_existing_virtual_network_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/network-rg/providers/Microsoft.Network/virtualNetworks/enterprise-vnet"
# param_existing_app_service_subnet_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/network-rg/providers/Microsoft.Network/virtualNetworks/enterprise-vnet/subnets/AppServiceIntegration"
# param_existing_private_endpoint_subnet_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/network-rg/providers/Microsoft.Network/virtualNetworks/enterprise-vnet/subnets/PrivateEndpoints"

# Optional: override the default address ranges used when Terraform creates the VNet
# param_private_network_address_space = ["10.0.0.0/21"]
# param_app_service_integration_subnet_prefixes = ["10.0.0.0/24"]
# param_private_endpoint_subnet_prefixes = ["10.0.2.0/24"]

# Optional: reuse customer-managed private DNS zones per service
# create_vnet_link defaults to true
# param_private_dns_zone_configs = {
#   openAi = {
#     zone_resource_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/dns-rg/providers/Microsoft.Network/privateDnsZones/privatelink.openai.azure.com"
#     create_vnet_link = false
#   }
#   webSites = {
#     zone_resource_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/dns-rg/providers/Microsoft.Network/privateDnsZones/privatelink.azurewebsites.net"
#   }
# }

#### Other Settings Variables

param_resource_owner_id = "Tom Jones"
param_resource_owner_email_id = "tom@somedomain.onmicrosoft.us"
param_create_entra_security_groups = true

### How to deploy with tfvars file

terraform plan -var-file="./params/rudy1.tfvars"
terraform apply -var-file="./params/rudy1.tfvars" -auto-approve
terraform destroy -var-file="./params/rudy1.tfvars" -auto-approve

## Post-Deployment Manual Steps

### Private Networking Notes

- If `param_enable_private_networking = true` and you supply any existing VNet or subnet IDs, supply **both** `param_existing_app_service_subnet_id` and `param_existing_private_endpoint_subnet_id`.
- If you reuse private DNS zones, use full resource IDs in `param_private_dns_zone_configs`.
- If a central networking team already manages the VNet links for a reused zone, set `create_vnet_link = false` for that zone.
- The App Service private endpoint uses the `sites` subresource and the web app itself is configured with public network access disabled when private networking is enabled.

### Existing Azure OpenAI Notes

- If you reuse an existing standard Azure OpenAI resource in another subscription, set `param_existing_azure_openai_subscription_id` so Terraform can look up that resource correctly.
- If you provide only `param_existing_azure_openai_endpoint` without a resource name and resource group, Terraform will use that endpoint for application configuration but will **not** create RBAC assignments against the OpenAI resource.
- Endpoint-only reuse is suitable for cases where the endpoint is externally managed, but managed identity permissions and Azure OpenAI private endpoint automation must then be handled outside this Terraform deployment.

STEP 1) Configure Azure Search indexes:
Deploy index as json files to Azure Search: ai_search-index-group.json, ai_search-index-user.json via the portal.

STEP 2) Navigate to Web UI url in a browser.

In the web ui, click on "Admin" > "app settings" to configure your app settings.

**NOTE:** Azure AI Foundry-compatible endpoints are supported for application configuration, but endpoint-only reuse does not give Terraform enough Azure resource metadata to automate RBAC or private endpoint integration. If you use an endpoint-only configuration, complete any required managed identity permissions and network isolation steps outside this Terraform deployment.

STEP 3) Test Web UI fully.
