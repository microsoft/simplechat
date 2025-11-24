targetScope = 'resourceGroup'

param location string
param appName string
param environment string
param tags object

param managedIdentityPrincipalId string
param managedIdentityId string
param enableDiagLogging bool
param logAnalyticsId string

// Import diagnostic settings configurations
module diagnosticConfigs 'diagnosticSettings.bicep' = if (enableDiagLogging) {
  name: 'diagnosticConfigs'
}

// search service resource
resource searchService 'Microsoft.Search/searchServices@2025-05-01' = {
  name: toLower('${appName}-${environment}-search')
  location: location
  sku: {
    name: 'basic'
  }
  properties: {
    hostingMode: 'default'
    publicNetworkAccess: 'Enabled'
    replicaCount: 1
    partitionCount: 1
  }
  tags: tags
}

// grant the managed identity access to search service as a search index data contributor
resource searchContributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(searchService.id, managedIdentityId, 'search-contributor')
  scope: searchService
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
    )
    principalId: managedIdentityPrincipalId
    principalType: 'ServicePrincipal'
  }
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
