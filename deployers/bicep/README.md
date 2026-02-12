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
- *\<cloudEnvironment\>* - Options will be *AzureCloud | AzureUSGovernment*
- *\<imageName\>* - Should be presented in the form *imageName:label* **Example:** *simple-chat:latest*

---

## Prerequisites

Before deploying, ensure you have:

1. **Azure Subscription** with Owner or Contributor permissions
2. **Azure CLI** (version 2.50.0 or later)
3. **Azure Developer CLI (azd)** (version 1.5.0 or later)
4. **Docker** installed and running (for container builds)
5. **PowerShell** (for the Entra app registration script)
6. **Permissions to create an Entra ID Application Registration** (or coordinate with your Entra admin)

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

The below steps cover the process to deploy the Simple Chat application to an Azure Subscription.  It is assumed the user has administrative rights to the subscription for deployment.  If the user does not also have permissions to create an Application Registration in Entra, a stand-alone script can be provided to an administrator with the correct permissions.

### Pre-Configuration:

The following procedure must be completed with a user that has permissions to create an application registration in the users Entra tenant.  If this procedure is to be completed by a different user, the following files should be provided:

`./deployers/Initialize-EntraApplication.ps1`</br>
`./deployers/azurecli/appRegistrationRoles.json`

#### Create the application registration:

`cd ./deployers`</br>
`.\Initialize-EntraApplication.ps1 -AppName "<appName>" -Environment "<environment>"  -AppRolesJsonPath "./azurecli/appRegistrationRoles.json"`

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

Using the bash terminal in Visual Studio Code

`cd ./deployers`

`azd config set cloud.name AzureCloud` - If you work with other Azure clouds, you may need to update your cloud like `azd config set cloud.name AzureUSGovernment` - more information here - [Use Azure Developer CLI in sovereign clouds | Microsoft Learn](https://learn.microsoft.com/en-us/azure/developer/azure-developer-cli/sovereign-clouds)

`az login` - this will open a browser window shta the user with Owner level permissions to the target subscription will need to authenticate with.

`azd auth login` - this will open a browser window that the user with Owner level permissions to the target subscription will need to authenticate with.

`azd env new <environment>` - Use the same value for the \<environment\> that was used in the application registration.

`azd env select <environment>` - select the new environment.

`azd provision --preview` - identify what will be deployed with the current configuration.

`azd up` - This step will begin the deployment process.  

#### Service Limitations of USGovCloud

> ⚠️ **Important:** Review this section carefully before deploying to Azure Government.

- **Services NOT available in Azure Government:**
    - Azure Video Indexer - Set `deployVideoIndexerService` to `false`

- **SKU Restrictions:**
    - **GlobalStandard SKU is NOT available** - Azure OpenAI models must use `Standard` SKU instead
    - Default deployment uses `GlobalStandard` - override `gptModels` and `embeddingModels` parameters

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
- Enter a value for the 'allowedIpAddresses' infrastructure parameter: *\<ipAddressList\>*
- Enter a value for the 'appName' infrastructure parameter: *\<appName\>*
- Enter a value for the 'authenticationType' infrastructure parameter: *\<key | managed_identity>*
- Enter a vaule for the 'cloudEnvironment' infrastructure parameter: *\<AzureCloud | AzureUSGovernment\>*
- Enter a value for the 'configureApplicationPermissions' infrastructure parameter: \<true | false\>*
- Enter a value for the 'deployContentSafety' infrastructure parameter: *\<true | false\>*
- Enter a value for the 'deployRedisCache' infrastructure parameter: *\<true | false\>*
- Enter a value for the 'deploySpeechService' infrastructure parameter: *\<true | false\>*
- Enter a value for the 'deployVideoIndexerService' infrastructure parameter: *\<true | false\>*
- Enter a value for the 'enableDiagLogging' infrastructure parameter: *\<true | false\>*
- Enter a value for the 'enablePrivateNetworking' infrastructure parameter: *\<true | false\>*
- Enter a value for the 'enterpriseAppClientId' infrastructure parameter: *\<clientID\>*
- Enter a value for the 'enterpriseAppClientSecret' infrastructure secured parameter: *\<clientSecret\>*
- Enter a value for the 'enterpriseAppServicePrincipalId' infrastructure parameter: *\<servicePrincipalId\>*
- Enter a value for the 'environment' infrastructure parameter: *\<environment\>*
- Enter a value for the 'imageName' infrastructure parameter: *\<imageName\>*
- Enter a value for the 'location' infrastructure parameter: *\<select from the list provided\>*

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

- When private networking is selected, 0.0.0.0 (representing the internal Azure Services) is added to the CosmosDB firewall in addition to any IP's added to the 'allowedIpAddresses' parameter.  Users are encouraged to include the IP address of the deployment server in the 'allowedIpAddresses.  This becomes not-applicable on completion of the deployment when CosmosDB, Key Vault, Azure Container Registry and the Web Application is configured for private networking only.  If the 'allowedIpAddresses parameter is not used, the administrator can manually add in the deployment server IP address to the Settings > Networking section of the coresponding service(s) and rerun the deployment.

- To evaluate any infrastructure changes between versions, with AZD the user can run:
`azd provision --preview` 

### Private Networking

When private networking is configured, access from the developers workstation to push updates and new Azure configurations will be blocked.  In addition, testing the web application when not on a VPN attached to the private network subnet is expected to be blocked.

During initial deployment, if post an error is raised "failed running post hooks: 'postprovision'" the deployment is being blocked from executing scripts against the CosmosDB service.  Ensure the deployment workstation IP address is added to the "allowedIPAddresses" parameter.  Similar messages may be seen from the Azure Container Registry Service.

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
| Video Indexer | ✅ | ❌ Not Available | |
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

**Q: What's the difference between GlobalStandard and Standard SKU?**
A: `GlobalStandard` provides access to Azure's global AI infrastructure with higher availability but is not available in Azure Government. `Standard` is region-specific and is required for USGov deployments.

### Networking

**Q: Can I deploy without private networking initially and add it later?**
A: Yes, set `enablePrivateNetworking` to `false` initially. You can enable it later but this requires re-running the deployment.

**Q: Why do I need to add my IP address to allowedIpAddresses?**
A: During deployment, scripts need to access Cosmos DB and other services. Your IP must be allowed through the firewall temporarily.

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
A: Run `azd up` again from the updated codebase. Use `azd provision --preview` to review changes first.

---

## Troubleshooting

### Common Deployment Errors

**Error: "failed running post hooks: 'postprovision'"**
- **Cause:** Deployment scripts cannot access Cosmos DB or other services
- **Solution:** Add your IP address to the `allowedIpAddresses` parameter and redeploy

**Error: "The subscription is not registered to use namespace 'Microsoft.CognitiveServices'"**
- **Cause:** Required resource provider not registered
- **Solution:** Run `az provider register --namespace Microsoft.CognitiveServices`

**Error: "Quota exceeded for deployment"**
- **Cause:** Azure OpenAI quota limits reached
- **Solution:** Request quota increase or reduce `skuCapacity` in model configuration

**Error: "InvalidTemplateDeployment - GlobalStandard SKU not available"**
- **Cause:** Attempting USGov deployment with GlobalStandard SKU
- **Solution:** Use `Standard` SKU for all models in Azure Government

**Error: "Resource 'Microsoft.VideoIndexer/accounts' not found"**
- **Cause:** Video Indexer not available in region (especially USGov)
- **Solution:** Set `deployVideoIndexerService` to `false`

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


