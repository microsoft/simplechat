targetScope = 'resourceGroup'

// Grants that let SimpleChat use a Video Indexer account and let that account read its media storage.
// Kept separate so an existing environment can add Video Indexer without redeploying every application grant.

@description('Name of the Video Indexer account.')
param videoIndexerName string

@description('Name of the storage account that holds the Video Indexer media.')
param videoIndexerStorageAccountName string

@description('Name of the web app whose system-assigned identity calls the Video Indexer generateAccessToken API.')
param webAppName string

@description('''Role definition ID granted to the web app identity on the Video Indexer account.
- Video Indexer Account Contributor (3f99eaab-6f59-4877-adf5-1cacd22e20b0) in Azure Commercial
- Contributor (b24988ac-6180-42a0-ab88-20f7382dd24c) where that role has not been confirmed''')
param webAppRoleDefinitionId string

resource webApp 'Microsoft.Web/sites@2022-03-01' existing = {
  name: webAppName
}

resource videoIndexerService 'Microsoft.VideoIndexer/accounts@2024-01-01' existing = {
  name: videoIndexerName
}

resource videoIndexerStorageAccount 'Microsoft.Storage/storageAccounts@2022-09-01' existing = {
  name: videoIndexerStorageAccountName
}

// SimpleChat always calls generateAccessToken with its managed identity, whatever authenticationType is.
// The role ID is part of the name so a later role change creates a new assignment instead of failing.
resource webAppVideoIndexerAccessRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(videoIndexerService.id, webApp.id, 'video-indexer-app-access', webAppRoleDefinitionId)
  scope: videoIndexerService
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      webAppRoleDefinitionId
    )
    principalId: webApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// grant the video indexer service access to its storage account as a Storage Blob Data Contributor.
// The name inputs match the assignment earlier deployer versions created on the application storage account.
resource videoIndexerStorageBlobDataContributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(videoIndexerStorageAccount.id, videoIndexerService.id, 'video-indexer-storage-blob-data-contributor')
  scope: videoIndexerStorageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
    )
    principalId: videoIndexerService.identity.principalId
    principalType: 'ServicePrincipal'
  }
}
