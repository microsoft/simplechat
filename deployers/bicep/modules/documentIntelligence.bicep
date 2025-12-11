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

// document intelligence resource
resource docIntel 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: toLower('${appName}-${environment}-docintel')
  location: location
  kind: 'FormRecognizer'
  sku: {
    name: 'S0'
  }
  properties: {
    publicNetworkAccess: 'Enabled'
    customSubDomainName: toLower('${appName}-${environment}-docintel')
  }
  tags: tags
}

// configure diagnostic settings for document intelligence
resource docIntelDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (enableDiagLogging) {
  name: toLower('${docIntel.name}-diagnostics')
  scope: docIntel
  properties: {
    workspaceId: logAnalyticsId
    #disable-next-line BCP318 // expect one value to be null
    logs: diagnosticConfigs.outputs.standardLogCategories
    #disable-next-line BCP318 // expect one value to be null
    metrics: diagnosticConfigs.outputs.standardMetricsCategories
  }
}

//=========================================================
// store document intelligence keys in key vault if using key authentication and configure app permissions = true
//=========================================================
module documentIntelligenceSecret 'keyVault-Secrets.bicep' = if (authenticationType == 'key' && configureApplicationPermissions) {
  name: 'storeDocumentIntelligenceSecret'
  params: {
    keyVaultName: keyVault
    secretName: 'document-intelligence-key'
    secretValue: docIntel.listKeys().key1
  }
}

output documentIntelligenceServiceName string = docIntel.name
output diagnosticLoggingEnabled bool = enableDiagLogging
output documentIntelligenceServiceEndpoint string = docIntel.properties.endpoint
