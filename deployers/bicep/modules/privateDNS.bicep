targetScope = 'resourceGroup'

param zoneName string
param appName string
param environment string
param name string
param vNetId string
param tags object
param existingZoneResourceId string = ''
param createVNetLink bool = true

var useExistingZone = !empty(existingZoneResourceId)
var linkName = toLower('${appName}-${environment}-${name}-pe-dnszonelink')
var existingZoneSubscriptionId = useExistingZone ? split(existingZoneResourceId, '/')[2] : ''
var existingZoneResourceGroupName = useExistingZone ? split(existingZoneResourceId, '/')[4] : ''
var existingZoneName = useExistingZone ? split(existingZoneResourceId, '/')[8] : ''

resource privateDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = if (!useExistingZone) {
  name: zoneName
  location: 'global'
  tags: tags
}

resource existingPrivateDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' existing = if (useExistingZone) {
  name: existingZoneName
  scope: resourceGroup(existingZoneSubscriptionId, existingZoneResourceGroupName)
}

resource privateDnsZoneLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = if (!useExistingZone && createVNetLink) {
  name: linkName
  parent: privateDnsZone
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: vNetId
    }
  }
}

module existingPrivateDnsZoneLink 'privateDNSLink.bicep' = if (useExistingZone && createVNetLink) {
  name: 'existing-${name}-privateDnsZoneLink'
  scope: resourceGroup(existingZoneSubscriptionId, existingZoneResourceGroupName)
  params: {
    zoneName: existingZoneName
    linkName: linkName
    vNetId: vNetId
  }
}

output privateDnsZoneId string = useExistingZone ? existingZoneResourceId : privateDnsZone.id
output privateDnsZoneName string = useExistingZone ? existingPrivateDnsZone.name : privateDnsZone.name
