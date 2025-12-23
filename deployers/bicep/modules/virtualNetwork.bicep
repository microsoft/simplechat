targetScope = 'resourceGroup'

param location string
param vNetName string
param addressSpaces array
param subnetConfigs array
param tags object 

resource virtualNetwork 'Microsoft.Network/virtualNetworks@2021-05-01' = {
  name: vNetName
  location: location
  properties: {
    addressSpace: {
       addressPrefixes: addressSpaces
    }
    subnets: [for subnet in subnetConfigs: {
      name: subnet.name
      properties: {
        addressPrefix: subnet.addressPrefix
        privateEndpointNetworkPolicies: subnet.enablePrivateEndpointNetworkPolicies ? 'Enabled' : 'Disabled'
        privateLinkServiceNetworkPolicies: subnet.enablePrivateLinkServiceNetworkPolicies ? 'Enabled' : 'Disabled'
      }
    }]
  }
  tags: tags
}
