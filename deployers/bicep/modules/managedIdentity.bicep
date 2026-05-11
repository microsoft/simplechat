targetScope = 'resourceGroup'

param location string
param appName string
param environment string
param tags object

// managed identity for resources
resource managedIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: toLower('${appName}-${environment}-id')
  location: location
  tags: tags
}

output clientId string = managedIdentity.properties.clientId
output principalId string = managedIdentity.properties.principalId
output resourceId string = managedIdentity.id
