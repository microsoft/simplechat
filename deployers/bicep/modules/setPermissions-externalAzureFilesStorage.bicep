targetScope = 'resourceGroup'

param storageAccountName string
param webAppPrincipalId string

resource storageAccount 'Microsoft.Storage/storageAccounts@2022-09-01' existing = {
  name: storageAccountName
}

resource storageFileDataPrivilegedReaderRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, webAppPrincipalId, 'storage-file-data-privileged-reader')
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      'b8eda974-7b85-4f76-af95-65846b26df6d'
    )
    principalId: webAppPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource storageReaderRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, webAppPrincipalId, 'storage-reader')
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      'acdd72a7-3385-48ef-bd42-f606fba81ae7'
    )
    principalId: webAppPrincipalId
    principalType: 'ServicePrincipal'
  }
}
