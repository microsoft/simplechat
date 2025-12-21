targetScope = 'resourceGroup'

param location string
param appName string
param environment string
param tags object

param enableDiagLogging bool
param logAnalyticsId string

param keyVault string
param authenticationType string
param configureApplicationPermissions bool

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
    #disable-next-line BCP036 // template is incorrect 
    hostingMode: 'default'
    publicNetworkAccess: 'Enabled'
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

//=========================================================
// store search Service keys in key vault if using key authentication and configure app permissions = true
//=========================================================
module searchServiceSecret 'keyVault-Secrets.bicep' = if (configureApplicationPermissions) {
  name: 'storeSearchServiceSecret'
  params: {
    keyVaultName: keyVault
    secretName: 'search-service-key'
    secretValue: searchService.listAdminKeys().primaryKey
  }
}

output searchServiceName string = searchService.name
output searchServiceEndpoint string = searchService.properties.endpoint
output searchServiceAuthencationType string = authenticationType
