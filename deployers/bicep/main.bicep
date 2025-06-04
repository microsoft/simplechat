/*
===============================================================================
  File:        main.bicep
  Description: BICEP deployment script for Azure resources related to a simple chat application.
  Author:      Microsoft Federal
  Created:     2025-May-15
  Version:     <v1.0.0>
===============================================================================

  Notes:
    - Currently supports Azure US Government only.
    - Is extensible to Azure Commercial with minor adjustments.

  Disclaimer:
    - This script is provided as-is and is not officially supported by Microsoft.
    - It is intended for educational purposes and may require modifications to fit specific use cases.
    - Ensure you have the necessary permissions and configurations in your Azure environment before deploying.

=============================================================================== 
*/


/* PARAMETERS
=============================================================================== */
@description('Specifies the Azure environment platform.')
@allowed([
  'AzureCloud'
  'AzureUSGovernment'
])
param azurePlatform string = 'AzureUSGovernment'

@description('Tenant ID where the resources are deployed and for App Registration.')
param tenantId string = subscription().tenantId

@minLength(1)
@maxLength(90)
@description('Primary Azure region for deployments.')
param location string = resourceGroup().location

@minLength(3)
@maxLength(24)
@description('A persons name for tagging resources. e.g. John Doe or johndoe@domain.com')
param resourceOwnerId string

@minLength(3)
@maxLength(3)
@allowed([
  'sbx'
  'dev'
  'tst'
  'uat'
  'prd'
])
@description('Environment identifier (e.g. sbx, dev, tst, uat, prd).')
param environment string = 'sbx'

@minLength(1)
@maxLength(8)
@description('A short base name (1-8 alphanumeric characters) for your organization or project (e.g., contoso1, projectx2). Used to construct resource names.')
param baseName string

@minLength(5)
@maxLength(50)
@description('Name of the existing Azure Container Registry (ACR). e.g. contosoacr1')
param acrName string

@minLength(1)
@maxLength(90)
@description('Name of the existing Resource Group housing Azure Container Registry (ACR).')
param acrResourceGroupName string

@description('Full image name and tag from ACR (e.g., simple-chat:2025-05-15_7).')
param imageName string

@description('Flag to determine if an existing Azure OpenAI instance should be used.')
param useExistingOpenAiInstance bool = true

@description('Name of the existing Azure OpenAI resource. Required if useExistingOpenAiInstance is true.')
param existingAzureOpenAiResourceName string = ''

@description('Resource group name of the existing Azure OpenAI resource. Required if useExistingOpenAiInstance is true.')
param existingAzureOpenAiResourceGroupName string = ''

// --- Entra App Registration Parameters (MUST BE CREATED MANUALLY FIRST) ---
@description('Client ID (Application ID) of the pre-created Entra App Registration.')
param appRegistrationClientId string

@description('A client secret from the pre-created Entra App Registration.')
@secure()
param appRegistrationClientSecret string

// Optional: Object ID of the Service Principal for the App Registration if RBAC needs to be assigned to it.
// If the app registration was just created, its SP might take a few minutes to replicate.
@description('Object ID of the Service Principal for the App Registration (used for RBAC, e.g., to OpenAI). Obtain via "az ad sp show --id <appRegistrationClientId> --query id -o tsv"')
param appRegistrationSpObjectId string = ''

// --- SKU Parameters (as in PowerShell script) ---
@description('SKU for the App Service Plan.')
param appServicePlanSku string = 'P1V3' // For Linux, ensure this SKU is available.

@allowed([
  'Standard_LRS'
  'Standard_GRS'
  'Standard_ZRS'
  'Premium_LRS'
])
@description('SKU for the Storage Account.')
param storageSku string = 'Standard_LRS'

@description('SKU for the Key Vault.')
param keyVaultSku string = 'standard' // or 'premium'

@description('SKU for the Log Analytics Workspace.')
param logAnalyticsSku string = 'PerGB2018'

@description('SKU for Azure Cognitive Services (OpenAI, Document Intelligence).')
param cognitiveServicesSku string = 'S0'

@description('SKU for Azure AI Search service.')
param searchSku string = 'basic'

@description('The UTC date and time when the deployment was started.')
param createdDateTime string = utcNow('yyyy-MM-dd HH:mm:ss')


/* VARIABLES
=============================================================================== */
var tags = {
  Environment: environment
  Owner: resourceOwnerId
  CreatedDateTime: createdDateTime
  Project: 'SimpleChat'
}

var clientSecretSettingName = 'MICROSOFT_PROVIDER_AUTHENTICATION_SECRET'
var openIdIssuerUrl = 'https://login.microsoftonline${azurePlatform == 'AzureUSGovernment' ? '.us' : '.com'}/${tenantId}/v2.0'

var docIntelEndpointSuffix = azurePlatform == 'AzureUSGovernment' ? '.cognitiveservices.azure.us' : '.cognitiveservices.azure.com'
var azureSearchEndpointSuffix = azurePlatform == 'AzureUSGovernment' ? '.search.azure.us' : '.search.windows.net'


// --- Naming Conventions (simplified from PowerShell functions) ---
var resourceNamePrefix = toLower('${baseName}-${environment}')
var uniqueStringForGlobals = uniqueString(resourceGroup().id, baseName, environment) // For globally unique names
var logAnalyticsName = '${resourceNamePrefix}-la'
var appInsightsName = '${resourceNamePrefix}-ai'
var keyVaultName = 'kv${uniqueStringForGlobals}' // KV names are globally unique
var storageAccountName = toLower('${replace(baseName, '-', '')}${environment}sa${substring(uniqueStringForGlobals, 0, 5)}') // Strict naming: 3-24 chars, lowercase alphanumeric
var managedIdentityName = '${resourceNamePrefix}-id'
var appServicePlanName = '${resourceNamePrefix}-asp'
var appServiceName = '${resourceNamePrefix}-app-${uniqueStringForGlobals}' // App Service names are globally unique for hostname
var cosmosDbName = '${resourceNamePrefix}-cosmos-${uniqueStringForGlobals}' // Cosmos DB names are globally unique
var openAIName = useExistingOpenAiInstance ? existingAzureOpenAiResourceName : '${resourceNamePrefix}-oai'
var docIntelName = '${resourceNamePrefix}-docintel'
var searchServiceName = '${resourceNamePrefix}-search-${uniqueStringForGlobals}' // Search names are globally unique
var acrLoginServer = '${acrName}${azurePlatform == 'AzureUSGovernment' ? '.azurecr.us' : '.azurecr.io'}'
var appServiceDefaultHostName = '${appServiceName}${azurePlatform == 'AzureUSGovernment' ? '.azurewebsites.us' : '.azurewebsites.net'}'
var cosmosDbEndpointSuffix = azurePlatform == 'AzureUSGovernment' ? '.documents.azure.us' : '.documents.azure.com'
var openAIEndpointSuffix = azurePlatform == 'AzureUSGovernment' ? '.openai.azure.us' : '.openai.azure.com'
var azureEndpointNameForAppSetting = azurePlatform == 'AzureUSGovernment' ? 'usgovernment' : 'azurecloud'
//var graphEndpoint = azurePlatform == 'AzureUSGovernment' ? 'https://graph.microsoft.us' : 'https://graph.microsoft.com'
var appServiceRedirectUri1 = 'https://${appServiceDefaultHostName}/.auth/login/aad/callback'
var appServiceRedirectUri2 = 'https://${appServiceDefaultHostName}/getAToken'
var appServiceLogoutUrl = 'https://${appServiceDefaultHostName}/logout'
var dockerRegistryUrl = '${acrLoginServer}${azurePlatform == 'AzureUSGovernment' ? '/${imageName}' : ':${imageName}'}'

/* RESOURCES
=============================================================================== */

// --- Log Analytics Workspace ---
resource logAnalyticsWorkspace 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: logAnalyticsName
  location: location
  tags: tags
  properties: {
    sku: {
      name: logAnalyticsSku
    }
    retentionInDays: 30
  }
}

// --- Application Insights ---
resource applicationInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location // App Insights location might differ based on LA workspace region, check best practice
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalyticsWorkspace.id
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

// --- Key Vault ---
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  tags: tags
  properties: {
    sku: {
      family: 'A'
      name: keyVaultSku
    }
    tenantId: tenantId
    enableRbacAuthorization: true // Recommended. Script has logic to fallback to access policies.
    // enableSoftDelete: true // Default is true
    // softDeleteRetentionInDays: 90 // Default
    // enablePurgeProtection: false // Consider enabling for prod
    networkAcls: {
      defaultAction: 'Allow' // Or 'Deny' with bypass options and virtualNetworkRules
      bypass: 'AzureServices'
    }
  }
}

// --- Storage Account ---
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: storageAccountName
  location: location
  tags: tags
  sku: {
    name: storageSku
  }
  kind: 'StorageV2'
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Deny' // More secure default
    }
  }
}

// --- User-Assigned Managed Identity ---
resource managedIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: managedIdentityName
  location: location
  tags: tags
}

// --- App Service Plan (Linux) ---
resource appServicePlan 'Microsoft.Web/serverfarms@2022-09-01' = {
  name: appServicePlanName
  location: location
  tags: tags
  sku: {
    name: appServicePlanSku
    tier: split(appServicePlanSku, 'V')[0] // e.g., P1 from P1V3, B from B1. Adjust if SKU naming is different.
    // size: appServicePlanSku // Some SKUs like 'B1', 'S1' use 'size' directly. 'P1V3' is complex.
    // family: // e.g. 'P', 'B'
    // capacity: // For elastic premium or specific plans
  }
  kind: 'linux' // As per script --is-linux
  properties: {
    reserved: true // Required for Linux plans
  }
}

// --- App Service (Web App for Containers) ---
resource appService 'Microsoft.Web/sites@2022-09-01' = {
  name: appServiceName
  location: location
  tags: tags
  kind: 'app,linux,container'
  identity: {
    type: 'SystemAssigned, UserAssigned'
    userAssignedIdentities: {
      '${managedIdentity.id}': {}
    }
  }
  properties: {
    serverFarmId: appServicePlan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'DOCKER|${dockerRegistryUrl}'
      alwaysOn: appServicePlan.sku.tier != 'Free' && appServicePlan.sku.tier != 'Shared' && appServicePlan.sku.tier != 'Basic' // Example, P1V3 should be true
      ftpsState: 'FtpsOnly'
      minTlsVersion: '1.2'
      acrUseManagedIdentityCreds: true
      acrUserManagedIdentityID: managedIdentity.properties.clientId // Client ID of the UAMI
    }
  }
}

resource appSettings 'Microsoft.Web/sites/config@2024-04-01' = {
  name: 'appsettings'
  parent: appService
  properties: {
    APPINSIGHTS_INSTRUMENTATIONKEY: applicationInsights.properties.InstrumentationKey
    APPLICATIONINSIGHTS_CONNECTION_STRING: applicationInsights.properties.ConnectionString
    AZURE_ENDPOINT: azureEndpointNameForAppSetting
    SCM_DO_BUILD_DURING_DEPLOYMENT: 'true'
    AZURE_COSMOS_AUTHENTICATION_TYPE: 'key'
    AZURE_COSMOS_ENDPOINT: 'https://${cosmosDbName}${cosmosDbEndpointSuffix}'
    AZURE_COSMOS_KEY: cosmosDb.listKeys().primaryMasterKey
    TENANT_ID: tenantId
    CLIENT_ID: appRegistrationClientId
    SECRET_KEY: appRegistrationClientSecret
    MICROSOFT_PROVIDER_AUTHENTICATION_SECRET: appRegistrationClientSecret
    WEBSITE_AUTH_AAD_ALLOWED_TENANTS: tenantId
    DOCKER_REGISTRY_SERVER_URL: 'https://${acrLoginServer}'
    DOCKER_REGISTRY_SERVER_PASSWORD: ''
    DOCKER_REGISTRY_SERVER_USERNAME: ''
    AZURE_OPENAI_ENDPOINT: useExistingOpenAiInstance ? 'https://${existingAzureOpenAiResourceName}${openAIEndpointSuffix}' : 'https://${openAIName}${openAIEndpointSuffix}'
    AZURE_DOCUMENTINTELLIGENCE_ENDPOINT: 'https://${docIntelName}${docIntelEndpointSuffix}/'
    AZURE_SEARCH_SERVICE_ENDPOINT: 'https://${searchServiceName}${azureSearchEndpointSuffix}/'
    AZURE_KEY_VAULT_ENDPOINT: keyVault.properties.vaultUri
  }
}

resource authSettingsV2 'Microsoft.Web/sites/config@2024-04-01' = {
  name: 'authsettingsV2'
  parent: appService // Link to the parent web app
  properties: {
    globalValidation: {
      requireAuthentication: true // Redirect unauthenticated requests to login
      unauthenticatedClientAction: 'RedirectToLoginPage' // Action for unauthenticated clients
      redirectToProvider: 'AzureActiveDirectory' // Default provider to redirect to
    }
    httpSettings: {
      forwardProxy: {
        convention: 'Standard' // or 'NoProxy'
      }
    }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          clientId: appRegistrationClientId
          clientSecretSettingName: clientSecretSettingName // App setting name for client secret
          openIdIssuer: openIdIssuerUrl
        }
        login: {
          disableWWWAuthenticate: false
        }
        validation: {
          allowedAudiences: [
            'api://${appRegistrationClientId}' // Replace with your application's client ID or other allowed audiences
            //'https://${appServiceName}${azurePlatform == 'AzureUSGovernment' ? '.azurewebsites.us' : '.azurewebsites.net'}'
          ]
        }
      }
    }
    login: {
      tokenStore: {
        enabled: true // Enable token store to persist tokens
      }
    }
    platform: {
      enabled: true // Enable App Service Authentication/Authorization
      runtimeVersion: '~1' // Or a specific runtime version
    }
  }
}


// --- Azure Cosmos DB account ---
resource cosmosDb 'Microsoft.DocumentDB/databaseAccounts@2023-11-15' = {
  name: cosmosDbName
  location: location
  tags: tags
  kind: 'GlobalDocumentDB' // SQL API
  properties: {
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
    databaseAccountOfferType: 'Standard'
    locations: [
      {
        locationName: location
        failoverPriority: 0
      }
    ]
    enableMultipleWriteLocations: false
    enableBurstCapacity: true
    // enableServerless: false // If using provisioned throughput with autoscale
    // capabilities: [ { name: 'EnableServerless' } ] // if serverless
    // The script mentions 'enable-prpp-autoscale True' - this is usually for child resources (db/container)
    // For account level, burst capacity is the closest. Autoscale is set on database or container.
  }
}

// --- Azure OpenAI Service (Cognitive Services Account) ---
resource cognitiveServicesOpenAI 'Microsoft.CognitiveServices/accounts@2023-05-01' = if (!useExistingOpenAiInstance) {
  name: openAIName
  location: location
  tags: tags
  kind: 'OpenAI'
  sku: {
    name: cognitiveServicesSku
  }
  properties: {
    customSubDomainName: openAIName // Required for OpenAI kind
    publicNetworkAccess: 'Enabled'
  }
}

// --- Document Intelligence Service (Cognitive Services Account) ---
resource cognitiveServicesDocIntel 'Microsoft.CognitiveServices/accounts@2023-05-01' = {
  name: docIntelName
  location: location
  tags: tags
  kind: 'FormRecognizer' // Kind for Document Intelligence
  sku: {
    name: cognitiveServicesSku
  }
  properties: {
    customSubDomainName: docIntelName //docIntel_SubDomainName // this throws an error: The content for this response was already consumed
    publicNetworkAccess: 'Enabled'
  }
}

// --- Azure AI Search Service ---
resource searchService 'Microsoft.Search/searchServices@2023-11-01' = {
  name: searchServiceName
  location: location
  tags: tags
  sku: {
    name: searchSku // e.g., 'basic', 'standard'
  }
  properties: {
    replicaCount: (searchSku == 'free' || searchSku == 'basic') ? 1 : 1 // Basic allows 1, Free has fixed. Standard can be >1
    partitionCount: (searchSku == 'free' || searchSku == 'basic') ? 1 : 1 // Basic allows 1, Free has fixed. Standard can be >1
    publicNetworkAccess: 'enabled' // As per script
    hostingMode: 'default'
  }
}

// ============================= ROLE ASSIGNMENTS (RBAC) =============================
// Built-in Role Definition IDs (GUIDs are stable and preferred for RBAC in Bicep)
var roles = {
  keyVaultSecretsUser: '4633458b-17de-408a-b874-0445c86b69e6'
  keyVaultSecretsOfficer: 'b86a8fe4-44ce-4948-aee5-eccb2c1ادrole9' // Typo in original guid portion
  cognitiveServicesUser: 'a97b65f3-24c7-4388-baec-2e87135dc908'
  cognitiveServicesContributor: '25fbc0a9-bd7c-42a3-aa1a-3b75d497ee68'
  cognitiveServicesOpenAIUser: '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
  cognitiveServicesOpenAIContributor: 'a001fd3d-188f-4b5d-821b-7da978bf7442'
  contributor: 'b24988ac-6180-42a0-ab88-20f7382dd24c' // General Contributor
  storageBlobDataContributor: 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
  acrPull: '7f951dda-4ed3-4680-a7ca-43fe172d538d'
}

// --- User-Assigned MI to Key Vault (if KV RBAC is enabled) ---
resource uamiToKeyVaultAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(managedIdentity.id, keyVault.id, roles.keyVaultSecretsUser)
  scope: keyVault
  properties: {
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', roles.keyVaultSecretsUser)
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// --- User-Assigned MI to OpenAI ---
resource existingOpenAI 'Microsoft.CognitiveServices/accounts@2023-05-01' existing = if (useExistingOpenAiInstance) {
  name: existingAzureOpenAiResourceName
  scope: resourceGroup(existingAzureOpenAiResourceGroupName)
}

resource uamiToOpenAIAccess_User 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(managedIdentity.id, useExistingOpenAiInstance ? existingOpenAI.id : cognitiveServicesOpenAI.id, roles.cognitiveServicesOpenAIUser)
  scope: useExistingOpenAiInstance ? existingOpenAI : cognitiveServicesOpenAI
  properties: {
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', roles.cognitiveServicesOpenAIUser)
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource uamiToOpenAIAccess_Contributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(managedIdentity.id, useExistingOpenAiInstance ? existingOpenAI.id : cognitiveServicesOpenAI.id, roles.cognitiveServicesOpenAIContributor)
  scope: useExistingOpenAiInstance ? existingOpenAI : cognitiveServicesOpenAI
  properties: {
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', roles.cognitiveServicesOpenAIContributor)
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// --- User-Assigned MI to Cosmos DB (Contributor as per script) ---
// Note: For data plane, Cosmos DB SQL Role-Based Access Control is preferred if AAD auth type is used.
// The script uses 'key' auth type for app, so this Contributor might be for management plane tasks by MI.
resource uamiToCosmosDbAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(managedIdentity.id, cosmosDb.id, roles.contributor)
  scope: cosmosDb
  properties: {
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', roles.contributor)
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// --- User-Assigned MI to Storage Account ---
resource uamiToStorageAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(managedIdentity.id, storageAccount.id, roles.storageBlobDataContributor)
  scope: storageAccount
  properties: {
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', roles.storageBlobDataContributor)
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// --- App Service System-Assigned MI to OpenAI ---
resource appSvcSmiToOpenAIAccess_User 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(appService.id, 'smi-openai-user', useExistingOpenAiInstance ? existingAzureOpenAiResourceName : cognitiveServicesOpenAI.id)
  scope: useExistingOpenAiInstance ? existingOpenAI : cognitiveServicesOpenAI
  properties: {
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', roles.cognitiveServicesOpenAIUser)
    principalId: appService.identity.principalId // System-Assigned MI Principal ID
    principalType: 'ServicePrincipal'
  }
}

// --- App Service System-Assigned MI to Storage ---
resource appSvcSmiToStorageAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(appService.id, 'smi-storage', storageAccount.id)
  scope: storageAccount
  properties: {
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', roles.storageBlobDataContributor)
    principalId: appService.identity.principalId // System-Assigned MI Principal ID
    principalType: 'ServicePrincipal'
  }
}

// --- App Registration Service Principal to OpenAI (if SP ObjectId is provided) ---
resource appRegSpToOpenAIAccess_User 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(appRegistrationSpObjectId)) {
  name: guid(appRegistrationSpObjectId, 'appreg-sp-openai-user', useExistingOpenAiInstance ? existingAzureOpenAiResourceName : cognitiveServicesOpenAI.id)
  scope: useExistingOpenAiInstance ? existingOpenAI : cognitiveServicesOpenAI
  properties: {
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', roles.cognitiveServicesOpenAIUser)
    principalId: appRegistrationSpObjectId
    principalType: 'ServicePrincipal'
  }
}

resource appRegSpToOpenAIAccess_Contributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(appRegistrationSpObjectId)) {
  name: guid(appRegistrationSpObjectId, 'appreg-sp-openai-contrib', useExistingOpenAiInstance ? existingAzureOpenAiResourceName : cognitiveServicesOpenAI.id)
  scope: useExistingOpenAiInstance ? existingOpenAI : cognitiveServicesOpenAI
  properties: {
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', roles.cognitiveServicesOpenAIContributor)
    principalId: appRegistrationSpObjectId
    principalType: 'ServicePrincipal'
  }
}


/* OUTPUTS
=============================================================================== */
output tenantId string = tenantId
output existingAzureOpenAiResourceName string = existingAzureOpenAiResourceName
output existingAzureOpenAiResourceGroupName string = existingAzureOpenAiResourceGroupName
output cognitiveServicesSku string = cognitiveServicesSku
output acrResourceGroupName string = acrResourceGroupName
output appServiceName string = appService.name
output appServiceHostName string = appService.properties.defaultHostName
output appServicePrincipalId string = appService.identity.principalId
output userAssignedIdentityPrincipalId string = managedIdentity.properties.principalId
output keyVaultName string = keyVault.name
output keyVaultUri string = keyVault.properties.vaultUri
output storageAccountName string = storageAccount.name
output cosmosDbName string = cosmosDb.name
output cosmosDbEndpoint string = cosmosDb.properties.documentEndpoint
@description('Redirect URI 1 for manual App Registration configuration.')
output appRegistrationRedirectUri1 string = appServiceRedirectUri1
@description('Redirect URI 2 for manual App Registration configuration.')
output appRegistrationRedirectUri2 string = appServiceRedirectUri2
@description('Logout URL for manual App Registration configuration.')
output appRegistrationLogoutUrl string = appServiceLogoutUrl
output azureOpenAiEndpoint string = useExistingOpenAiInstance ? 'https://${existingAzureOpenAiResourceName}${openAIEndpointSuffix}' : 'https://${openAIName}${openAIEndpointSuffix}'
output documentIntelligenceEndpoint string = cognitiveServicesDocIntel.properties.endpoint
output searchServiceEndpoint string = 'https://${searchServiceName}.search.windows.net/' // Suffix may vary by platform
