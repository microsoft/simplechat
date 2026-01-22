targetScope = 'resourceGroup'

param name string
param location string
param appName string
param environment string
param serviceResourceID string
param subnetId string
param groupIDs array
param privateDnsZoneIds array = []
param tags object

resource dnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2021-05-01' = if (length(privateDnsZoneIds) > 0) {
  name: 'default'
  parent: privateEndpoint
  properties: {
    privateDnsZoneConfigs: [
      for zoneId in privateDnsZoneIds: {
        name: last(split(zoneId, '/'))
        properties: {
          privateDnsZoneId: zoneId
        }
      }
    ]
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

// @description('Private endpoint resource ID')
// output privateEndpointId string = privateEndpoint.id

// @description('Private endpoint name')
// output privateEndpointName string = privateEndpoint.name

// @description('Private IP address assigned to the private endpoint')
// output privateIpAddress string = privateEndpoint.properties.customDnsConfigs[0].ipAddresses[0]
