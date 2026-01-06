targetScope = 'resourceGroup'

param location string
param acrName string
param tags object

param enableDiagLogging bool
param logAnalyticsId string

param keyVault string
param authenticationType string
param configureApplicationPermissions bool

param appName string
param environment string
param vNetId string = ''
param privateEndpointSubnetId string = ''

// Import diagnostic settings configurations
module diagnosticConfigs 'diagnosticSettings.bicep' = if (enableDiagLogging) {
  name: 'diagnosticConfigs'
}

// create private endpoint for azure container registry if private endpoint subnet id is provided
module privateEndpoint 'privateEndpoint.bicep' = if (privateEndpointSubnetId != '') {
  name: toLower('${appName}-${environment}-acr-pe')
  dependsOn:[
    acr
  ]
  params: {
    name: 'acr'
    location: location
    appName: appName
    environment: environment
    privateDNSZoneName: 'privatelink.azurecr.io'
    vNetId: vNetId
    subnetId: privateEndpointSubnetId
    serviceResourceID: acr.id
    groupIDs: [
      'registry'
    ]
    tags: tags
  }
}

// azure container registry
resource acr 'Microsoft.ContainerRegistry/registries@2025-04-01' = {
  name: acrName
  location: location

  sku: {
    name: privateEndpointSubnetId != '' ? 'Premium' : 'Standard'
  }
  properties: {
    adminUserEnabled: true
    publicNetworkAccess: privateEndpointSubnetId != '' ? 'Disabled' : 'Enabled'
  }
  tags: tags
}

//=========================================================
// store container registry keys in key vault if using key authentication and configure app permissions = true
//=========================================================
module containerRegistrySecret 'keyVault-Secrets.bicep' = if (authenticationType == 'key' && configureApplicationPermissions) {
  name: 'storeContainerRegistrySecret'
  params: {
    keyVaultName: keyVault
    secretName: 'container-registry-key'
    secretValue: acr.listCredentials().passwords[0].value
  }
}

// configure diagnostic settings for azure container registry
resource acrDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (enableDiagLogging) {
  name: toLower('${acr.name}-diagnostics')
  scope: acr
  properties: {
    workspaceId: logAnalyticsId
    #disable-next-line BCP318 // expect one value to be null
    logs: diagnosticConfigs.outputs.standardLogCategories
    #disable-next-line BCP318 // expect one value to be null
    metrics: diagnosticConfigs.outputs.standardMetricsCategories
  }
}

output acrName string = acr.name
output acrResourceGroup string = resourceGroup().name
