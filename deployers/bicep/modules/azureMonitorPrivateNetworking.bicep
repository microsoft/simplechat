targetScope = 'resourceGroup'

param location string
param appName string
param environment string
param tags object
param virtualNetworkId string
@minLength(1)
param privateEndpointSubnetId string
param privateDnsZoneConfigs object = {}
param blobStorageDnsZoneId string
param monitoringResourceIds array

var cloudName = toLower(az.environment().name)
var dnsNames = loadJsonContent('privateDNSZones.json')[cloudName]
var zoneKeys = concat(['monitor', 'monitorOms', 'monitorOds', 'monitorAgent'], empty(dnsNames.monitorAdx) ? [] : ['monitorAdx'])
var zoneConfigs = [for zoneKey in zoneKeys: {
  key: zoneKey
  zoneName: dnsNames[zoneKey]
  zoneResourceId: contains(privateDnsZoneConfigs, zoneKey) ? (privateDnsZoneConfigs[zoneKey].zoneResourceId ?? '') : ''
  createVNetLink: contains(privateDnsZoneConfigs, zoneKey) ? (privateDnsZoneConfigs[zoneKey].createVNetLink ?? true) : true
}]

resource scope 'Microsoft.Insights/privateLinkScopes@2021-07-01-preview' = {
  name: toLower('${appName}-${environment}-ampls')
  location: 'global'
  properties: {
    accessModeSettings: {
      ingestionAccessMode: 'PrivateOnly'
      queryAccessMode: 'PrivateOnly'
    }
  }
  tags: tags
}

resource scopedResources 'Microsoft.Insights/privateLinkScopes/scopedResources@2021-07-01-preview' = [for (monitoringResourceId, resourceIndex) in monitoringResourceIds: {
  parent: scope
  name: 'monitor-${resourceIndex}'
  properties: {
    linkedResourceId: monitoringResourceId
  }
}]

module dnsZones 'privateDNS.bicep' = [for zoneConfig in zoneConfigs: {
  name: '${zoneConfig.key}DNSZone'
  params: {
    zoneName: zoneConfig.zoneName
    appName: appName
    environment: environment
    name: zoneConfig.key
    vNetId: virtualNetworkId
    tags: tags
    existingZoneResourceId: zoneConfig.zoneResourceId
    createVNetLink: zoneConfig.createVNetLink
  }
}]

var monitorDnsZoneIds = [for zoneConfig in take(zoneConfigs, 4): empty(zoneConfig.zoneResourceId) ? resourceId('Microsoft.Network/privateDnsZones', zoneConfig.zoneName) : zoneConfig.zoneResourceId]

module monitorPE 'privateEndpoint.bicep' = {
  name: 'monitorPE'
  params: {
    name: 'ampls'
    location: location
    appName: appName
    environment: environment
    serviceResourceID: scope.id
    subnetId: privateEndpointSubnetId
    groupIDs: ['azuremonitor']
    privateDnsZoneIds: concat(monitorDnsZoneIds, [blobStorageDnsZoneId])
    tags: tags
  }
  dependsOn: [scopedResources, dnsZones]
}

resource monitorNic 'Microsoft.Network/networkInterfaces@2023-09-01' existing = {
  name: toLower('${appName}-${environment}-ampls-nic')
}

var adxZoneConfig = privateDnsZoneConfigs.?monitorAdx ?? {}
var adxZoneResourceId = adxZoneConfig.zoneResourceId ?? ''
var adxDnsEntries = flatten(map(monitorNic.properties.ipConfigurations, ipConfig => map(ipConfig.properties.privateLinkConnectionProperties.fqdns ?? [], fqdn => {
  fqdn: fqdn
  ipAddress: ipConfig.properties.privateIPAddress
})))

module adxDnsRecords 'privateDNSRecords.bicep' = if (!empty(dnsNames.monitorAdx)) {
  name: 'monitorAdxDNSRecords'
  scope: resourceGroup(empty(adxZoneResourceId) ? subscription().subscriptionId : split(adxZoneResourceId, '/')[2], empty(adxZoneResourceId) ? resourceGroup().name : split(adxZoneResourceId, '/')[4])
  params: {
    zoneName: dnsNames.monitorAdx
    records: map(filter(adxDnsEntries, entry => endsWith(entry.fqdn, '.${dnsNames.monitorAdx}') || entry.fqdn == dnsNames.monitorAdx), entry => {
      name: entry.fqdn == dnsNames.monitorAdx ? '@' : substring(entry.fqdn, 0, length(entry.fqdn) - length(dnsNames.monitorAdx) - 1)
      ipAddress: entry.ipAddress
    })
  }
  dependsOn: [monitorPE, dnsZones]
}

output privateLinkScopeId string = scope.id
