targetScope = 'subscription'

@minLength(1)
@description('''The Azure region where resources will be deployed.  
- Region must align to the target cloud environment''')
param location string

@description('''The target Azure Cloud environment.
- Accepted values are: AzureCloud, AzureUSGovernment, public, usgovernment, custom
- Default is based on the ARM cloud name''')
@allowed([
  'AzureCloud'        // public, keep allowed values for backwards compatibility
  'AzureUSGovernment' // usgovernment
  'public'             
  'usgovernment'       
  'custom'
])
param cloudEnvironment string = az.environment().name == 'AzureCloud' ? 'public' : (az.environment().name == 'AzureUSGovernment' ? 'usgovernment' : 'custom')
// SimpleChat expects public, usgovernment or custom
var scCloudEnvironment = cloudEnvironment == 'AzureCloud' ? 'public' : (cloudEnvironment == 'AzureUSGovernment' ? 'usgovernment' : cloudEnvironment)

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
param imageName string = 'simplechat:latest'

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

@description('''Enable private endpoints and virtual network integration for deployed resources. 
- Default is false''')
param enablePrivateNetworking bool

@description('''Optional existing virtual network resource ID to reuse when private networking is enabled.
- May reference a virtual network in the same or another resource group or subscription
- Leave blank to create a new virtual network''')
param existingVirtualNetworkId string = ''

@description('''Optional existing subnet resource ID to use for App Service VNet integration.
- May reference a subnet in the same or another resource group or subscription
- Required when reusing an existing virtual network because subnets are not created in external virtual networks''')
param existingAppServiceSubnetId string = ''

@description('''Optional existing subnet resource ID to use for private endpoints.
- May reference a subnet in the same or another resource group or subscription
- Required when reusing an existing virtual network because subnets are not created in external virtual networks''')
param existingPrivateEndpointSubnetId string = ''

@description('''Optional per-zone private DNS configuration for private networking.
- Leave empty to create all private DNS zones locally and create VNet links automatically
- For each supported key, provide:
  - zoneResourceId: Optional existing private DNS zone resource ID to reuse
  - createVNetLink: Optional bool, defaults to true. Set to false if the customer manages the VNet link separately
- Supported keys: keyVault, cosmosDb, containerRegistry, aiSearch, blobStorage, cognitiveServices, openAi, webSites''')
param privateDnsZoneConfigs object = {}

@description('''Optional existing Azure OpenAI or Azure AI Foundry OpenAI-compatible endpoint.
- Leave blank to deploy a new Azure OpenAI resource
- Public Azure AI Foundry project endpoints are supported for application configuration, but do not support private endpoint automation''')
param existingOpenAIEndpoint string = ''

@description('''Optional Video Indexer ARM API version override for custom cloud deployments.
- Leave blank to use the cloud default
- Public defaults to 2025-04-01
- Azure Government defaults to 2024-01-01''')
param customVideoIndexerArmApiVersion string = ''

@description('''Optional Video Indexer endpoint override for custom cloud deployments.
- Leave blank to use the public endpoint default''')
param customVideoIndexerEndpoint string = ''

@description('''Optional existing Azure OpenAI resource name.
- Provide this when reusing a standard Azure OpenAI resource and you want managed identity permissions or private endpoint integration configured automatically''')
param existingOpenAIResourceName string = ''

@description('''Optional resource group for an existing Azure OpenAI resource.
- Used when reusing a standard Azure OpenAI resource across resource groups or subscriptions''')
param existingOpenAIResourceGroup string = ''

@description('''Optional subscription ID for an existing Azure OpenAI resource.
- Used when reusing a standard Azure OpenAI resource across subscriptions''')
param existingOpenAISubscriptionId string = ''

@description('''Azure OpenAI deployment type used for the default GPT and embedding model deployments.
- Azure Commercial options: Standard, DatazoneStandard, GlobalStandard
- Azure Government default model deployments use Standard regardless of this selection
- Ignored when you provide custom gptModels or embeddingModels arrays''')
@allowed([
  'Standard'
  'DatazoneStandard'
  'GlobalStandard'
])
param openAIDeploymentType string

// --- Custom Azure Environment Parameters (for 'custom' azureEnvironment) ---
@description('Custom blob storage URL suffix, e.g. blob.core.usgovcloudapi.net')
param customBlobStorageSuffix string = 'blob.${az.environment().suffixes.storage}'
@description('Custom Graph API URL, e.g. https://graph.microsoft.us')
param customGraphUrl string? // az.environment().graph is legacy AD, do not use
@description('Custom Identity URL, e.g. https://login.microsoftonline.us/')
param customIdentityUrl string = az.environment().authentication.loginEndpoint
@description('Custom Resource Manager URL, e.g. https://management.usgovcloudapi.net')
param customResourceManagerUrl string = az.environment().resourceManager
@description('Custom Cognitive Services scope ex: https://cognitiveservices.azure.com/.default')
param customCognitiveServicesScope string = 'https://cognitiveservices.azure.com/.default'
@description('Custom search resource URL for token audience, e.g. https://search.azure.us')
param customSearchResourceUrl string = 'https://search.azure.com'

@description('''Array of GPT model names to deploy to the OpenAI resource.''')
param gptModels array = []

@description('''Array of embedding model names to deploy to the OpenAI resource.''')
param embeddingModels array = []

//----------------
// allowed IP addresses for resources
@description('''Comma separated list of IP addresses or ranges to allow access to resources when private networking is enabled.
Leave blank if not using private networking.
- Format for single IP: 'x.x.x.x'
- Format for range: 'x.x.x.x/y'
- Example:  1.2.3.4, 2.3.4.5/32
''')
param allowedIpAddresses string = ''
var allowedIpAddressesSplit = empty(allowedIpAddresses) ? [] : split(allowedIpAddresses!, ',')
var allowedIpAddressesArray = [for ip in allowedIpAddressesSplit: trim(ip)]
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
var isPublicCloud = scCloudEnvironment == 'public'
var isUsGovernmentCloud = scCloudEnvironment == 'usgovernment'
var acrCloudSuffix = isPublicCloud ? '.azurecr.io' : '.azurecr.us'
var acrName = toLower('${appName}${environment}acr')
var containerRegistry = '${acrName}${acrCloudSuffix}'
var containerImageName = '${containerRegistry}/${imageName}'
var vNetName = '${appName}-${environment}-vnet'
var normalizedLocation = toLower(replace(location, ' ', ''))
var resolvedOpenAIDeploymentType = isUsGovernmentCloud ? 'Standard' : openAIDeploymentType
var defaultGptModels = [
  {
    modelName: 'gpt-4o'
    modelVersion: isUsGovernmentCloud ? '2024-05-13' : '2024-11-20'
    skuName: resolvedOpenAIDeploymentType
    skuCapacity: 100
  }
]
var defaultEmbeddingModels = isUsGovernmentCloud
  ? [
      {
        modelName: normalizedLocation == 'usgovvirginia' ? 'text-embedding-ada-002' : 'text-embedding-3-small'
        modelVersion: normalizedLocation == 'usgovvirginia' ? '2' : '1'
        skuName: resolvedOpenAIDeploymentType
        skuCapacity: 100
      }
    ]
  : [
      {
        modelName: 'text-embedding-3-small'
        modelVersion: '1'
        skuName: resolvedOpenAIDeploymentType
        skuCapacity: 100
      }
    ]
var resolvedGptModels = empty(gptModels) ? defaultGptModels : gptModels
var resolvedEmbeddingModels = empty(embeddingModels) ? defaultEmbeddingModels : embeddingModels
var resolvedVideoIndexerArmApiVersion = scCloudEnvironment == 'usgovernment'
  ? '2024-01-01'
  : (scCloudEnvironment == 'custom' && !empty(customVideoIndexerArmApiVersion) ? customVideoIndexerArmApiVersion : '2025-04-01')
var resolvedVideoIndexerEndpoint = scCloudEnvironment == 'usgovernment'
  ? 'https://api.videoindexer.ai.azure.us'
  : (scCloudEnvironment == 'custom' && !empty(customVideoIndexerEndpoint) ? customVideoIndexerEndpoint : 'https://api.videoindexer.ai')
var videoIndexerSupportsOpenAiIntegration = resolvedVideoIndexerArmApiVersion == '2025-04-01'
var videoIndexerSupportsPrivateEndpoints = resolvedVideoIndexerArmApiVersion == '2025-04-01'
var hasExistingAppServiceSubnetId = !empty(existingAppServiceSubnetId)
var hasExistingPrivateEndpointSubnetId = !empty(existingPrivateEndpointSubnetId)
var inferredVirtualNetworkId = hasExistingAppServiceSubnetId ? split(existingAppServiceSubnetId, '/subnets/')[0] : (hasExistingPrivateEndpointSubnetId ? split(existingPrivateEndpointSubnetId, '/subnets/')[0] : '')
var resolvedExistingVirtualNetworkId = !empty(existingVirtualNetworkId) ? existingVirtualNetworkId : inferredVirtualNetworkId
var useExistingVirtualNetwork = enablePrivateNetworking && (!empty(resolvedExistingVirtualNetworkId) || hasExistingAppServiceSubnetId || hasExistingPrivateEndpointSubnetId)
var allowedIpsForCosmos = union(['0.0.0.0'], allowedIpAddressesArray)
var cosmosDbIpRules = [for ip in allowedIpsForCosmos: {
  ipAddressOrRange: ip
}]
var acrIpRules = [for ip in allowedIpAddressesArray: {
  action: 'Allow'
  value: ip
}]
#disable-next-line BCP318 // value can't be null when a new virtual network is created
var resolvedVirtualNetworkId = enablePrivateNetworking ? (useExistingVirtualNetwork ? resolvedExistingVirtualNetworkId : virtualNetwork.outputs.vNetId) : ''
#disable-next-line BCP318 // value can't be null when a new virtual network is created
var resolvedAppServiceSubnetId = enablePrivateNetworking ? (useExistingVirtualNetwork ? existingAppServiceSubnetId : virtualNetwork.outputs.appServiceSubnetId) : ''
#disable-next-line BCP318 // value can't be null when a new virtual network is created
var resolvedPrivateEndpointSubnetId = enablePrivateNetworking ? (useExistingVirtualNetwork ? existingPrivateEndpointSubnetId : virtualNetwork.outputs.privateNetworkSubnetId) : ''

//=========================================================
// Resource group deployment
//=========================================================
resource rg 'Microsoft.Resources/resourceGroups@2022-09-01' = {
  name: rgName
  location: location
  tags: tags
}

//=========================================================
// Create Virtual Network if private networking is enabled
//=========================================================
module virtualNetwork 'modules/virtualNetwork.bicep' = if (enablePrivateNetworking && !useExistingVirtualNetwork) {
  scope: rg
  name: 'virtualNetwork'
  params: {
    location: location
    vNetName: vNetName
    addressSpaces: ['10.0.0.0/21']
    subnetConfigs: [
      {
        name: 'AppServiceIntegration' // this subnet name must be present for app service vnet integration
        addressPrefix: '10.0.0.0/24'
        enablePrivateEndpointNetworkPolicies: true
        enablePrivateLinkServiceNetworkPolicies: true
      }
      {
        name: 'PrivateEndpoints' // this subnet name must be present if private endpoints are to be used
        addressPrefix: '10.0.2.0/24'
        enablePrivateEndpointNetworkPolicies: true
        enablePrivateLinkServiceNetworkPolicies: true
      }
    ]
    tags: tags
  }
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

    enablePrivateNetworking: enablePrivateNetworking
    allowedIpAddresses: cosmosDbIpRules
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

    enablePrivateNetworking: enablePrivateNetworking
    allowedIpAddresses: acrIpRules
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

    enablePrivateNetworking: enablePrivateNetworking
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

    enablePrivateNetworking: enablePrivateNetworking
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

    enablePrivateNetworking: enablePrivateNetworking
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

    existingOpenAIEndpoint: existingOpenAIEndpoint
    existingOpenAIResourceName: existingOpenAIResourceName
    existingOpenAIResourceGroup: existingOpenAIResourceGroup
    existingOpenAISubscriptionId: existingOpenAISubscriptionId
    gptModels: resolvedGptModels
    embeddingModels: resolvedEmbeddingModels

    enablePrivateNetworking: enablePrivateNetworking
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
    azurePlatform: scCloudEnvironment
    cosmosDbName: cosmosDB.outputs.cosmosDbName
    searchServiceName: searchService.outputs.searchServiceName
    openAiServiceName: openAI.outputs.openAIName
    openAiEndpoint: openAI.outputs.openAIEndpoint
    openAiResourceGroupName: openAI.outputs.openAIResourceGroup
    documentIntelligenceServiceName: docIntel.outputs.documentIntelligenceServiceName
    appInsightsName: applicationInsights.outputs.appInsightsName
    enterpriseAppClientId: enterpriseAppClientId
    enterpriseAppClientSecret: enterpriseAppClientSecret
    authenticationType: authenticationType
    keyVaultUri: keyVault.outputs.keyVaultUri

    enablePrivateNetworking: enablePrivateNetworking
    appServiceSubnetId: resolvedAppServiceSubnetId

    // --- Custom Azure Environment Parameters (for 'custom' azureEnvironment) ---
    customBlobStorageSuffix: customBlobStorageSuffix
    customGraphUrl: customGraphUrl
    customIdentityUrl: customIdentityUrl
    customResourceManagerUrl: customResourceManagerUrl
    customCognitiveServicesScope: customCognitiveServicesScope
    customSearchResourceUrl: customSearchResourceUrl
    customVideoIndexerEndpoint: resolvedVideoIndexerEndpoint
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

    enablePrivateNetworking: enablePrivateNetworking
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

    //enablePrivateNetworking: enablePrivateNetworking
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

    enablePrivateNetworking: enablePrivateNetworking
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
    videoIndexerArmApiVersion: resolvedVideoIndexerArmApiVersion

    enablePrivateNetworking: enablePrivateNetworking
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
    openAIResourceGroupName: openAI.outputs.openAIResourceGroup
    openAISubscriptionId: openAI.outputs.openAISubscriptionId
    docIntelName: docIntel.outputs.documentIntelligenceServiceName
    storageAccountName: storageAccount.outputs.name
    searchServiceName: searchService.outputs.searchServiceName

    #disable-next-line BCP318 // expect one value to be null
    speechServiceName: deploySpeechService ? speechService.outputs.speechServiceName : ''
    #disable-next-line BCP318 // expect one value to be null
    redisCacheName: deployRedisCache ? redisCache.outputs.redisCacheName : ''
    #disable-next-line BCP318 // expect one value to be null
    contentSafetyName: deployContentSafety ? contentSafety.outputs.contentSafetyName : ''
    #disable-next-line BCP318 // expect one value to be null
    videoIndexerName: deployVideoIndexerService ? videoIndexerService.outputs.videoIndexerServiceName : ''
    videoIndexerSupportsOpenAiIntegration: videoIndexerSupportsOpenAiIntegration
  }
}

//=========================================================
// configure private networking
//=========================================================
module privateNetworking 'modules/privateNetworking.bicep' = if (enablePrivateNetworking) {
  name: 'privateNetworking'
  scope: rg
  params: {

    virtualNetworkId: resolvedVirtualNetworkId
    privateEndpointSubnetId: resolvedPrivateEndpointSubnetId
    privateDnsZoneConfigs: privateDnsZoneConfigs

    location: location
    appName: appName
    environment: environment
    tags: tags

    keyVaultName: keyVault.outputs.keyVaultName
    cosmosDBName: cosmosDB.outputs.cosmosDbName
    acrName: acr.outputs.acrName
    searchServiceName: searchService.outputs.searchServiceName
    docIntelName: docIntel.outputs.documentIntelligenceServiceName
    storageAccountName: storageAccount.outputs.name
    openAIName: openAI.outputs.openAIName
    openAIResourceGroupName: openAI.outputs.openAIResourceGroup
    openAISubscriptionId: openAI.outputs.openAISubscriptionId
    webAppName: appService.outputs.name
    
    #disable-next-line BCP318 // expect one value to be null
    contentSafetyName: deployContentSafety ? contentSafety.outputs.contentSafetyName : ''
    #disable-next-line BCP318 // expect one value to be null
    speechServiceName: deploySpeechService ? speechService.outputs.speechServiceName : ''
    #disable-next-line BCP318 // expect one value to be null
    videoIndexerName: deployVideoIndexerService ? videoIndexerService.outputs.videoIndexerServiceName : ''
    videoIndexerSupportsPrivateEndpoints: videoIndexerSupportsPrivateEndpoints
  }
}


//=========================================================
// output values
//=========================================================


// output values required for postprovision script in azure.yaml
output var_acrName string = toLower('${appName}${environment}acr')
output var_authenticationType string = toLower(authenticationType)
output var_blobStorageEndpoint string = storageAccount.outputs.endpoint
output var_configureApplication bool = configureApplicationPermissions
#disable-next-line BCP318 // expect one value to be null
output var_contentSafetyEndpoint string = deployContentSafety ? contentSafety.outputs.contentSafetyEndpoint : ''
output var_cosmosDb_accountName string = cosmosDB.outputs.cosmosDbName
output var_cosmosDb_uri string = cosmosDB.outputs.cosmosDbUri
output var_deploymentLocation string = rg.location
output var_documentIntelligenceServiceEndpoint string = docIntel.outputs.documentIntelligenceServiceEndpoint
output var_keyVaultName string = keyVault.outputs.keyVaultName
output var_keyVaultUri string = keyVault.outputs.keyVaultUri
output var_openAIEndpoint string = openAI.outputs.openAIEndpoint
output var_openAIGPTModels array = resolvedGptModels
output var_openAIResourceGroup string = openAI.outputs.openAIResourceGroup //may be able to remove
output var_openAIEmbeddingModels array = resolvedEmbeddingModels
output var_openAISubscriptionId string = openAI.outputs.openAISubscriptionId
#disable-next-line BCP318 // expect one value to be null
output var_redisCacheHostName string = deployRedisCache ? redisCache.outputs.redisCacheHostName : ''
output var_rgName string = rgName
output var_searchServiceEndpoint string = searchService.outputs.searchServiceEndpoint
#disable-next-line BCP318 // expect one value to be null
output var_speechServiceEndpoint string = deploySpeechService ? speechService.outputs.speechServiceEndpoint : ''
output var_subscriptionId string = subscription().subscriptionId
output var_videoIndexerArmApiVersion string = resolvedVideoIndexerArmApiVersion
#disable-next-line BCP318 // expect one value to be null
output var_videoIndexerAccountId string = deployVideoIndexerService ? videoIndexerService.outputs.videoIndexerAccountId : ''
output var_videoIndexerEndpoint string = resolvedVideoIndexerEndpoint
#disable-next-line BCP318 // expect one value to be null
output var_videoIndexerName string = deployVideoIndexerService ? videoIndexerService.outputs.videoIndexerServiceName : ''

// output values required for predeploy script in azure.yaml
output var_containerRegistry string = containerRegistry
output var_imageName string = contains(imageName, ':') ? split(imageName, ':')[0] : imageName
//output var_imageTag string = split(imageName, ':')[1]
output var_imageTag string = contains(imageName, ':')
  ? split(imageName, ':')[1]
  : 'latest'

output var_webService string = appService.outputs.name

// output values required for postup script in azure.yaml
output var_enablePrivateNetworking bool = enablePrivateNetworking

