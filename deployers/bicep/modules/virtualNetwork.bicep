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
        delegations: subnet.name == 'AppServiceIntegration' ? [
          {
            name: 'delegation'
            properties: {
              serviceName: 'Microsoft.Web/serverFarms'
            }
          }
        ] : []
      }
    }]
  }
  tags: tags
}

var subnetIds = [for subnet in subnetConfigs: resourceId('Microsoft.Network/virtualNetworks/subnets', vNetName, subnet.name)]
var subnetNames = [for subnet in subnetConfigs: subnet.name]
var appServiceIntegrationSubnetIndex = indexOf(subnetNames, 'AppServiceIntegration')
var privateEndpointIndex = indexOf(subnetNames, 'PrivateEndpoints')

// output results
output vNetId string = virtualNetwork.id
output privateNetworkSubnetId string = privateEndpointIndex == -1 ? '' : subnetIds[privateEndpointIndex]
output appServiceSubnetId string = appServiceIntegrationSubnetIndex == -1 ? '' : subnetIds[appServiceIntegrationSubnetIndex]
