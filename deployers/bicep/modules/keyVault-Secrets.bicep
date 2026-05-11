targetScope = 'resourceGroup'

param keyVaultName string
param secretName string
@secure()
param secretValue string

resource kv 'Microsoft.KeyVault/vaults@2025-05-01' existing = {
  name: keyVaultName
}

resource secret 'Microsoft.KeyVault/vaults/secrets@2025-05-01' = {
  name: secretName
  parent: kv
  properties: {
    value: secretValue
  }
}

//------------------------------------------------
// output values
//------------------------------------------------
output SecretUri string = '${kv.properties.vaultUri}secrets/${secretName}'
