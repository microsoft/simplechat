targetScope = 'resourceGroup'

param location string
param appName string
param environment string
param tags object

param enableDiagLogging bool
param logAnalyticsId string

param enablePrivateNetworking bool

@allowed([
  'free'
  'basic'
  'standard'
  'standard2'
  'standard3'
  'storage_optimized_l1'
  'storage_optimized_l2'
])
param skuName string = 'standard'

@allowed([
  'free'
  'standard'
])
param semanticSearchSku string = 'standard'

// Import diagnostic settings configurations
module diagnosticConfigs 'diagnosticSettings.bicep' = if (enableDiagLogging) {
  name: 'diagnosticConfigs'
}

// search service resource
resource searchService 'Microsoft.Search/searchServices@2025-05-01' = {
  name: toLower('${appName}-${environment}-search')
  location: location
  sku: {
    name: skuName
  }
  properties: {
    #disable-next-line BCP036 // template is incorrect 
    hostingMode: 'default'
    #disable-next-line BCP037 // 2025-05-01 supports semanticSearch even when local Bicep types lag
    semanticSearch: semanticSearchSku
    publicNetworkAccess: enablePrivateNetworking ? 'Disabled' : 'Enabled'
    replicaCount: 1
    partitionCount: 1
    authOptions: {
      aadOrApiKey: {aadAuthFailureMode: 'http403' }
    } 
    disableLocalAuth: false
  }
  tags: tags
}

// configure diagnostic settings for search service
resource searchDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (enableDiagLogging) {
  name: toLower('${searchService.name}-diagnostics')
  scope: searchService
  properties: {
    workspaceId: logAnalyticsId
    #disable-next-line BCP318 // expect one value to be null
    logs: diagnosticConfigs.outputs.standardLogCategories
    #disable-next-line BCP318 // expect one value to be null
    metrics: diagnosticConfigs.outputs.standardMetricsCategories
  }
}

output searchServiceName string = searchService.name
output searchServiceEndpoint string = searchService.properties.endpoint
