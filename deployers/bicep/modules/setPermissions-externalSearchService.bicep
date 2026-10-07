targetScope = 'resourceGroup'

param searchServiceName string
param webAppPrincipalId string
param grantReaderRole bool = false

resource searchService 'Microsoft.Search/searchServices@2025-05-01' existing = {
  name: searchServiceName
}

resource searchIndexDataReaderRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(searchService.id, webAppPrincipalId, 'search-index-data-reader')
  scope: searchService
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '1407120a-92aa-4202-b7e9-c0e197c71c8f'
    )
    principalId: webAppPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource searchReaderRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (grantReaderRole) {
  name: guid(searchService.id, webAppPrincipalId, 'search-reader')
  scope: searchService
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      'acdd72a7-3385-48ef-bd42-f606fba81ae7'
    )
    principalId: webAppPrincipalId
    principalType: 'ServicePrincipal'
  }
}
