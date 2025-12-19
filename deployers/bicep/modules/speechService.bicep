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

// deploy speech service if required
resource speechService 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: toLower('${appName}-${environment}-speech')
  location: location
  kind: 'SpeechServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    publicNetworkAccess: 'Enabled'
    customSubDomainName: toLower('${appName}-${environment}-speech')
  }
  tags: tags
}

// configure diagnostic settings for speech service
resource speechServiceDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (enableDiagLogging) {
  name: toLower('${speechService.name}-diagnostics')
  scope: speechService
  properties: {
    workspaceId: logAnalyticsId
    #disable-next-line BCP318 // expect one value to be null
    logs: diagnosticConfigs.outputs.standardLogCategories
    #disable-next-line BCP318 // expect one value to be null
    metrics: diagnosticConfigs.outputs.standardMetricsCategories
  }
}

//=========================================================
// store speech Service keys in key vault if using key authentication and configure app permissions = true
//=========================================================
module speechServiceSecret 'keyVault-Secrets.bicep' = if ((authenticationType == 'key') && (configureApplicationPermissions)) {
  name: 'storeSpeechServiceSecret'
  params: {
    keyVaultName: keyVault
    secretName: 'speech-service-key'
    secretValue: speechService.listKeys().key1
  }
}

output speechServiceName string = speechService.name
output speechServiceEndpoint string = speechService.properties.endpoint
output speechServiceAuthenticationType string = authenticationType
