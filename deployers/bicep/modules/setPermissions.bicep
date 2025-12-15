targetScope = 'resourceGroup'

param webAppName string
param authenticationType string
param keyVaultName string
param enterpriseAppServicePrincipalId string
param cosmosDBName string
param acrName string
param openAIName string
param docIntelName string
param storageAccountName string
param speechServiceName string
param searchServiceName string
param contentSafetyName string
param videoIndexerName string

resource webApp 'Microsoft.Web/sites@2022-03-01' existing = {
  name: webAppName
}

resource kv 'Microsoft.KeyVault/vaults@2025-05-01' existing = {
  name: keyVaultName
}

resource cosmosDb 'Microsoft.DocumentDB/databaseAccounts@2023-04-15' existing = {
  name: cosmosDBName
}

resource acr 'Microsoft.ContainerRegistry/registries@2025-04-01' existing = {
  name: acrName
}

resource openAiService 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
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

resource contentSafety 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = if (contentSafetyName != '') {
  name: contentSafetyName
}

resource videoIndexerService 'Microsoft.VideoIndexer/accounts@2025-04-01' existing = if (videoIndexerName != '') {
  name: videoIndexerName
}

// grant the webApp access to the key vault
resource kvSecretsUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(kv.id, webApp.id, 'kv-secrets-user')
  scope: kv
  properties: {
    // Built-in role definition id for "Key Vault Secrets User"
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '4633458b-17de-408a-b874-0445c86b69e6'
    )
    principalId: webApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// grant the webApp access to cosmos db as a contributor
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

// Grant the managed identity Cosmos DB Built-in Data Contributor role
resource cosmosDataContributorRole 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2023-04-15' = if (authenticationType == 'managed_identity') {
  name: guid(cosmosDb.id, webApp.id, 'cosmos-data-contributor')
  parent: cosmosDb
  properties: {
    // Cosmos DB Built-in Data Contributor role definition ID
    roleDefinitionId: '${cosmosDb.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002'
    principalId: webApp.identity.principalId
    scope: cosmosDb.id
  }
}

// grant the webApp access to the ACR with acrpull role
resource acrPullRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, webApp.id, 'acr-pull-role')
  scope: acr
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '7f951dda-4ed3-4680-a7ca-43fe172d538d' // ACR Pull role
    )
    principalId: webApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// Grant the openai service access cognitive services openai user
resource openAIUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (authenticationType == 'managed_identity') {
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

// Grant the enterprise application access to the cognitive services openai user
resource openAIenterpriseAppUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (authenticationType == 'managed_identity') {
  scope: openAiService
  name: guid(openAiService.id, webApp.id, 'enterpriseApp-CognitiveServicesOpenAIUserRole')
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
    )
    principalId: enterpriseAppServicePrincipalId
    principalType: 'ServicePrincipal'
  }
}

// grant the managed identity access to document intelligence as a Cognitive Services User
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

// grant the managed identity access to the storage account as a blob data contributor
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

// grant the managed identity access to speech service as a Cognitive Services User
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

// grant the managed identity access to search service as a Search Service Contributor
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

// grant the managed identity access to search service as a Search Service Contributor
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

// grant the managed identity access to content safety as a Cognitive Services User
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

// grant the video indexer service access to storage account as a Storage Blob Data Contributor
resource videoIndexerStorageBlobDataContributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (videoIndexerName != '') {
  name: guid(storageAccount.id, videoIndexerService.id, 'video-indexer-storage-blob-data-contributor')
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
    )
    #disable-next-line BCP318 // may be null if video indexer not deployed
    principalId: videoIndexerService.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// grant the video indexer service access to OpenAI service as cognitive services Contributor
resource videoIndexerStorageCogServicesContributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (videoIndexerName != '') {
  name: guid(openAiService.id, videoIndexerService.id, 'video-indexer-cog-services-contributor')
  scope: openAiService
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '25fbc0a9-bd7c-42a3-aa1a-3b75d497ee68'
    )
    #disable-next-line BCP318 // may be null if video indexer not deployed
    principalId: videoIndexerService.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// grant the video indexer service access to OpenAI service as cognitive services user
resource videoIndexerStorageCogServicesUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (videoIndexerName != '') {
  name: guid(openAiService.id, videoIndexerService.id, 'video-indexer-cog-services-user')
  scope: openAiService
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      'a97b65f3-24c7-4388-baec-2e87135dc908'
    )
    #disable-next-line BCP318 // may be null if video indexer not deployed
    principalId: videoIndexerService.identity.principalId
    principalType: 'ServicePrincipal'
  }
}
