targetScope = 'subscription'

@minLength(1)
@description('''The Azure region where resources will be deployed.  
- Region must align to the target cloud environment''')
param location string

@allowed([
  'public'
  'usgovernment'
  'custom'  
])
param cloudEnvironmentOverride string?
var cloudEnvironment = cloudEnvironmentOverride ?? (az.environment().name == 'AzureCloud' ? 'public' : (az.environment().name == 'AzureUSGovernment' ? 'usgovernment' : 'custom'))

@description('''The name of the application to be deployed.  
- Name may only contain letters and numbers
- Between 3 and 12 characters in length 
- No spaces or special characters''')
@minLength(3)
@maxLength(12)
param appName string

@description('''The dev/qa/prod environment or as named in your environment. This will be used to create resource group names and tags.
- Must be between 2 and 10 characters in length
- No spaces or special characters''')
@minLength(2)
@maxLength(10)
param environment string

@description('Optional object containing additional tags to apply to all resources.')
param specialTags object = {}

@minLength(1)
@maxLength(64)
@description('Name of the AZD environment')
param azdEnvironmentName string

@description('''Enable diagnostic logging for resources deployed in the resource group. 
- All content will be sent to the deployed Log Analytics workspace
- Default is false''')
param enableDiagLogging bool

@description('''Enable enterprise application (Azure AD App Registration) configuration.
- Enables SSO, conditional access, and centralized identity management
- Default is true''')
param enableEnterpriseApp bool = true

@description('''Azure AD Application Client ID for enterprise authentication.
- Required if enableEnterpriseApp is true
- Should be the client ID of the registered Azure AD application''')
param enterpriseAppClientId string

@description('''Azure AD Application Client Secret for enterprise authentication.
- Required if enableEnterpriseApp is true
- Should be created in Azure AD App Registration and passed via environment variable
- Will be stored securely in Azure Key Vault during deployment''')
@secure()
param enterpriseAppClientSecret string

@description('''Use existing Azure Container Registry
- Default is false''')
param useExistingAcr bool

@description('''The name of the existing Azure Container Registry containing the container image to deploy to the web app.
- Required if useExistingAcr is true
- should be in the format <registry-name>
- Do not include any domain suffix such as .azurecr.io''')
param existingAcrResourceName string

@description('''The name of the Azure Container Registry resource group.
- Required if useExistingAcr is true''')
param existingAcrResourceGroup string

@description('''Enable deployment of Content Safety service and related resources.
- Default is false''')
param deployContentSafety bool

@description('''Enable deployment of Azure Cache for Redis and related resources.
- Default is false''')
param deployRedisCache bool

@description('''Enable deployment of Azure Speech service and related resources.
- Default is false''')
param deploySpeechService bool

@description('''Use existing Azure OpenAI resource''')
param useExistingOpenAISvc bool

@description('''Existing Azure OpenAI Resource Group Name
- Required if useExistingOpenAISvc is true''')
param existingOpenAIResourceGroupName string

@description('''Existing Azure OpenAI Resource Name
- Required if useExistingOpenAISvc is true''')
param existingOpenAIResourceName string

@description('''The name of the container image to deploy to the web app.
- should be in the format <repository>:<tag>''')
param imageName string

@description('''Unauthenticated client action for enterprise application.
- RedirectToLoginPage: Redirect unauthenticated users to login
- Return401: Return 401 Unauthorized for unauthenticated requests
- AllowAnonymous: Allow anonymous access''')
@allowed([
  'AllowAnonymous'
  'RedirectToLoginPage'
  'Return401'
  'Return403'
])
param unauthenticatedClientAction string = 'RedirectToLoginPage'

//=========================================================
// variable declarations for the main deployment 
//=========================================================

var rgName = '${appName}-${environment}-rg'
var requiredTags = { application: appName, environment: environment, 'azd-env-name': azdEnvironmentName }
var tags = union(requiredTags, specialTags)
var acrCloudSuffix = az.environment().suffixes.acrLoginServer
var containerRegistry = '${acrName}${acrCloudSuffix}'
var acrName = useExistingAcr ? existingAcrResourceName : toLower('${appName}${environment}acr')
var containerImageName = '${containerRegistry}/${imageName}'

//=========================================================
// Resource group deployment
//=========================================================
resource rg 'Microsoft.Resources/resourceGroups@2022-09-01' = {
  name: rgName
  location: location
  tags: tags
}

//=========================================================
// Create managed identity
//=========================================================
module managedIdentity 'modules/managedIdentity.bicep' = {
  name: 'managedIdentity'
  scope: rg
  params: {
    location: location
    appName: appName
    environment: environment
    tags: tags
  }
}

//=========================================================
// Create log analytics workspace 
//=========================================================
module logAnalytics 'modules/logAnalytics.bicep' = {
  name: 'logAnalytics'
  scope: rg
  params: {
    location: location
    appName: appName
    environment: environment
    tags: tags
  }
}

//=========================================================
// Create key vault
//=========================================================
module keyVault 'modules/keyVault.bicep' = {
  name: 'keyVault'
  scope: rg
  params: {
    location: location
    appName: appName
    environment: environment
    tags: tags
    managedIdentityPrincipalId: managedIdentity.outputs.principalId
    managedIdentityId: managedIdentity.outputs.resourceId
    enableDiagLogging: enableDiagLogging
    logAnalyticsId: logAnalytics.outputs.logAnalyticsId
    enableEnterpriseApp: enableEnterpriseApp
    enterpriseAppClientId: enterpriseAppClientId
    enterpriseAppClientSecret: enterpriseAppClientSecret
  }
}

//=========================================================
// Create application insights
//=========================================================
module appInsights 'modules/appInsights.bicep' = {
  name: 'appInsights'
  scope: rg
  params: {
    location: location
    appName: appName
    environment: environment
    tags: tags
    logAnalyticsId: logAnalytics.outputs.logAnalyticsId
  }
}

//=========================================================
// Create storage account
//=========================================================
module storageAccount 'modules/storageAccount.bicep' = {
  name: 'storageAccount'
  scope: rg
  params: {
    location: location
    appName: appName
    environment: environment
    tags: tags
    managedIdentityPrincipalId: managedIdentity.outputs.principalId
    managedIdentityId: managedIdentity.outputs.resourceId
    enableDiagLogging: enableDiagLogging
    logAnalyticsId: logAnalytics.outputs.logAnalyticsId
  }
}

//=========================================================
// Create CosmosDB resource
//=========================================================
module cosmosDB 'modules/cosmosDb.bicep' = {
  name: 'cosmosDB'
  scope: rg
  params: {
    location: location
    appName: appName
    environment: environment
    tags: tags
    managedIdentityPrincipalId: managedIdentity.outputs.principalId
    managedIdentityId: managedIdentity.outputs.resourceId
    enableDiagLogging: enableDiagLogging
    logAnalyticsId: logAnalytics.outputs.logAnalyticsId
  }
}

//=========================================================
// Create Document Intelligence resource
//=========================================================
module docIntel 'modules/documentIntelligence.bicep' = {
  name: 'docIntel'
  scope: rg
  params: {
    location: location
    appName: appName
    environment: environment
    tags: tags
    managedIdentityPrincipalId: managedIdentity.outputs.principalId
    managedIdentityId: managedIdentity.outputs.resourceId
    enableDiagLogging: enableDiagLogging
    logAnalyticsId: logAnalytics.outputs.logAnalyticsId
  }
}

//=========================================================
// Create or get Azure Container Registry
//=========================================================
module acr_create 'modules/azureContainerRegistry.bicep' = if (!useExistingAcr) {
  name: 'azureContainerRegistry_create'
  scope: rg
  params: {
    location: location
    acrName: acrName
    tags: tags
    managedIdentityPrincipalId: managedIdentity.outputs.principalId
    managedIdentityId: managedIdentity.outputs.resourceId
    enableDiagLogging: enableDiagLogging
    logAnalyticsId: logAnalytics.outputs.logAnalyticsId
  }
}

module acr_existing 'modules/azureContainerRegistry-existing.bicep' = if (useExistingAcr) {
  name: 'acr-existing'
  scope: rg
  params: {
    acrName: existingAcrResourceName
    acrResourceGroup: existingAcrResourceGroup
    managedIdentityPrincipalId: managedIdentity.outputs.principalId
  }
}

//=========================================================
// Create Search Service resource
//=========================================================
module searchService 'modules/search.bicep' = {
  name: 'searchService'
  scope: rg
  params: {
    location: location
    appName: appName
    environment: environment
    tags: tags
    managedIdentityPrincipalId: managedIdentity.outputs.principalId
    managedIdentityId: managedIdentity.outputs.resourceId
    enableDiagLogging: enableDiagLogging
    logAnalyticsId: logAnalytics.outputs.logAnalyticsId
  }
}

//=========================================================
// Create or get Optional Resource - OpenAI Service
//=========================================================
module openAI_create 'modules/openAI.bicep' = if (!useExistingOpenAISvc) {
  name: 'openAICreate'
  scope: rg
  params: {
    location: location
    appName: appName
    environment: environment
    tags: tags
    //managedIdentityPrincipalId: managedIdentity.outputs.principalId
    managedIdentityId: managedIdentity.outputs.resourceId
    enableDiagLogging: enableDiagLogging
    logAnalyticsId: logAnalytics.outputs.logAnalyticsId
  }
}

module openAI_existing 'modules/openAI-existing.bicep' = if (useExistingOpenAISvc) {
  name: 'openAIExisting'
  scope: resourceGroup(useExistingOpenAISvc ? existingOpenAIResourceGroupName : rgName)
  params: {
    openAIName: existingOpenAIResourceName
  }
}

//=========================================================
// Create Optional Resource - Content Safety
//=========================================================
module contentSafety 'modules/contentSafety.bicep' = if (deployContentSafety) {
  name: 'contentSafety'
  scope: rg
  params: {
    location: location
    appName: appName
    environment: environment
    tags: tags
    managedIdentityPrincipalId: managedIdentity.outputs.principalId
    managedIdentityId: managedIdentity.outputs.resourceId
    enableDiagLogging: enableDiagLogging
    logAnalyticsId: logAnalytics.outputs.logAnalyticsId
  }
}

//=========================================================
// Create Optional Resource - Redis Cache
//=========================================================
module redisCache 'modules/redisCache.bicep' = if (deployRedisCache) {
  name: 'redisCache'
  scope: rg
  params: {
    location: location
    appName: appName
    environment: environment
    tags: tags
    //managedIdentityPrincipalId: managedIdentity.outputs.principalId
    //managedIdentityId: managedIdentity.outputs.resourceId
    enableDiagLogging: enableDiagLogging
    logAnalyticsId: logAnalytics.outputs.logAnalyticsId
  }
}

//=========================================================
// Create App Service Plan
//=========================================================
module appServicePlan 'modules/appServicePlan.bicep' = {
  name: 'appServicePlan'
  scope: rg
  params: {
    location: location
    appName: appName
    environment: environment
    tags: tags
    enableDiagLogging: enableDiagLogging
    logAnalyticsId: logAnalytics.outputs.logAnalyticsId
  }
}

//=========================================================
// Create App Service (Web App for Containers)
//=========================================================
module appService 'modules/appService.bicep' = {
  name: 'appService'
  scope: rg
  params: {
    location: location
    appName: appName
    environment: environment
    tags: tags
    acrName: useExistingAcr ? acr_existing!.outputs.acrName : acr_create!.outputs.acrName
    managedIdentityId: managedIdentity.outputs.resourceId
    managedIdentityClientId: managedIdentity.outputs.clientId
    enableDiagLogging: enableDiagLogging
    logAnalyticsId: logAnalytics.outputs.logAnalyticsId
    appServicePlanId: appServicePlan.outputs.appServicePlanId
    containerImageName: containerImageName
    azurePlatform: cloudEnvironment
    cosmosDbName: cosmosDB.outputs.cosmosDbName
    searchServiceName: searchService.outputs.searchServiceName
    openAiServiceName: useExistingOpenAISvc ? openAI_existing!.outputs.openAIName : openAI_create!.outputs.openAIName
    openAiResourceGroupName: useExistingOpenAISvc
      ? existingOpenAIResourceGroupName
      : openAI_create!.outputs.openAIResourceGroup
    documentIntelligenceServiceName: docIntel.outputs.documentIntelligenceServiceName
    appInsightsName: appInsights.outputs.appInsightsName
    enterpriseAppClientId: enterpriseAppClientId
    enterpriseAppClientSecret: ''
    keyVaultUri: keyVault.outputs.keyVaultUri
  }
}

//=========================================================
// Create Enterprise Application Configuration
//=========================================================
module enterpriseApp 'modules/enterpriseApplication.bicep' = if (enableEnterpriseApp) {
  name: 'enterpriseApplication'
  scope: rg
  params: {
    appName: appName
    environment: environment
    redirectUri: 'https://${appService.outputs.defaultHostName}'
  }
}

//=========================================================
// Configure App Service Authentication with Enterprise App
//=========================================================
module appServiceAuth 'modules/appServiceAuthentication.bicep' = if (enableEnterpriseApp && !empty(enterpriseAppClientId)) {
  name: 'appServiceAuthentication'
  scope: rg
  dependsOn: [
    enterpriseApp
  ]
  params: {
    webAppName: appService.outputs.name
    clientId: enterpriseAppClientId
    // Use the auto-generated secret URI if no manual secret was provided, otherwise use the manual one
    clientSecretKeyVaultUri: !empty(enterpriseAppClientSecret) ? keyVault.outputs.enterpriseAppClientSecretUri : ''
    tenantId: tenant().tenantId
    enableAuthentication: enableEnterpriseApp
    unauthenticatedClientAction: unauthenticatedClientAction
    tokenStoreEnabled: true
  }
}

//=========================================================
// Create Optional Resource - Speech Service
//=========================================================
module speechService 'modules/speechService.bicep' = if (deploySpeechService) {
  name: 'speechService'
  scope: rg
  params: {
    location: location
    appName: appName
    environment: environment
    tags: tags
    managedIdentityPrincipalId: managedIdentity.outputs.principalId
    managedIdentityId: managedIdentity.outputs.resourceId
    enableDiagLogging: enableDiagLogging
    logAnalyticsId: logAnalytics.outputs.logAnalyticsId
  }
}

//=========================================================
// Resource to Configure Enterprise App Permissions
//=========================================================
module enterpriseAppPermissions 'modules/enterpriseAppPermissions.bicep' = if (enableEnterpriseApp) {
  name: 'enterpriseAppPermissions'
  scope: rg
  params: {
    webAppName: appService.outputs.name
    keyVaultName: keyVault.outputs.keyVaultName
    cosmosDBName: cosmosDB.outputs.cosmosDbName
    #disable-next-line BCP318 // expect one value to be null
    openAIName: useExistingOpenAISvc ? '' : openAI_create.outputs.openAIName
    docIntelName: docIntel.outputs.documentIntelligenceServiceName
    storageAccountName: storageAccount.outputs.name
    #disable-next-line BCP318 // expect one value to be null
    speechServiceName: deploySpeechService ? speechService.outputs.speechServiceName : ''
    searchServiceName: searchService.outputs.searchServiceName
    #disable-next-line BCP318 // expect one value to be null
    contentSafetyName: deployContentSafety ? contentSafety.outputs.contentSafetyName : ''
  }
}


//=========================================================
// Outputs for deployment of container image
//=========================================================

output var_rgName string = rgName
output var_acrName string = useExistingAcr ? existingAcrResourceName : toLower('${appName}${environment}acr')
output var_containerRegistry string = containerRegistry
output var_imageName string = contains(imageName, ':') ? split(imageName, ':')[0] : imageName
output var_imageTag string = split(imageName, ':')[1] 
output var_specialImage bool = contains(imageName, ':') ? split(imageName, ':')[1] != 'latest' : false
output var_webService string = appService.outputs.name
