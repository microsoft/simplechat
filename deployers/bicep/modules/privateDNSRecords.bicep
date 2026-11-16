targetScope = 'resourceGroup'

param zoneName string
param records array
var recordNames = union(map(records, record => record.name), [])

resource zone 'Microsoft.Network/privateDnsZones@2020-06-01' existing = {
  name: zoneName
}

resource dnsRecords 'Microsoft.Network/privateDnsZones/A@2020-06-01' = [for recordName in recordNames: {
  parent: zone
  name: recordName
  properties: {
    ttl: 60
    aRecords: map(filter(records, record => record.name == recordName), record => { ipv4Address: record.ipAddress })
  }
}]
