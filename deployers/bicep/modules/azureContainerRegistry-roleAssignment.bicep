targetScope = 'resourceGroup'

param acrName string
param managedIdentityPrincipalId string

resource existingACR 'Microsoft.ContainerRegistry/registries@2025-04-01' existing = {
  name: acrName
}

// Built-in role definition ID for AcrPull
var acrPullRoleDefinitionId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '7f951dda-4ed3-4680-a7ca-43fe172d538d'
)

// grant the managed identity access to azure container registry as a pull contributor
resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingACR.id, managedIdentityPrincipalId, acrPullRoleDefinitionId)
  scope: existingACR
  properties: {
    roleDefinitionId: acrPullRoleDefinitionId
    principalId: managedIdentityPrincipalId
    principalType: 'ServicePrincipal'
  }  
}

output acrName string = existingACR.name
