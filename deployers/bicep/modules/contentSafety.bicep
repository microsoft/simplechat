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

// deploy content safety resource if required
resource contentSafety 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: toLower('${appName}-${environment}-contentsafety')
  location: location
  kind: 'ContentSafety'
  sku: {
    name: 'S0'
  }
  properties: {
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: false
    customSubDomainName: toLower('${appName}-${environment}-contentsafety')
  }
  tags: tags
}

// grant the managed identity access to content safety as a Cognitive Services User
resource contentSafetyUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(contentSafety.id, managedIdentityId, 'content-safety-user')
  scope: contentSafety
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      'a97b65f3-24c7-4388-baec-2e87135dc908'
    )
    principalId: managedIdentityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// configure diagnostic settings for content safety
resource contentSafetyDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (enableDiagLogging)  {
  name: toLower('${contentSafety.name}-diagnostics')
  scope: contentSafety
  properties: {
    workspaceId: logAnalyticsId
    #disable-next-line BCP318 // expect one value to be null
    logs: diagnosticConfigs.outputs.standardLogCategories
    #disable-next-line BCP318 // expect one value to be null
    metrics: diagnosticConfigs.outputs.standardMetricsCategories
  }
}

output contentSafetyName string = contentSafety.name
output contentSafetyEndpoint string = contentSafety.properties.endpoint
