targetScope = 'resourceGroup'

param location string
param appName string
param environment string
param tags object

//param managedIdentityPrincipalId string
//param managedIdentityId string
param enableDiagLogging bool
param logAnalyticsId string

// Import diagnostic settings configurations
module diagnosticConfigs 'diagnosticSettings.bicep' = {
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

// todo: grant the managed identity access to content safety as a Cognitive Services User
/*
resource contentSafetyUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (deployContentSafety) {
  name: guid(contentSafety.id, managedIdentity.id, 'content-safety-user')
  scope: contentSafety
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      'a97b65f3-24c7-4388-baec-2e87135dc908'
    )
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}
*/

// configure diagnostic settings for redis cache
resource redisCacheDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (enableDiagLogging) {
  name: toLower('${redisCache.name}-diagnostics')
  scope: redisCache
  properties: {
    workspaceId: logAnalyticsId
    logs: diagnosticConfigs.outputs.standardLogCategories
    metrics: diagnosticConfigs.outputs.standardMetricsCategories
  }
}
