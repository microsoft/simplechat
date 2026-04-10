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
      resourceId: storage.id
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
      resourceId: storage.id
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
