targetScope = 'resourceGroup'

param lockName string
param lockNotes string

resource resourceGroupDeleteLock 'Microsoft.Authorization/locks@2020-05-01' = {
  name: lockName
  properties: {
    level: 'CanNotDelete'
    notes: lockNotes
  }
}
