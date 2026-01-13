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

// deploy redis cache if required
resource redisCache 'Microsoft.Cache/Redis@2024-11-01' = {
  name: toLower('${appName}-${environment}-redis')
  location: location
  properties: {
    sku: {
      name: 'Standard'
      family: 'C'
      capacity: 0
    }
    enableNonSslPort: false
    minimumTlsVersion: '1.2'
    redisConfiguration: {
      'aad-enabled': 'true'
    }
  }
  tags: tags
}

// configure diagnostic settings for redis cache
resource redisCacheDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (enableDiagLogging) {
  name: toLower('${redisCache.name}-diagnostics')
  scope: redisCache
  properties: {
    workspaceId: logAnalyticsId
    #disable-next-line BCP318 // expect one value to be null
    logs: diagnosticConfigs.outputs.standardLogCategories
    #disable-next-line BCP318 // expect one value to be null
    metrics: diagnosticConfigs.outputs.standardMetricsCategories
  }
}

//=========================================================
// store redis cache keys in key vault if using key authentication and configure app permissions = true
//=========================================================
module redisCacheSecret 'keyVault-Secrets.bicep' = if (authenticationType == 'key' && configureApplicationPermissions) {
  name: 'storeRedisCacheSecret'
  params: {
    keyVaultName: keyVault
    secretName: 'redis-cache-key'
    secretValue: redisCache.listKeys().primaryKey
  }
}

output redisCacheName string = redisCache.name
