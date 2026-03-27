targetScope = 'resourceGroup'

param openAIName string
param authenticationType string
param webAppPrincipalId string
param enterpriseAppServicePrincipalId string
param videoIndexerPrincipalId string = ''
param videoIndexerName string = ''
param videoIndexerSupportsOpenAiIntegration bool = true

resource openAiService 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: openAIName
}

resource openAIUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (authenticationType == 'managed_identity') {
  scope: openAiService
  name: guid(openAiService.id, webAppPrincipalId, 'openai-user')
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
    )
    principalId: webAppPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource openAIenterpriseAppUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (authenticationType == 'managed_identity') {
  scope: openAiService
  name: guid(openAiService.id, enterpriseAppServicePrincipalId, 'enterpriseApp-CognitiveServicesOpenAIUserRole')
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
    )
    principalId: enterpriseAppServicePrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource videoIndexerStorageCogServicesContributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (videoIndexerName != '' && !empty(videoIndexerPrincipalId) && videoIndexerSupportsOpenAiIntegration) {
  name: guid(openAiService.id, videoIndexerPrincipalId, 'video-indexer-cog-services-contributor')
  scope: openAiService
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '25fbc0a9-bd7c-42a3-aa1a-3b75d497ee68'
    )
    principalId: videoIndexerPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource videoIndexerStorageCogServicesUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (videoIndexerName != '' && !empty(videoIndexerPrincipalId) && videoIndexerSupportsOpenAiIntegration) {
  name: guid(openAiService.id, videoIndexerPrincipalId, 'video-indexer-cog-services-user')
  scope: openAiService
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      'a97b65f3-24c7-4388-baec-2e87135dc908'
    )
    principalId: videoIndexerPrincipalId
    principalType: 'ServicePrincipal'
  }
}
