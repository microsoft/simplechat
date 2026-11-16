targetScope = 'resourceGroup'

param location string
param appName string
param environment string
param tags object

param enableDiagLogging bool
param logAnalyticsId string

param storageAccount string
param openAiServiceName string
param videoIndexerArmApiVersion string

@description('''Create a storage account in the Video Indexer region instead of using the application storage account.
- Set when Video Indexer is deployed to a different region than the application.''')
param useDedicatedStorageAccount bool = false

param enablePrivateNetworking bool

// Import diagnostic settings configurations
module diagnosticConfigs 'diagnosticSettings.bicep' = if (enableDiagLogging) {
  name: 'diagnosticConfigs'
}

resource storage 'Microsoft.Storage/storageAccounts@2021-09-01' existing = {
  name: storageAccount
}

resource openAiService 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: openAiServiceName
}

var dedicatedStorageAccountName = toLower('${appName}${environment}vi')

// Video Indexer keeps its media in a storage account in its own region, so a Video Indexer
// region that differs from the application region gets its own Standard GPv2 account.
resource videoIndexerStorage 'Microsoft.Storage/storageAccounts@2022-09-01' = if (useDedicatedStorageAccount) {
  #disable-next-line BCP334 //Name length managed by Bicep parameters.
  name: dedicatedStorageAccountName
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    // Only Video Indexer uses this account, and it connects as a trusted Azure service. A disabled
    // public endpoint would also block that path, so private networking denies all other traffic instead.
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: enablePrivateNetworking ? 'Deny' : 'Allow'
    }
  }
  tags: tags
}

resource videoIndexerStorageBlobService 'Microsoft.Storage/storageAccounts/blobServices@2023-01-01' = if (useDedicatedStorageAccount) {
  name: 'default'
  parent: videoIndexerStorage
}

resource videoIndexerStorageDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (enableDiagLogging && useDedicatedStorageAccount) {
  name: '${dedicatedStorageAccountName}-diagnostics'
  scope: videoIndexerStorage
  properties: {
    workspaceId: logAnalyticsId
    logs: [] // Storage account main resource doesn't have logs
    #disable-next-line BCP318 // expect one value to be null
    metrics: diagnosticConfigs.outputs.transactionMetricsCategories
  }
}

resource videoIndexerStorageBlobDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (enableDiagLogging && useDedicatedStorageAccount) {
  name: '${dedicatedStorageAccountName}-blob-diagnostics'
  scope: videoIndexerStorageBlobService
  properties: {
    workspaceId: logAnalyticsId
    #disable-next-line BCP318 // expect one value to be null
    logs: diagnosticConfigs.outputs.standardLogCategories
    #disable-next-line BCP318 // expect one value to be null
    metrics: diagnosticConfigs.outputs.transactionMetricsCategories
  }
}

#disable-next-line BCP318 // the dedicated account exists whenever it is selected
var videoIndexerStorageAccountId = useDedicatedStorageAccount ? videoIndexerStorage.id : storage.id

var useLegacyVideoIndexerApi = videoIndexerArmApiVersion == '2024-01-01'

resource videoIndexerServiceCurrent 'Microsoft.VideoIndexer/accounts@2025-04-01' = if (!useLegacyVideoIndexerApi) {
  name: toLower('${appName}-${environment}-video')
  location: location

  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    publicNetworkAccess: enablePrivateNetworking ? 'Disabled' : 'Enabled'
    storageServices: {
      resourceId: videoIndexerStorageAccountId
    }
    openAiServices: {
      resourceId: openAiService.id
    }
  }
  tags: tags
  dependsOn: [
    storage
    openAiService
  ]
}

resource videoIndexerServiceLegacy 'Microsoft.VideoIndexer/accounts@2024-01-01' = if (useLegacyVideoIndexerApi) {
  name: toLower('${appName}-${environment}-video')
  location: location

  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    storageServices: {
      resourceId: videoIndexerStorageAccountId
    }
  }
  tags: tags
  dependsOn: [
    storage
  ]
}

// configure diagnostic settings for video indexer service
resource videoIndexerServiceCurrentDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (enableDiagLogging && !useLegacyVideoIndexerApi) {
  name: toLower('${videoIndexerServiceCurrent.name}-diagnostics')
  scope: videoIndexerServiceCurrent
  properties: {
    workspaceId: logAnalyticsId
    #disable-next-line BCP318 // expect one value to be null
    logs: diagnosticConfigs.outputs.limitedLogCategories
  }
}

resource videoIndexerServiceLegacyDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (enableDiagLogging && useLegacyVideoIndexerApi) {
  name: toLower('${videoIndexerServiceLegacy.name}-diagnostics')
  scope: videoIndexerServiceLegacy
  properties: {
    workspaceId: logAnalyticsId
    #disable-next-line BCP318 // expect one value to be null
    logs: diagnosticConfigs.outputs.limitedLogCategories
  }
}

#disable-next-line BCP318 // exactly one conditional resource exists for the selected API version
output videoIndexerServiceName string = useLegacyVideoIndexerApi ? videoIndexerServiceLegacy.name : videoIndexerServiceCurrent.name
#disable-next-line BCP318 // exactly one conditional resource exists for the selected API version
output videoIndexerAccountId string = useLegacyVideoIndexerApi ? videoIndexerServiceLegacy.properties.accountId : videoIndexerServiceCurrent.properties.accountId
// SimpleChat builds Video Indexer API URLs from this region name, so return it in ARM's normalized form.
output videoIndexerLocation string = toLower(replace(location, ' ', ''))
output videoIndexerStorageAccountName string = useDedicatedStorageAccount ? dedicatedStorageAccountName : storage.name
