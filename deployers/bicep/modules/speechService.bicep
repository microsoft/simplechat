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
module diagnosticConfigs 'diagnosticSettings.bicep' = if (enableDiagLogging){
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
    type: 'SystemAssigned, UserAssigned'
    userAssignedIdentities: {
      '${managedIdentityId}': {}
    }
  }
  properties: {
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: false
    customSubDomainName: toLower('${appName}-${environment}-speech')
  }
  tags: tags
}

// grant the managed identity access to speech service as a Cognitive Services User
resource speechServiceUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(speechService.id, managedIdentityId, 'speech-service-user')
  scope: speechService
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      'a97b65f3-24c7-4388-baec-2e87135dc908'
    )
    principalId: managedIdentityPrincipalId
    principalType: 'ServicePrincipal'
  }
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

output speechServiceName string = speechService.name
