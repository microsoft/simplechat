targetScope = 'resourceGroup'

param acrName string
param acrResourceGroup string
param managedIdentityPrincipalId string

// Deploy role assignment to the ACR's resource group
module roleAssignment 'azureContainerRegistry-roleAssignment.bicep' = {
  name: 'acr-role-assignment'
  scope: resourceGroup(acrResourceGroup)
  params: {
    acrName: acrName
    managedIdentityPrincipalId: managedIdentityPrincipalId
  }
}

output acrName string = roleAssignment.outputs.acrName
output acrResourceGroup string = acrResourceGroup
