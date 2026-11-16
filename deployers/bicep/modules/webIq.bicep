// webIq.bicep
// Exact account shape documented at https://learn.microsoft.com/en-us/web-iq/get-started/deploy-azure-cli.
param accountName string
param tags object = {}

resource account 'Microsoft.WebIQ/accounts@2026-06-01-preview' = {
  name: accountName
  location: 'global'
  kind: 'WebIQ.Grounding'
  sku: {
    name: 'G3'
  }
  properties: {
    statisticsEnabled: false
  }
  tags: tags
}

output resourceId string = account.id
