targetScope = 'subscription'

@minLength(1)
@description('''The Azure region where resources will be deployed.  
- Region must align to the target cloud environment''')
param location string

@description('''The target Azure Cloud environment.
- Accepted values are: AzureCloud, AzureUSGovernment
- Default is AzureCloud''')
@allowed([
  'AzureCloud'
  'AzureUSGovernment'
])
param cloudEnvironment string

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

@minLength(1)
@maxLength(64)
@description('Name of the AZD environment')
param azdEnvironmentName string

@description('''The name of the container image to deploy to the web app.
- should be in the format <repository>:<tag>''')
param imageName string

@description('''Azure AD Application Client ID for enterprise authentication.
- Should be the client ID of the registered Azure AD application''')
param enterpriseAppClientId string

@description('''Azure AD Application Service Principal Id for the enterprise application.
- Should be the Service Principal ID of the registered Azure AD application''')
param enterpriseAppServicePrincipalId string

@description('''Azure AD Application Client Secret for enterprise authentication.
- Required if enableEnterpriseApp is true
- Should be created in Azure AD App Registration and passed via environment variable
- Will be stored securely in Azure Key Vault during deployment''')
@secure()
param enterpriseAppClientSecret string

//----------------
// configurations
@description('''Authentication type for resources that support Managed Identity or Key authentication.
- Key: Use access keys for authentication (application keys will be stored in Key Vault)
- managed_identity: Use Managed Identity for authentication''')
@allowed([
  'key'
  'managed_identity'
])
param authenticationType string

@description('''Configure permissions (based on authenticationType) for the deployed web application to access required resources.
''')
param configureApplicationPermissions bool

@description('Optional object containing additional tags to apply to all resources.')
param specialTags object = {}

@description('''Enable diagnostic logging for resources deployed in the resource group. 
- All content will be sent to the deployed Log Analytics workspace
- Default is false''')
param enableDiagLogging bool

@description('''Array of GPT model names to deploy to the OpenAI resource.''')
param gptModels array = [
  {
    modelName: 'gpt-4.1'
    modelVersion: '2025-04-14'
    skuName: 'GlobalStandard'
    skuCapacity: 150
  }
  {
    modelName: 'gpt-4o'
    modelVersion: '2024-11-20'
    skuName: 'GlobalStandard'
    skuCapacity: 100
  }
]

@description('''Array of embedding model names to deploy to the OpenAI resource.''')
param embeddingModels array = [
  {
    modelName: 'text-embedding-3-small'
    modelVersion: '1'
    skuName: 'GlobalStandard'
    skuCapacity: 150
  }
  {
    modelName: 'text-embedding-3-large'
    modelVersion: '1'
    skuName: 'GlobalStandard'
    skuCapacity: 150
  }
]
//----------------
// optional services

@description('''Enable deployment of Content Safety service and related resources.
- Default is false''')
param deployContentSafety bool

@description('''Enable deployment of Azure Cache for Redis and related resources.
- Default is false''')
param deployRedisCache bool

@description('''Enable deployment of Azure Speech service and related resources.
- Default is false''')
param deploySpeechService bool

@description('''Enable deployment of Azure Video Indexer service and related resources.
- Default is false''')
param deployVideoIndexerService bool

//=========================================================
// variable declarations for the main deployment 
//=========================================================
var rgName = '${appName}-${environment}-rg'
var requiredTags = { application: appName, environment: environment, 'azd-env-name': azdEnvironmentName }
var tags = union(requiredTags, specialTags)
var acrCloudSuffix = cloudEnvironment == 'AzureCloud' ? '.azurecr.io' : '.azurecr.us'
var acrName = toLower('${appName}${environment}acr')
var containerRegistry = '${acrName}${acrCloudSuffix}'
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
// Create log analytics workspace 
//=========================================================
module logAnalytics 'modules/logAnalyticsWorkspace.bicep' = {
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
// Create application insights
//=========================================================
module applicationInsights 'modules/applicationInsights.bicep' = {
  name: 'applicationInsights'
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
    enableDiagLogging: enableDiagLogging
    logAnalyticsId: logAnalytics.outputs.logAnalyticsId
  }
}

//=========================================================
// Store enterprise app client secret in key vault
//=========================================================
module storeEnterpriseAppSecret 'modules/keyVault-Secrets.bicep' = if (!empty(enterpriseAppClientSecret)) {
  name: 'storeEnterpriseAppSecret'
  scope: rg
  params: {
    keyVaultName: keyVault.outputs.keyVaultName
    secretName: 'enterprise-app-client-secret'
    secretValue: enterpriseAppClientSecret
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
    enableDiagLogging: enableDiagLogging
    logAnalyticsId: logAnalytics.outputs.logAnalyticsId

    keyVault: keyVault.outputs.keyVaultName
    authenticationType: authenticationType
    configureApplicationPermissions: configureApplicationPermissions
  }
}

//=========================================================
// Create Azure Container Registry
//=========================================================
module acr 'modules/azureContainerRegistry.bicep' = {
  name: 'azureContainerRegistry'
  scope: rg
  params: {
    location: location
    acrName: acrName
    tags: tags
    enableDiagLogging: enableDiagLogging
    logAnalyticsId: logAnalytics.outputs.logAnalyticsId

    keyVault: keyVault.outputs.keyVaultName
    authenticationType: authenticationType
    configureApplicationPermissions: configureApplicationPermissions
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
    enableDiagLogging: enableDiagLogging
    logAnalyticsId: logAnalytics.outputs.logAnalyticsId

    keyVault: keyVault.outputs.keyVaultName
    authenticationType: authenticationType
    configureApplicationPermissions: configureApplicationPermissions
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
    enableDiagLogging: enableDiagLogging
    logAnalyticsId: logAnalytics.outputs.logAnalyticsId

    keyVault: keyVault.outputs.keyVaultName
    authenticationType: authenticationType
    configureApplicationPermissions: configureApplicationPermissions
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
    enableDiagLogging: enableDiagLogging
    logAnalyticsId: logAnalytics.outputs.logAnalyticsId

    keyVault: keyVault.outputs.keyVaultName
    authenticationType: authenticationType
    configureApplicationPermissions: configureApplicationPermissions
  }
}

//=========================================================
// Create - OpenAI Service
//=========================================================
module openAI 'modules/openAI.bicep' = {
  name: 'openAI'
  scope: rg
  params: {
    location: location
    appName: appName
    environment: environment
    tags: tags
    enableDiagLogging: enableDiagLogging
    logAnalyticsId: logAnalytics.outputs.logAnalyticsId

    keyVault: keyVault.outputs.keyVaultName
    authenticationType: authenticationType
    configureApplicationPermissions: configureApplicationPermissions

    gptModels: gptModels
    embeddingModels: embeddingModels
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
    acrName: acr.outputs.acrName
    enableDiagLogging: enableDiagLogging
    logAnalyticsId: logAnalytics.outputs.logAnalyticsId
    appServicePlanId: appServicePlan.outputs.appServicePlanId
    containerImageName: containerImageName
    azurePlatform: cloudEnvironment
    cosmosDbName: cosmosDB.outputs.cosmosDbName
    searchServiceName: searchService.outputs.searchServiceName
    openAiServiceName: openAI.outputs.openAIName
    openAiResourceGroupName: openAI.outputs.openAIResourceGroup
    documentIntelligenceServiceName: docIntel.outputs.documentIntelligenceServiceName
    appInsightsName: applicationInsights.outputs.appInsightsName
    enterpriseAppClientId: enterpriseAppClientId
    enterpriseAppClientSecret: enterpriseAppClientSecret
    authenticationType: authenticationType
    keyVaultUri: keyVault.outputs.keyVaultUri
  }
}

//=========================================================
// configure optional services
//=========================================================

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
    enableDiagLogging: enableDiagLogging
    logAnalyticsId: logAnalytics.outputs.logAnalyticsId

    keyVault: keyVault.outputs.keyVaultName
    authenticationType: authenticationType
    configureApplicationPermissions: configureApplicationPermissions
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
    enableDiagLogging: enableDiagLogging
    logAnalyticsId: logAnalytics.outputs.logAnalyticsId

    keyVault: keyVault.outputs.keyVaultName
    authenticationType: authenticationType
    configureApplicationPermissions: configureApplicationPermissions
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
    enableDiagLogging: enableDiagLogging
    logAnalyticsId: logAnalytics.outputs.logAnalyticsId

    keyVault: keyVault.outputs.keyVaultName
    authenticationType: authenticationType
    configureApplicationPermissions: configureApplicationPermissions
  }
}

//=========================================================
// Create Optional Resource - Video Indexer Service
//=========================================================
module videoIndexerService 'modules/videoIndexer.bicep' = if (deployVideoIndexerService) {
  name: 'videoIndexerService'
  scope: rg
  params: {
    location: location
    appName: appName
    environment: environment
    tags: tags
    enableDiagLogging: enableDiagLogging
    logAnalyticsId: logAnalytics.outputs.logAnalyticsId

    storageAccount: storageAccount.outputs.name
    openAiServiceName: openAI.outputs.openAIName
  }
}

//=========================================================
// configure permissions for managed identity to access resources
//=========================================================
module setPermissions 'modules/setPermissions.bicep' = if (configureApplicationPermissions) {
  name: 'setPermissions'
  scope: rg
  params: {

    webAppName: appService.outputs.name
    authenticationType: authenticationType
    enterpriseAppServicePrincipalId: enterpriseAppServicePrincipalId
    keyVaultName: keyVault.outputs.keyVaultName
    cosmosDBName: cosmosDB.outputs.cosmosDbName
    acrName: acr.outputs.acrName
    openAIName: openAI.outputs.openAIName
    docIntelName: docIntel.outputs.documentIntelligenceServiceName
    storageAccountName: storageAccount.outputs.name
    #disable-next-line BCP318 // expect one value to be null
    speechServiceName: deploySpeechService ? speechService.outputs.speechServiceName : ''
    searchServiceName: searchService.outputs.searchServiceName
    #disable-next-line BCP318 // expect one value to be null
    contentSafetyName: deployContentSafety ? contentSafety.outputs.contentSafetyName : ''
    #disable-next-line BCP318 // expect one value to be null
    videoIndexerName: deployVideoIndexerService ? videoIndexerService.outputs.videoIndexerServiceName : ''
  }
}

//=========================================================
// output values
//=========================================================
// output required for both predeploy and postprovision scripts in azure.yaml
output var_rgName string = rgName

// output values required for predeploy script in azure.yaml
output var_webService string = appService.outputs.name
output var_imageName string = contains(imageName, ':') ? split(imageName, ':')[0] : imageName
output var_imageTag string = split(imageName, ':')[1]
output var_containerRegistry string = containerRegistry
output var_acrName string = toLower('${appName}${environment}acr')

// output values required for postprovision script in azure.yaml
output var_configureApplication bool = configureApplicationPermissions
output var_keyVaultUri string = keyVault.outputs.keyVaultUri
output var_cosmosDb_uri string = cosmosDB.outputs.cosmosDbUri
output var_subscriptionId string = subscription().subscriptionId
output var_authenticationType string = toLower(authenticationType)
output var_openAIEndpoint string = openAI.outputs.openAIEndpoint
output var_openAIResourceGroup string = openAI.outputs.openAIResourceGroup //may be able to remove
output var_openAIGPTModels array = gptModels
output var_openAIEmbeddingModels array = embeddingModels
output var_blobStorageEndpoint string = storageAccount.outputs.endpoint
#disable-next-line BCP318 // expect one value to be null
output var_contentSafetyEndpoint string = deployContentSafety ? contentSafety.outputs.contentSafetyEndpoint : ''
output var_deploymentLocation string = rg.location
output var_searchServiceEndpoint string = searchService.outputs.searchServiceEndpoint
output var_documentIntelligenceServiceEndpoint string = docIntel.outputs.documentIntelligenceServiceEndpoint
output var_videoIndexerName string = deployVideoIndexerService
#disable-next-line BCP318 // expect one value to be null
  ? videoIndexerService.outputs.videoIndexerServiceName
  : ''
output var_videoIndexerAccountId string = deployVideoIndexerService
#disable-next-line BCP318 // expect one value to be null
  ? videoIndexerService.outputs.videoIndexerAccountId
  : ''
#disable-next-line BCP318 // expect one value to be null
output var_speechServiceEndpoint string = deploySpeechService ? speechService.outputs.speechServiceEndpoint : ''
