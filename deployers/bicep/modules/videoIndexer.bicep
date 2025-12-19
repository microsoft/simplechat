targetScope = 'resourceGroup'

param location string
param appName string
param environment string
param tags object

param enableDiagLogging bool
param logAnalyticsId string

param storageAccount string
param openAiServiceName string

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

// deploy video indexer service if required
resource videoIndexerService 'Microsoft.VideoIndexer/accounts@2025-04-01' = {
  name: toLower('${appName}-${environment}-video')
  location: location

  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    publicNetworkAccess: 'Enabled'
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

// configure diagnostic settings for video indexer service
resource videoIndexerServiceDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (enableDiagLogging) {
  name: toLower('${videoIndexerService.name}-diagnostics')
  scope: videoIndexerService
  properties: {
    workspaceId: logAnalyticsId
    #disable-next-line BCP318 // expect one value to be null
    logs: diagnosticConfigs.outputs.limitedLogCategories
  }
}

output videoIndexerServiceName string = videoIndexerService.name
output videoIndexerAccountId string = videoIndexerService.properties.accountId
