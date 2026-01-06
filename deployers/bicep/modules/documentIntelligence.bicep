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

param vNetId string = ''
param privateEndpointSubnetId string = ''

// Import diagnostic settings configurations
module diagnosticConfigs 'diagnosticSettings.bicep' = if (enableDiagLogging) {
  name: 'diagnosticConfigs'
}

// create private endpoint for azure document intelligence if private endpoint subnet id is provided
module privateEndpoint 'privateEndpoint.bicep' = if (privateEndpointSubnetId != '') {
  name: toLower('${appName}-${environment}-docintel-pe')
  dependsOn:[
    docIntel
  ]
  params: {
    name: 'docintel'
    location: location
    appName: appName
    environment: environment
    privateDNSZoneName: 'privatelink.cognitiveservices.azure.com'
    vNetId: vNetId
    subnetId: privateEndpointSubnetId
    serviceResourceID: docIntel.id
    groupIDs: [
      'account'
    ]
    tags: tags
  }
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
    publicNetworkAccess: privateEndpointSubnetId != '' ? 'Disabled' : 'Enabled'
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
