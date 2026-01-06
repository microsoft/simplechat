targetScope = 'resourceGroup'

param name string
param location string
param appName string
param environment string
param serviceResourceID string
param subnetId string
param groupIDs array
param vNetId string = ''
param privateDNSZoneName string = ''
param tags object

resource privateDnsZone 'Microsoft.Network/privateDnsZones@2024-06-01' = if (privateDNSZoneName != '') {
  name: privateDNSZoneName
  location: 'global'
  tags: tags
}

resource privateDnsZoneLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = if (privateDNSZoneName != '') {
  name: toLower('${appName}-${environment}-${name}-pe-dnszonelink')
  parent: privateDnsZone
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: vNetId
    }
  }
}

resource privateEndpoint 'Microsoft.Network/privateEndpoints@2021-05-01' = {
  name: toLower('${appName}-${environment}-${name}-pe')
  location: location
  properties: {
    subnet: {
      id: subnetId
    }
    privateLinkServiceConnections: [
      {
        name: toLower('${appName}-${environment}-${name}-pe')
        properties: {
          privateLinkServiceId: serviceResourceID
          groupIds: groupIDs
        }
      }
    ]
    customNetworkInterfaceName: toLower('${appName}-${environment}-${name}-nic')
  }
  tags: tags
}

@description('Private endpoint resource ID')
output privateEndpointId string = privateEndpoint.id

@description('Private endpoint name')
output privateEndpointName string = privateEndpoint.name

@description('Private IP address assigned to the private endpoint')
output privateIpAddress string = privateEndpoint.properties.customDnsConfigs[0].ipAddresses[0]
