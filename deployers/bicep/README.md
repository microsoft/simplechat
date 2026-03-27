# Deploying SimpleChat with AZD

>Strongly encourage administrators to use Visual Studio Code and Dev Containers for this deployment type.

## Table of Contents</br>
- [Deployment Variables](#Deployment-Variables)
- [Prerequisites](#Prerequisites)
- [Deployment Process](#Deployment-Process)
    - [Pre-Configuration](#Pre-Configuration)
        - [Create the application registration](#Create-the-application-registration)
    - [Deployment Process](#Deployment-Process-1)
        - [Configure AZD Environment](#Configure-AZD-Environment)
        - [Deployment Prompts](#Deployment-Prompts)
    - [Post Deployment Tasks](#Post-Deployment-Tasks)
- [Cleanup / Deprovision](#Cleanup-/-Deprovisioning)
- [Helpful Info](#Helpful-Info)
    - [Private Networking](#Private-Networking)
- [Azure Government (USGov) Considerations](#Azure-Government-USGov-Considerations)
- [Frequently Asked Questions](#Frequently-Asked-Questions)
- [Troubleshooting](#Troubleshooting)

---

## Deployment Variables
The following variables will be used within this document:

- *\<appName\>* - This will become the beginning of each of the objects created.  Minimum of 3 characters, maximum of 12 characters.  No Spaces or special characters.
- *\<environment\>* - This will be used as part of the object names as well as with the AZD environments.  **Example:** *dev/qa/prod*.
- *\<cloudEnvironment\>* - Options will be *AzureCloud | AzureUSGovernment | custom*
- *\<openAIDeploymentType\>* - Azure OpenAI deployment type for default model deployments.  **Options:** *Standard | DatazoneStandard | GlobalStandard* for Azure Commercial. Use *Standard* for Azure Government.
- *\<imageName\>* - Should be presented in the form *imageName:label* **Default:** *simplechat:latest*

---

## Prerequisites

Before deploying, ensure you have:

1. **Azure Subscription** with Owner or Contributor permissions
2. **Azure CLI** (version 2.50.0 or later)
  Install: https://learn.microsoft.com/cli/azure/install-azure-cli
3. **Azure Developer CLI (azd)** (version 1.5.0 or later)
  Install: https://learn.microsoft.com/azure/developer/azure-developer-cli/install-azd
4. **Access to Azure Container Registry Tasks** so `azd up` can build the image in ACR with `az acr build`
5. **PowerShell 7** (for the Entra app registration script on Windows, Linux, or macOS)
  Install: https://learn.microsoft.com/powershell/scripting/install/installing-powershell
6. **Permissions to create an Entra ID Application Registration** (or coordinate with your Entra admin)

Platform note:

- Windows users can run the PowerShell examples directly in PowerShell.
- Linux and macOS users can run the same scripts with `pwsh`.
- If you use bash for shell commands, keep bash variable syntax in bash and invoke PowerShell scripts with `pwsh`.

### Required Azure Resource Providers
Ensure the following resource providers are registered in your subscription:
- `Microsoft.Web`
- `Microsoft.DocumentDB`
- `Microsoft.CognitiveServices`
- `Microsoft.Search`
- `Microsoft.Storage`
- `Microsoft.KeyVault`
- `Microsoft.ContainerRegistry`
- `Microsoft.Insights`
- `Microsoft.OperationalInsights`


## Deployment Process

## Runtime Startup Behavior

- This deployer publishes a **container image** to Azure App Service.
- Gunicorn is started by the container entrypoint in `application/single_app/Dockerfile`.
- Do **not** add an App Service Stack Settings Startup command for this deployer unless you intentionally change the deployment model away from containers.
- If you later switch to a native Python App Service deployment, deploy the `application/single_app` folder and use this startup command instead:

```bash
python -m gunicorn -c gunicorn.conf.py app:app
```

The below steps cover the process to deploy the Simple Chat application to an Azure Subscription.  It is assumed the user has administrative rights to the subscription for deployment.  If the user does not also have permissions to create an Application Registration in Entra, a stand-alone script can be provided to an administrator with the correct permissions.

### Pre-Configuration:

The following procedure must be completed with a user that has permissions to create an application registration in the users Entra tenant.  If this procedure is to be completed by a different user, the following files should be provided:

`./deployers/Initialize-EntraApplication.ps1`</br>
`./deployers/azurecli/appRegistrationRoles.json`

Before running the commands below, choose which shell you are using.

- PowerShell variable syntax: `$appName = "simplechat"`
- Bash variable syntax: `appName="simplechat"`

Do not use bash-style variable assignment in PowerShell. `appName = "simplechat"` is not valid PowerShell.

#### Create the application registration:

PowerShell:

```powershell
cd ./deployers
$appName = "simplechat"
$environment = "dev"
.\Initialize-EntraApplication.ps1 -AppName $appName -Environment $environment -AppRolesJsonPath "./azurecli/appRegistrationRoles.json"
```

Bash:

```bash
cd ./deployers
appName="simplechat"
environment="dev"
pwsh ./Initialize-EntraApplication.ps1 -AppName "$appName" -Environment "$environment" -AppRolesJsonPath "./azurecli/appRegistrationRoles.json"
```

This script will create an Entra Enterprise Application, with an App Registration named *\<appName\>*-*\<environment\>*-ar for the web service called *\<appName\>*-*\<environment\>*-app.  The web service name may be overriden with the `-AppServceName` parameter. A user can also specify a different expiration date for the secret which defaults to 180 days with the `-SecretExpirationDays` parameter.

>**Note**: If the script was provided to a different administrator, the -AppRolesJsonPath will need to be edited to the location of the appRegistrationRoles.json file.

The powershell script will report the following information on successful completion.  

>**Be sure to save this information as it will not be available after the window is closed.**

```========================================
App Registration Created Successfully!
========================================
Application Name:       <registered application name>
Client ID:              <clientID>
Tenant ID:              <tenantID>
Service Principal ID:   <servicePrincipalId>
Client Secret:          <clientSecret>
Secret Expiration:      <yyyy-mm-dd>
```

In addition, the script will note additional steps that must be taken for the app registration step to be completed.

1.  Grant Admin Consent for API Permissions:

    - Navigate to Azure Portal > Entra ID > App registrations
    - Find app: *\<registered application name\>*
    - Go to API permissions
    - Click 'Grant admin consent for [Tenant]'

1.  Assign Users/Groups to Enterprise Application:
    - Navigate to Azure Portal > Entra ID > Enterprise applications
    - Find app: *\<registered application name\>*
    - Go to Users and groups
    - Add user/group assignments with appropriate app roles

1.  Store the Client Secret Securely:
    - Save the client secret in Azure Key Vault or secure credential store
    - The secret value is shown above and will not be displayed again

### Deployment Process

After the application registration has been successfully completed the following deployment may begin:

#### Configure AZD Environment

You can run AZD commands from either PowerShell or bash in Visual Studio Code. The AZD commands are the same, but any shell variable assignment must match the shell you chose.

PowerShell example:

```powershell
cd ./deployers
$environment = "dev"
azd config set cloud.name AzureCloud
azd auth login
# First time in this repo with AZD, or if AZD has not been initialized in this folder yet:
azd init
azd env new $environment
azd env select $environment
azd provision --preview
azd up
```

Bash example:

```bash
cd ./deployers
environment="dev"
azd config set cloud.name AzureCloud
azd auth login
# First time in this repo with AZD, or if AZD has not been initialized in this folder yet:
azd init
azd env new "$environment"
azd env select "$environment"
azd provision --preview
azd up
```

If `deployers/azure.yaml` is already being recognized by AZD and the project has already been initialized on your machine, you can skip `azd init` and go straight to `azd env new`, `azd env select`, `azd provision --preview`, or `azd up`.

If you work with other Azure clouds, you may need to update your cloud like `azd config set cloud.name AzureUSGovernment` - more information here - [Use Azure Developer CLI in sovereign clouds | Microsoft Learn](https://learn.microsoft.com/en-us/azure/developer/azure-developer-cli/sovereign-clouds)

`cd ./deployers`

`azd config set cloud.name AzureCloud`

`az login` - this will open a browser window shta the user with Owner level permissions to the target subscription will need to authenticate with.

`azd auth login` - this will open a browser window that the user with Owner level permissions to the target subscription will need to authenticate with.

`azd init` - initialize the AZD project in the current folder if this is your first time using AZD in this repo or if the folder has not been initialized yet.

`azd env new <environment>` - Use the same value for the \<environment\> that was used in the application registration.

`azd env select <environment>` - select the new environment.

`azd provision --preview` - identify what will be deployed with the current configuration.

`azd up` - This step will begin the deployment process.  

During `azd up`, the predeploy hook now builds the application image in Azure Container Registry by using `az acr build` with `application/single_app/Dockerfile`. A local Docker daemon is no longer required for this deployment path.

#### Service Limitations of USGovCloud

> ⚠️ **Important:** Review this section carefully before deploying to Azure Government.

- **Services with cloud-specific deployment behavior in Azure Government:**
  - Azure Video Indexer - use the government ARM API profile (`2024-01-01`), which does not support the newer OpenAI integration and private endpoint properties used in Azure Commercial

- **SKU Restrictions:**
  - **GlobalStandard SKU is NOT available** - Azure OpenAI models must use `Standard` SKU instead
  - Default model deployments use `Standard` for Azure Government even if you select another `openAIDeploymentType`

- **Model Availability:**
    - Verify the `gptModels` and `embeddingModels` model names and versions are available in your target USGov region
    - Model availability may differ from Azure Commercial - check [Azure OpenAI Service models](https://learn.microsoft.com/en-us/azure/ai-services/openai/concepts/models)

- **Limited Regional Availability:**
    - ContentSafety - typically only USGov Virginia, USGov Arizona
    - SpeechService - verify feature availability (Neural voices may be limited)
    - DocumentIntelligence - prebuilt models may differ

**Example USGov Model Configuration Override:**
```json
{
  "gptModels": [
    {
      "modelName": "gpt-4o",
      "modelVersion": "2024-05-13",
      "skuName": "Standard",
      "skuCapacity": 100
    }
  ],
  "embeddingModels": [
    {
      "modelName": "text-embedding-ada-002",
      "modelVersion": "2",
      "skuName": "Standard",
      "skuCapacity": 100
    }
  ]
}
```

#### Deployment Prompts
> For each of the following parameters ensure the value noted in *\<parameter\>* matches settings as noted above.

> If you are unsure what a parameter is used for, see specific help for each parameter by entering "?" at that prompt.

- Select an Azure Subscription to use: *\<select from available list\>*
- Enter a value for the 'allowedIpAddresses' infrastructure parameter: *\<optional deployment-runner public egress IP or CIDR\>*
- Enter a value for the 'appName' infrastructure parameter: *\<appName\>*
- Enter a value for the 'authenticationType' infrastructure parameter: *\<key | managed_identity>*
- Enter a vaule for the 'cloudEnvironment' infrastructure parameter: *\<AzureCloud | AzureUSGovernment\>*
- Enter a value for the 'openAIDeploymentType' infrastructure parameter: *\<Standard | DatazoneStandard | GlobalStandard\>*
- Enter a value for the 'configureApplicationPermissions' infrastructure parameter: \<true | false\>*
- Enter a value for the 'deployContentSafety' infrastructure parameter: *\<true | false\>*
- Enter a value for the 'deployRedisCache' infrastructure parameter: *\<true | false\>*
- Enter a value for the 'deploySpeechService' infrastructure parameter: *\<true | false\>*
- Enter a value for the 'deployVideoIndexerService' infrastructure parameter: *\<true | false\>*
- Enter a value for the 'enableDiagLogging' infrastructure parameter: *\<true | false\>*
- Enter a value for the 'enablePrivateNetworking' infrastructure parameter: *\<true | false\>*
- Enter a value for the 'existingVirtualNetworkId' infrastructure parameter: *\<optional VNet resource ID\>*
- Enter a value for the 'existingAppServiceSubnetId' infrastructure parameter: *\<optional subnet resource ID for App Service VNet integration\>*
- Enter a value for the 'existingPrivateEndpointSubnetId' infrastructure parameter: *\<optional subnet resource ID for private endpoints\>*
- Enter a value for the 'privateDnsZoneConfigs' infrastructure parameter: *\<optional JSON object for reusing private DNS zones or suppressing VNet link creation\>*
- Enter a value for the 'enterpriseAppClientId' infrastructure parameter: *\<clientID\>*
- Enter a value for the 'enterpriseAppClientSecret' infrastructure secured parameter: *\<clientSecret\>*
- Enter a value for the 'enterpriseAppServicePrincipalId' infrastructure parameter: *\<servicePrincipalId\>*
- Enter a value for the 'environment' infrastructure parameter: *\<environment\>*
- Enter a value for the 'imageName' infrastructure parameter: *\<optional imageName\>*
- Enter a value for the 'location' infrastructure parameter: *\<select from the list provided\>*

`allowedIpAddresses` is optional. Leave it blank when the machine running `azd up` already has private connectivity to the deployed services through your corporate network, VPN, jump host, or build agent and can resolve the private DNS names.

`imageName` defaults to `simplechat:latest`. Most deployments can accept that default without entering a custom value.

`openAIDeploymentType` controls the default Azure OpenAI model deployment type used when this deployment creates the GPT and embedding model deployments for you. In Azure Commercial, choose `Standard`, `DatazoneStandard`, or `GlobalStandard` based on your quota and regional availability. In Azure Government, choose `Standard`.

If you provide custom `gptModels` or `embeddingModels` arrays, or if you reuse an existing Azure OpenAI endpoint, those explicit settings take precedence over `openAIDeploymentType`.

Provide a value only when private networking is enabled and the machine running `azd up` must temporarily reach Cosmos DB or Azure Container Registry over a public path during deployment. In that case, enter the public egress IP address or CIDR that Azure sees for that deployment runner. In many enterprise environments this is a company NAT or proxy address, not the laptop's local `10.x.x.x`, `172.16.x.x` to `172.31.x.x`, or `192.168.x.x` address.

If you need to identify the public egress IP for the deployment runner, use a trusted public IP lookup from that same machine and network path, for example by searching `what is my IP` in Bing.

When private networking is enabled, the preprovision validation step now attempts to detect the deployment runner public IP automatically and merge it into `ALLOWED_IP_RANGES` for the current AZD environment before provisioning starts. That lets Cosmos DB and Azure Container Registry receive the runner IP in their initial firewall rules without waiting for a later postprovision update.

Provisioning may take between 5-40 minutes depending on the options selected.

On the completion of the deployment, a URL will be presented, the user may use to access the site.

---

### Post Deployment Tasks:

Once logged in to the newly deployed application with admin credentials, review the application configuration in the Admin Settings:

1. Admin Settings > AI Models > GPT Configuration & Embeddings Configuration.  Application is pre-configured with the chosen security model (key / managed identity).  Select "Test GPT Connection" and "Test Embedding Connection" to verify connection.

1. Admin Settings > Scale > Redis Cache (if enabled) - Select "Test Redis Connection"

1. Admin Settings > Workspaces >  Multi-Modal Vision Analysis - Select "Test Vision Analysis"

1. Admin Settings > Search & Extract > Azure AI Search 
    > Known Bug:  Unable to test "Managed Identity" authentication type.  Must use "Key" for validation but application will run under Managed Identity"

    - "Authentication Type" - Key
    - "Search Key" - *Pre-populated from key vault value*.
    - At the top of the Admin Page you'll see warning boxes indicating Index Schema Mismatch.
        - Click "Create user Index"
        - Click "Create group Index"
        - Click "Create public Index"
    - Select "Test Azure AI Search Connection"

1. Search & Extract > Document Intelligence - Select "Test Document Intelligence Connection"


User should now be able to fully use Simple Chat application.

---
## Cleanup / Deprovisioning

> This is a destructive process.  Use with caution.

`cd ./deployers`</br>
`azd down --purge` - This will delete all deployed resource for this solution and purge key vault, document intelligence, OpenAI services.

---
## Helpful Info

- If Key based authentication is selected, ensure keys are rotated  per organizational requirements.

- If a deployment failure is encountered, often times, rerunning the deployment will clear the temporary error.

- When private networking is selected, `0.0.0.0` (representing Azure services) is added to the Cosmos DB firewall in addition to any IPs provided in `allowedIpAddresses`. Leave `allowedIpAddresses` blank when the deployment runner already has private connectivity and private DNS resolution through your enterprise network design. Provide it only when the deployment runner must temporarily reach Cosmos DB or Azure Container Registry from a public egress path during setup. The preprovision step now tries to auto-add the runner public IP to the AZD environment before provisioning. If you later add firewall rules manually in Azure Portal, allow up to 30 minutes for those changes to propagate before rerunning the deployment.

- When private networking is selected, the Azure Container Registry deployment enables the trusted Azure services bypass so `az acr build` can run through ACR Tasks even while the registry network rule set remains restricted. A denied ACR build that references an Azure-hosted IP such as the task agent usually means the registry was provisioned before this setting was enabled and needs to be reprovisioned.

- To evaluate any infrastructure changes between versions, with AZD the user can run:
`azd provision --preview` 

### Private Networking

When private networking is configured, access from the developers workstation to push updates and new Azure configurations will be blocked.  In addition, testing the web application when not on a VPN attached to the private network subnet is expected to be blocked.

For enterprise deployments, focus on the machine running `azd up`, not just the user laptop. If that deployment runner is inside the private network path and can resolve the private endpoints, `allowedIpAddresses` is typically not needed. If the deployment runner is outside that private path and must temporarily reach protected services over the internet, provide the runner's public egress IP or CIDR.

#### Existing VNet Prerequisites

If you enable private networking and choose to reuse an existing VNet, the deployment assumes the network prerequisites are already in place.

- Provide `existingVirtualNetworkId` only when you want to reuse an existing VNet.
- When `existingVirtualNetworkId` is provided, you must also provide both `existingAppServiceSubnetId` and `existingPrivateEndpointSubnetId`.
- The template does not create subnets inside an existing customer-managed VNet.
- The App Service integration subnet must already exist and be prepared for App Service regional VNet integration, including delegation to `Microsoft.Web/serverFarms`.
- The private endpoint subnet must already exist and be intended for private endpoints for the Azure services you enable.
- The existing VNet and subnets should be reachable and approved under your organization's network design, including any cross-resource-group or cross-subscription access requirements.

#### Private DNS Zone Guidance

Private DNS is required for reliable name resolution when private endpoints are enabled.

- If you leave `privateDnsZoneConfigs` empty, the deployment creates the required private DNS zones in the deployment resource group and links them to the VNet automatically.
- If your organization already manages private DNS centrally, provide `privateDnsZoneConfigs` with one or more `zoneResourceId` values to reuse those existing zones.
- Set `createVNetLink` to `false` only when the DNS zone is already linked to the target VNet or when your networking team will manage the VNet link separately.
- If you reuse an existing VNet but do not create or link the required private DNS zones, the application may deploy successfully but private name resolution to services such as Cosmos DB, Storage, Azure AI Search, Azure OpenAI, Key Vault, and App Service private endpoints will fail.

Example `privateDnsZoneConfigs` value:

```json
{
  "openAi": {
    "zoneResourceId": "/subscriptions/<subId>/resourceGroups/<dns-rg>/providers/Microsoft.Network/privateDnsZones/privatelink.openai.azure.com",
    "createVNetLink": true
  },
  "cosmosDb": {
    "zoneResourceId": "/subscriptions/<subId>/resourceGroups/<dns-rg>/providers/Microsoft.Network/privateDnsZones/privatelink.documents.azure.com",
    "createVNetLink": false
  }
}
```

Supported `privateDnsZoneConfigs` keys: `keyVault`, `cosmosDb`, `containerRegistry`, `aiSearch`, `blobStorage`, `cognitiveServices`, `openAi`, and `webSites`.

During initial deployment, if post an error is raised "failed running post hooks: 'postprovision'" the deployment is being blocked from executing scripts against the CosmosDB service. Ensure the deployment workstation IP address is added to the `allowedIpAddresses` parameter or the `ALLOWED_IP_RANGES` AZD environment value. Similar messages may be seen from the Azure Container Registry service. If you add the firewall rule manually in Azure Portal, wait up to 30 minutes for propagation before rerunning `azd up`.

If `az acr build` fails with `denied: client with IP '<address>' is not allowed access`, adding the workstation IP usually does not help because the denied address is commonly the Azure Container Registry Tasks worker, not the local machine. In that case, ensure the registry allows trusted Azure services and reprovision the registry configuration.

When private networking is enabled, to test the web applicaiton, users may configure a VPN into the deployed vNet (space is provided for this) or the administration may adjust the networking limitations to the deployed website.  This may be accomplished with the following script:

`az webapp update --name <appName>-<environment>-app --resource-group <appName>-<environment>-rg --public-network-access Enabled;`

To permit redeployment of Azure infrastructure services, the following script may be used to enable access when private networking is enabled.

```
az cosmosdb update --name <appName>-<environment>-cosmos --resource-group <appName>-<environment>-rg --public-network-access enabled
az keyvault update --name <appName>-<environment>-kv --resource-group <appName>-<environment>-rg --public-network-access enabled 
az acr update --name <appName><environment>acr --resource-group <appName>-<environment>-rg --public-network-enabled true
az resource update --name <appName>-<environment>-app --resource-group <appName>-<environment>-rg --resource-type "Microsoft.Web/sites" --set properties.publicNetworkAccess=Enabled
```

---

## Azure Government (USGov) Considerations

### Services Deployed

| Service | Azure Commercial | Azure Government | Notes |
|---------|------------------|------------------|-------|
| App Service | ✅ | ✅ | Premium V3 tier |
| Cosmos DB | ✅ | ✅ | Serverless mode |
| Azure OpenAI | ✅ | ✅ | Standard SKU only in USGov |
| Azure AI Search | ✅ | ✅ | Basic tier |
| Document Intelligence | ✅ | ✅ | Limited regions |
| Storage Account | ✅ | ✅ | Standard LRS |
| Key Vault | ✅ | ✅ | Standard tier |
| Container Registry | ✅ | ✅ | Basic tier |
| Application Insights | ✅ | ✅ | |
| Log Analytics | ✅ | ✅ | |
| Content Safety | ✅ | ⚠️ Limited | Not all regions |
| Speech Service | ✅ | ⚠️ Limited | Feature restrictions |
| Video Indexer | ✅ | ✅ Limited | Azure Government uses the `2024-01-01` ARM API profile; newer OpenAI integration and private endpoint properties remain commercial/custom-cloud only |
| Redis Cache | ✅ | ✅ | Standard tier |

### Endpoint Differences

The deployment automatically handles the following endpoint differences:
- ACR Domain: `.azurecr.io` → `.azurecr.us`
- Entra Login: `login.microsoftonline.com` → `login.microsoftonline.us`
- OpenID Issuer: `sts.windows.net` → `login.microsoftonline.us`
- Private DNS Zones: Automatically configured for USGov

---

## Frequently Asked Questions

### General Questions

**Q: How long does deployment take?**
A: Initial deployment typically takes 15-40 minutes depending on options selected. Subsequent deployments are faster.

**Q: What Azure permissions do I need?**
A: You need Owner or Contributor role on the target subscription, plus ability to create Entra ID app registrations (or work with your Entra admin).

**Q: Can I deploy to an existing resource group?**
A: No, the deployment creates a new resource group named `<appName>-<environment>-rg`.

**Q: What is the default authentication type?**
A: You can choose between `key` (API keys stored in Key Vault) or `managed_identity` (recommended for production).

### Model Configuration

**Q: How do I customize which GPT models are deployed?**
A: Override the `gptModels` parameter with your desired configuration:
```json
[
  {
    "modelName": "gpt-4o",
    "modelVersion": "2024-11-20",
    "skuName": "GlobalStandard",
    "skuCapacity": 100
  }
]
```

**Q: What's the difference between GlobalStandard, DatazoneStandard, and Standard SKU?**
A: `GlobalStandard` uses Azure's global AI infrastructure, `DatazoneStandard` uses the regional data zone option when available, and `Standard` is region-specific. Availability and quota can differ by region and subscription. Azure Government deployments should use `Standard`.

### Networking

**Q: Can I deploy without private networking initially and add it later?**
A: Yes, set `enablePrivateNetworking` to `false` initially. You can enable it later but this requires re-running the deployment.

**Q: Why do I need to add my IP address to allowedIpAddresses?**
A: You only need to provide `allowedIpAddresses` when the machine running `azd up` must temporarily reach Cosmos DB or Azure Container Registry over a public network path during deployment. If your deployment runner is already on a private corporate network, VPN, jump host, or build agent with private connectivity and private DNS resolution to those services, leave the value blank.

**Q: Which IP address should I provide if I do need it?**
A: Provide the public egress IP address or CIDR that Azure sees for the machine running `azd up`. In enterprise environments this is often a company NAT or proxy address rather than the laptop's local private address. A simple way to identify it is to use a trusted public IP lookup from that same machine and network path, for example by searching `what is my IP` in Bing.

**Q: What do I need before selecting an existing VNet?**
A: You need an existing VNet plus both an App Service integration subnet and a private endpoint subnet. The deployment does not create subnets in a reused VNet.

**Q: What happens if I leave privateDnsZoneConfigs empty?**
A: The deployment creates the supported private DNS zones in the deployment resource group and creates VNet links automatically.

**Q: When should I set createVNetLink to false?**
A: Only when the DNS zone is already linked to the target VNet or when a central networking team manages those links outside this deployment.

### Costs

**Q: What's the estimated monthly cost?**
A: Base infrastructure (without optional services) costs approximately:
- App Service Plan (P1v3): ~$150/month
- Cosmos DB (Serverless): Pay-per-request
- Azure OpenAI: Pay-per-token
- Azure AI Search (Basic): ~$70/month
- Other services: Variable based on usage

### Upgrading

**Q: How do I upgrade to a new version?**
A: For **code-only** container updates, prefer `azd deploy`. Use `azd provision --preview` and then `azd up` only when the release also changes infrastructure. See [../../docs/how-to/upgrade_paths.md](../../docs/how-to/upgrade_paths.md) for the upgrade decision guide.

---

## Troubleshooting

### Common Deployment Errors

**Error: "failed running post hooks: 'postprovision'"**
- **Cause:** Deployment scripts cannot access Cosmos DB or other services
- **Solution:** If the deployment runner is outside the private network path, add its public egress IP or CIDR to `allowedIpAddresses` and redeploy. If the deployment runner is already on the private network path, verify private DNS resolution and routing to the private endpoints instead of adding a public IP.

**Error: "The subscription is not registered to use namespace 'Microsoft.CognitiveServices'"**
- **Cause:** Required resource provider not registered
- **Solution:** Run `az provider register --namespace Microsoft.CognitiveServices`

**Error: "Quota exceeded for deployment"**
- **Cause:** Azure OpenAI quota limits reached
- **Solution:** Try a different `openAIDeploymentType`, request quota increase, or reduce `skuCapacity` in custom model configuration. Then rerun `azd up`.

If you do not want this deployment to create new Azure OpenAI model deployments, rerun with an existing Azure OpenAI endpoint and complete the remaining model configuration manually in Simple Chat after deployment. See `docs/setup_instructions_manual.md` and `docs/admin_configuration.md` for the manual steps.

**Error: "InvalidTemplateDeployment - GlobalStandard SKU not available"**
- **Cause:** Attempting USGov deployment with GlobalStandard SKU
- **Solution:** Use `Standard` SKU for all models in Azure Government

**Error: "Resource 'Microsoft.VideoIndexer/accounts' not found"**
- **Cause:** Video Indexer API capabilities differ by cloud and region
- **Solution:** Use the cloud-appropriate API profile. Azure Government deployments use the `2024-01-01` profile; commercial deployments use `2025-04-01`; custom clouds can override the API version and endpoint.

### Post-Deployment Issues

**Issue: Cannot access the web application**
- Verify the Entra app registration is configured correctly
- Check that admin consent was granted for API permissions
- Ensure users are assigned to the enterprise application

**Issue: "Test Connection" fails in Admin Settings**
- For Managed Identity: Wait 5-10 minutes for role assignments to propagate
- For Key Authentication: Verify secrets exist in Key Vault
- Check Application Insights for detailed error logs

**Issue: AI Search shows "Index Schema Mismatch"**
- This is expected on first deployment
- Click "Create user Index", "Create group Index", "Create public Index" in Admin Settings

### Logs and Diagnostics

Enable diagnostic logging by setting `enableDiagLogging` to `true`. Logs are sent to:
- Log Analytics Workspace: `<appName>-<environment>-logs`
- Application Insights: `<appName>-<environment>-ai`

View application logs:
```bash
az webapp log tail --name <appName>-<environment>-app --resource-group <appName>-<environment>-rg
```


