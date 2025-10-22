targetScope = 'resourceGroup'

param acrName string
param managedIdentityPrincipalId string
param managedIdentityId string

resource existingACR 'Microsoft.ContainerRegistry/registries@2025-04-01' existing = {
  name: acrName
}

// grant the managed identity access to azure container registry as a pull contributor
resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingACR.id, managedIdentityId, 'acr-acrpull')
  scope: existingACR
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '7f951dda-4ed3-4680-a7ca-43fe172d538d'
    )
    principalId: managedIdentityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

output acrName string = existingACR.name
output acrResourceGroup string = resourceGroup().name
