targetScope = 'resourceGroup'

param nativeWebAppName string
param authenticationType string

@allowed([
  'key'
  'managed_identity'
])
param redisAuthenticationType string = authenticationType

param keyVaultName string
param cosmosDBName string
param openAIName string
param openAIResourceGroupName string
param openAISubscriptionId string
param docIntelName string
param storageAccountName string
param speechServiceName string
param searchServiceName string
param redisCacheName string
param contentSafetyName string

var useExternalOpenAIResource = openAIName != '' && !empty(openAIResourceGroupName) && !empty(openAISubscriptionId)

resource webApp 'Microsoft.Web/sites@2022-03-01' existing = {
  name: nativeWebAppName
}

resource kv 'Microsoft.KeyVault/vaults@2025-05-01' existing = {
  name: keyVaultName
}

resource cosmosDb 'Microsoft.DocumentDB/databaseAccounts@2023-04-15' existing = {
  name: cosmosDBName
}

resource openAiService 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = if (openAIName != '' && !useExternalOpenAIResource) {
  name: openAIName
}

resource docIntelService 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = if (docIntelName != '') {
  name: docIntelName
}

resource storageAccount 'Microsoft.Storage/storageAccounts@2022-09-01' existing = {
  name: storageAccountName
}

resource speechService 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = if (speechServiceName != '') {
  name: speechServiceName
}

resource searchService 'Microsoft.Search/searchServices@2025-05-01' existing = {
  name: searchServiceName
}

resource redisCache 'Microsoft.Cache/Redis@2024-11-01' existing = if (redisCacheName != '') {
  name: redisCacheName
}

resource contentSafety 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = if (contentSafetyName != '') {
  name: contentSafetyName
}

resource kvSecretsUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(kv.id, webApp.id, 'kv-secrets-user')
  scope: kv
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '4633458b-17de-408a-b874-0445c86b69e6'
    )
    principalId: webApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource cosmosContributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (authenticationType == 'managed_identity') {
  name: guid(cosmosDb.id, webApp.id, 'cosmos-contributor')
  scope: cosmosDb
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      'b24988ac-6180-42a0-ab88-20f7382dd24c'
    )
    principalId: webApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource cosmosThroughputOperatorRoleDefinition 'Microsoft.Authorization/roleDefinitions@2022-04-01' existing = {
  name: guid(resourceGroup().id, 'simplechat-cosmos-throughput-operator')
}

resource cosmosThroughputOperatorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(cosmosDb.id, webApp.id, 'cosmos-throughput-operator')
  scope: cosmosDb
  properties: {
    roleDefinitionId: cosmosThroughputOperatorRoleDefinition.id
    principalId: webApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource cosmosDataContributorRole 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2023-04-15' = if (authenticationType == 'managed_identity') {
  name: guid(cosmosDb.id, webApp.id, 'cosmos-data-contributor')
  parent: cosmosDb
  properties: {
    roleDefinitionId: '${cosmosDb.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002'
    principalId: webApp.identity.principalId
    scope: cosmosDb.id
  }
}

resource openAIUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (authenticationType == 'managed_identity' && openAIName != '' && !useExternalOpenAIResource) {
  scope: openAiService
  name: guid(openAiService.id, webApp.id, 'openai-user')
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
    )
    principalId: webApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

module openAIExternalPermissions 'setPermissions-openAIExternal.bicep' = if (useExternalOpenAIResource) {
  name: 'nativeOpenAIExternalPermissions'
  scope: resourceGroup(openAISubscriptionId, openAIResourceGroupName)
  params: {
    openAIName: openAIName
    authenticationType: authenticationType
    webAppPrincipalId: webApp.identity.principalId
    enterpriseAppServicePrincipalId: ''
    videoIndexerPrincipalId: ''
    videoIndexerName: ''
    videoIndexerSupportsOpenAiIntegration: false
  }
}

resource docIntelUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (authenticationType == 'managed_identity') {
  name: guid(docIntelService.id, webApp.id, 'doc-intel-user')
  scope: docIntelService
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      'a97b65f3-24c7-4388-baec-2e87135dc908'
    )
    principalId: webApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource storageBlobDataContributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (authenticationType == 'managed_identity') {
  name: guid(storageAccount.id, webApp.id, 'storage-blob-data-contributor')
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
    )
    principalId: webApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource speechServiceUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (speechServiceName != '' && authenticationType == 'managed_identity') {
  name: guid(speechService.id, webApp.id, 'speech-service-user')
  scope: speechService
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      'a97b65f3-24c7-4388-baec-2e87135dc908'
    )
    principalId: webApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource searchIndexDataContributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (authenticationType == 'managed_identity') {
  name: guid(searchService.id, webApp.id, 'search-index-data-contributor')
  scope: searchService
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
    )
    principalId: webApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource searchServiceContributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (authenticationType == 'managed_identity') {
  name: guid(searchService.id, webApp.id, 'search-service-contributor')
  scope: searchService
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '7ca78c08-252a-4471-8644-bb5ff32d4ba0'
    )
    principalId: webApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource contentSafetyUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (contentSafetyName != '' && authenticationType == 'managed_identity') {
  name: guid(contentSafety.id, webApp.id, 'content-safety-user')
  scope: contentSafety
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      'a97b65f3-24c7-4388-baec-2e87135dc908'
    )
    principalId: webApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource redisCacheContributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (redisCacheName != '' && redisAuthenticationType == 'managed_identity') {
  name: guid(redisCache.id, webApp.id, 'redis-cache-contributor')
  scope: redisCache
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      'e0f68234-74aa-48ed-b826-c38b57376e17'
    )
    principalId: webApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource redisCacheDataContributorAccessPolicy 'Microsoft.Cache/Redis/accessPolicyAssignments@2024-11-01' = if (redisCacheName != '' && redisAuthenticationType == 'managed_identity') {
  parent: redisCache
  name: 'native-webapp-mi-data-contributor'
  properties: {
    accessPolicyName: 'Data Contributor'
    objectId: webApp.identity.principalId
    objectIdAlias: webApp.identity.principalId
  }
}
