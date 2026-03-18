targetScope = 'resourceGroup'

param virtualNetworkId string
param privateEndpointSubnetId string
param privateDnsZoneConfigs object = {}

param location string
param appName string
param environment string
param tags object

param keyVaultName string
param cosmosDBName string
param acrName string
param searchServiceName string
param docIntelName string
param storageAccountName string
param openAIName string
param openAIResourceGroupName string
param openAISubscriptionId string
param webAppName string


// // redis cache
param contentSafetyName string
param speechServiceName string
param videoIndexerName string

var useExternalOpenAIResource = openAIName != '' && !empty(openAIResourceGroupName) && !empty(openAISubscriptionId)

//=========================================================
// privateDNSZoneNames
var cloudName = toLower(az.environment().name)
var privateDnsZoneData = loadJsonContent('privateDNSZones.json')

var aiSearchDnsZoneName = privateDnsZoneData[cloudName].aisearch
var blobStorageDnsZoneName = privateDnsZoneData[cloudName].blobStorage
var cognitiveServicesDnsZoneName = privateDnsZoneData[cloudName].cognitiveServices
var containerRegistryDnsZoneName = privateDnsZoneData[cloudName].containerRegistry
var cosmosDbDnsZoneName = privateDnsZoneData[cloudName].cosmosDb
var keyVaultDnsZoneName = privateDnsZoneData[cloudName].keyVault
var openAiDnsZoneName = privateDnsZoneData[cloudName].openAi
var webSitesDnsZoneName = privateDnsZoneData[cloudName].webSites
var defaultPrivateDnsZoneConfig = {
  zoneResourceId: ''
  createVNetLink: true
}
var keyVaultPrivateDnsZoneConfig = contains(privateDnsZoneConfigs, 'keyVault') ? union(defaultPrivateDnsZoneConfig, privateDnsZoneConfigs.keyVault) : defaultPrivateDnsZoneConfig
var cosmosDbPrivateDnsZoneConfig = contains(privateDnsZoneConfigs, 'cosmosDb') ? union(defaultPrivateDnsZoneConfig, privateDnsZoneConfigs.cosmosDb) : defaultPrivateDnsZoneConfig
var containerRegistryPrivateDnsZoneConfig = contains(privateDnsZoneConfigs, 'containerRegistry') ? union(defaultPrivateDnsZoneConfig, privateDnsZoneConfigs.containerRegistry) : defaultPrivateDnsZoneConfig
var aiSearchPrivateDnsZoneConfig = contains(privateDnsZoneConfigs, 'aiSearch') ? union(defaultPrivateDnsZoneConfig, privateDnsZoneConfigs.aiSearch) : defaultPrivateDnsZoneConfig
var blobStoragePrivateDnsZoneConfig = contains(privateDnsZoneConfigs, 'blobStorage') ? union(defaultPrivateDnsZoneConfig, privateDnsZoneConfigs.blobStorage) : defaultPrivateDnsZoneConfig
var cognitiveServicesPrivateDnsZoneConfig = contains(privateDnsZoneConfigs, 'cognitiveServices') ? union(defaultPrivateDnsZoneConfig, privateDnsZoneConfigs.cognitiveServices) : defaultPrivateDnsZoneConfig
var openAiPrivateDnsZoneConfig = contains(privateDnsZoneConfigs, 'openAi') ? union(defaultPrivateDnsZoneConfig, privateDnsZoneConfigs.openAi) : defaultPrivateDnsZoneConfig
var webSitesPrivateDnsZoneConfig = contains(privateDnsZoneConfigs, 'webSites') ? union(defaultPrivateDnsZoneConfig, privateDnsZoneConfigs.webSites) : defaultPrivateDnsZoneConfig

//=========================================================
// key vault
//=========================================================
resource kv 'Microsoft.KeyVault/vaults@2025-05-01' existing = {
  name: keyVaultName
}

module keyVaultDNSZone 'privateDNS.bicep' = {
  name: 'keyVaultDNSZone'
  params: {
    zoneName: keyVaultDnsZoneName
    appName: appName
    environment: environment
    name: 'kv'
    vNetId: virtualNetworkId
    tags: tags
    existingZoneResourceId: keyVaultPrivateDnsZoneConfig.zoneResourceId
    createVNetLink: keyVaultPrivateDnsZoneConfig.createVNetLink
  }
}

module keyVaultPE 'privateEndpoint.bicep' = {
  name: 'keyVaultPE'
  dependsOn: [
    kv
  ]
  params: {
    name: 'kv'
    location: location
    appName: appName
    environment: environment
    serviceResourceID: kv.id
    subnetId: privateEndpointSubnetId
    groupIDs: [
      'vault'
    ]
    privateDnsZoneIds: [
      keyVaultDNSZone.outputs.privateDnsZoneId
    ]
    tags: tags
  }
}
//=========================================================
// cosmos db
//=========================================================
resource cosmosDb 'Microsoft.DocumentDB/databaseAccounts@2023-04-15' existing = {
  name: cosmosDBName
}

module cosmosDbDNSZone 'privateDNS.bicep' = {
  name: 'cosmosDbDNSZone'
  params: {
    zoneName: cosmosDbDnsZoneName
    appName: appName
    environment: environment
    name: 'cosmosDb'
    vNetId: virtualNetworkId
    tags: tags
    existingZoneResourceId: cosmosDbPrivateDnsZoneConfig.zoneResourceId
    createVNetLink: cosmosDbPrivateDnsZoneConfig.createVNetLink
  }
}

module cosmosDbPE 'privateEndpoint.bicep' = {
  name: 'cosmosDbPE'
  dependsOn: [
    cosmosDb
  ]
  params: {
    name: 'cosmosDb'
    location: location
    appName: appName
    environment: environment
    serviceResourceID: cosmosDb.id
    subnetId: privateEndpointSubnetId
    groupIDs: [
      'sql'
    ]
    privateDnsZoneIds: [
      cosmosDbDNSZone.outputs.privateDnsZoneId
    ]
    tags: tags
  }
}
//=========================================================
// azure container registry
//=========================================================
resource acr 'Microsoft.ContainerRegistry/registries@2025-04-01' existing = {
  name: acrName
}

module acrDNSZone 'privateDNS.bicep' = {
  name: 'acrDNSZone'
  params: {
    zoneName: containerRegistryDnsZoneName
    appName: appName
    environment: environment
    name: 'acr'
    vNetId: virtualNetworkId
    tags: tags
    existingZoneResourceId: containerRegistryPrivateDnsZoneConfig.zoneResourceId
    createVNetLink: containerRegistryPrivateDnsZoneConfig.createVNetLink
  }
}

module acrPE 'privateEndpoint.bicep' = {
  name: 'acrPE'
  dependsOn: [
    acr
  ]
  params: {
    name: 'acr'
    location: location
    appName: appName
    environment: environment
    serviceResourceID: acr.id
    subnetId: privateEndpointSubnetId
    groupIDs: [
      'registry'
    ]
    privateDnsZoneIds: [
      acrDNSZone.outputs.privateDnsZoneId
    ]
    tags: tags
  }
}
//=========================================================
// search service
//=========================================================
resource searchService 'Microsoft.Search/searchServices@2025-05-01' existing = {
  name: searchServiceName
}

module searchServiceDNSZone 'privateDNS.bicep' = {
  name: 'searchServiceDNSZone'
  params: {
    zoneName: aiSearchDnsZoneName
    appName: appName
    environment: environment
    name: 'searchService'
    vNetId: virtualNetworkId
    tags: tags
    existingZoneResourceId: aiSearchPrivateDnsZoneConfig.zoneResourceId
    createVNetLink: aiSearchPrivateDnsZoneConfig.createVNetLink
  }
}

module searchServicePE 'privateEndpoint.bicep' = {
  name: 'searchServicePE'
  dependsOn: [
    searchService
  ]
  params: {
    name: 'searchService'
    location: location
    appName: appName
    environment: environment
    serviceResourceID: searchService.id
    subnetId: privateEndpointSubnetId
    groupIDs: [
      'searchService'
    ]
    privateDnsZoneIds: [
      searchServiceDNSZone.outputs.privateDnsZoneId
    ]
    tags: tags
  }
}
//=========================================================
// document intelligence service
//=========================================================
resource docIntelService 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = if (docIntelName != '') {
  name: docIntelName
}

module docIntelDNSZone 'privateDNS.bicep' = {
  name: 'docIntelDNSZone'
  params: {
    zoneName: cognitiveServicesDnsZoneName
    appName: appName
    environment: environment
    name: 'docIntelService'
    vNetId: virtualNetworkId
    tags: tags
    existingZoneResourceId: cognitiveServicesPrivateDnsZoneConfig.zoneResourceId
    createVNetLink: cognitiveServicesPrivateDnsZoneConfig.createVNetLink
  }
}

module docIntelPE 'privateEndpoint.bicep' = {
  name: 'docIntelPE'
  dependsOn: [
    docIntelService
  ]
  params: {
    name: 'docIntelService'
    location: location
    appName: appName
    environment: environment
    serviceResourceID: docIntelService.id
    subnetId: privateEndpointSubnetId
    groupIDs: [
      'account'
    ]
    privateDnsZoneIds: [
      docIntelDNSZone.outputs.privateDnsZoneId
    ]
    tags: tags
  }
}
//=========================================================
// storage account
//=========================================================
resource storageAccount 'Microsoft.Storage/storageAccounts@2022-09-01' existing = {
  name: storageAccountName
}

module storageAccountDNSZone 'privateDNS.bicep' = {
  name: 'storageAccountDNSZone'
  params: {
    zoneName: blobStorageDnsZoneName
    appName: appName
    environment: environment
    name: 'storage'
    vNetId: virtualNetworkId
    tags: tags
    existingZoneResourceId: blobStoragePrivateDnsZoneConfig.zoneResourceId
    createVNetLink: blobStoragePrivateDnsZoneConfig.createVNetLink
  }
}

module storageAccountPE 'privateEndpoint.bicep' = {
  name: 'storageAccountPE'
  dependsOn: [
    storageAccount
  ]
  params: {
    name: 'storageAccount'
    location: location
    appName: appName
    environment: environment
    serviceResourceID: storageAccount.id
    subnetId: privateEndpointSubnetId
    groupIDs: [
      'blob'
    ]
    privateDnsZoneIds: [
      storageAccountDNSZone.outputs.privateDnsZoneId
    ]
    tags: tags
  }
}
//=========================================================
resource openAiService 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = if (openAIName != '' && !useExternalOpenAIResource) {
  name: openAIName
}

resource openAiServiceExternal 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = if (useExternalOpenAIResource) {
  name: openAIName
  scope: resourceGroup(openAISubscriptionId, openAIResourceGroupName)
}

module openAiDNSZone 'privateDNS.bicep' = if (openAIName != '') {
  name: 'openAiDNSZone'
  params: {
    zoneName: openAiDnsZoneName
    appName: appName
    environment: environment
    name: 'openAiService'
    vNetId: virtualNetworkId
    tags: tags
    existingZoneResourceId: openAiPrivateDnsZoneConfig.zoneResourceId
    createVNetLink: openAiPrivateDnsZoneConfig.createVNetLink
  }
}

module openAiPE 'privateEndpoint.bicep' = if (openAIName != '') {
  name: 'openAiPE'
  dependsOn: [
  ]
  params: {
    name: 'openAiService'
    location: location
    appName: appName
    environment: environment
    serviceResourceID: useExternalOpenAIResource ? openAiServiceExternal.id : openAiService.id
    subnetId: privateEndpointSubnetId
    groupIDs: [
      'account'
    ]
    privateDnsZoneIds: [
      #disable-next-line BCP318 // module is deployed under the same condition as this private endpoint
      openAiDNSZone.outputs.privateDnsZoneId
    ]
    tags: tags
  }
}
//=========================================================
// web app
//=========================================================
resource webApp 'Microsoft.Web/sites@2022-03-01' existing = {
  name: webAppName
}

module webAppDNSZone 'privateDNS.bicep' = {
  name: 'webAppDNSZone'
  params: {
    zoneName: webSitesDnsZoneName
    appName: appName
    environment: environment
    name: 'webApp'
    vNetId: virtualNetworkId
    tags: tags
    existingZoneResourceId: webSitesPrivateDnsZoneConfig.zoneResourceId
    createVNetLink: webSitesPrivateDnsZoneConfig.createVNetLink
  }
}

module webAppPE 'privateEndpoint.bicep' = {
  name: 'webAppPE'
  dependsOn: [
    webApp
  ]
  params: {
    name: 'webApp'
    location: location
    appName: appName
    environment: environment
    serviceResourceID: webApp.id
    subnetId: privateEndpointSubnetId
    groupIDs: [
      'sites'
    ]
    privateDnsZoneIds: [
      webAppDNSZone.outputs.privateDnsZoneId
    ]
    tags: tags
  }
}
//=========================================================
// content safety service - Optional
//=========================================================
resource contentSafety 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = if (contentSafetyName != '') {
  name: contentSafetyName
}

module contentSafetyPE 'privateEndpoint.bicep' = if (contentSafetyName != '') {
  name: 'contentSafetyPE'
  dependsOn: [
    contentSafety
  ]
  params: {
    name: 'contentSafety'
    location: location
    appName: appName
    environment: environment
    serviceResourceID: contentSafety.id
    subnetId: privateEndpointSubnetId
    groupIDs: [
      'account'
    ]
    privateDnsZoneIds: [
      docIntelDNSZone.outputs.privateDnsZoneId
    ]
    tags: tags
  }
}
//=========================================================
// speech service - Optional
//=========================================================
resource speechService 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = if (speechServiceName != '') {
  name: speechServiceName
}

module speechServicePE 'privateEndpoint.bicep' = if (speechServiceName != '') {
  name: 'speechServicePE'
  dependsOn: [
    speechService
  ]
  params: {
    name: 'speechService'
    location: location
    appName: appName
    environment: environment
    serviceResourceID: speechService.id
    subnetId: privateEndpointSubnetId
    groupIDs: [
      'account'
    ]
    privateDnsZoneIds: [
      docIntelDNSZone.outputs.privateDnsZoneId
    ]
    tags: tags
  }
}
//=========================================================
// video indexer service - Optional
//=========================================================
resource videoIndexerService 'Microsoft.VideoIndexer/accounts@2025-04-01' existing = if (videoIndexerName != '') {
  name: videoIndexerName
}

module videoIndexerPE 'privateEndpoint.bicep' = if (videoIndexerName != '') {
  name: 'videoIndexerPE'
  dependsOn: [
    videoIndexerService
  ]
  params: {
    name: 'videoIndexerService'
    location: location
    appName: appName
    environment: environment
    serviceResourceID: videoIndexerService.id
    subnetId: privateEndpointSubnetId
    groupIDs: [
      'account'
    ]
    privateDnsZoneIds: [
      docIntelDNSZone.outputs.privateDnsZoneId
    ]
    tags: tags
  }
}
