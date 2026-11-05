// contentUnderstandingAccess.bicep
param accountName string
param webAppName string
param webAppResourceGroup string
param webAppSubscriptionId string
param deploymentPrincipalId string

resource account 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: accountName
}
resource webApp 'Microsoft.Web/sites@2024-04-01' existing = {
  name: webAppName
  scope: resourceGroup(webAppSubscriptionId, webAppResourceGroup)
}

var userRoleId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'a97b65f3-24c7-4388-baec-2e87135dc908')
resource appUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(account.id, webApp.id, userRoleId)
  scope: account
  properties: {
    roleDefinitionId: userRoleId
    principalId: webApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}
resource runnerUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(deploymentPrincipalId)) {
  name: guid(account.id, deploymentPrincipalId, userRoleId)
  scope: account
  properties: {
    roleDefinitionId: userRoleId
    principalId: deploymentPrincipalId
  }
}
