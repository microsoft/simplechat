targetScope = 'resourceGroup'

param location string
param appName string
param environment string
param tags object

param enableDiagLogging bool
param logAnalyticsId string

param vNetId string = ''
param privateEndpointSubnetId string = ''

// Import diagnostic settings configurations
module diagnosticConfigs 'diagnosticSettings.bicep' = if (enableDiagLogging) {
  name: 'diagnosticConfigs'
}

// create private endpoint for key vault if private endpoint subnet id is provided
module privateEndpoint 'privateEndpoint.bicep' = if (privateEndpointSubnetId != '') {
  name: toLower('${appName}-${environment}-kv-pe')
  dependsOn:[
    kv
  ]
  params: {
    name: 'kv'
    location: location
    appName: appName
    environment: environment
    privateDNSZoneName: 'privatelink.vaultcore.azure.net'
    vNetId: vNetId
    subnetId: privateEndpointSubnetId
    serviceResourceID: kv.id
    groupIDs: [
      'vault'
    ]
    tags: tags
  }
}

// key vault resource 
resource kv 'Microsoft.KeyVault/vaults@2024-11-01' = {
  name: toLower('${appName}-${environment}-kv')
  location: location
  properties: {
    tenantId: subscription().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    accessPolicies: []
    enabledForDeployment: false
    enabledForDiskEncryption: false
    enabledForTemplateDeployment: false
    publicNetworkAccess: privateEndpointSubnetId != '' ? 'Disabled' : 'Enabled'
    enableRbacAuthorization: true
  }
  tags: tags
}

// configure diagnostic settings for key vault
resource kvDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (enableDiagLogging) {
  name: toLower('${kv.name}-diagnostics')
  scope: kv
  properties: {
    workspaceId: logAnalyticsId
    #disable-next-line BCP318 // expect one value to be null
    logs: diagnosticConfigs.outputs.standardLogCategories
    #disable-next-line BCP318 // expect one value to be null
    metrics: diagnosticConfigs.outputs.standardMetricsCategories
  }
}

output keyVaultId string = kv.id
output keyVaultName string = kv.name
output keyVaultUri string = kv.properties.vaultUri
