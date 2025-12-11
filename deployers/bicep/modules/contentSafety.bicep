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
    customSubDomainName: toLower('${appName}-${environment}-contentsafety')
  }
  tags: tags
}

// configure diagnostic settings for content safety
resource contentSafetyDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (enableDiagLogging) {
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

//=========================================================
// store contentSafety keys in key vault if using key authentication and configure app permissions = true
//=========================================================
module contentSafetySecret 'keyVault-Secrets.bicep' = if (authenticationType == 'key' && configureApplicationPermissions) {
  name: 'storeContentSafetySecret'
  params: {
    keyVaultName: keyVault
    secretName: 'content-safety-key'
    secretValue: contentSafety.listKeys().key1
  }
}

output contentSafetyName string = contentSafety.name
output contentSafetyEndpoint string = contentSafety.properties.endpoint
