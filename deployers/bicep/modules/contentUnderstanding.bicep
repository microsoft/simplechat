// contentUnderstanding.bicep
param accountName string
param location string
param models array
param tags object = {}

resource account 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: accountName
  location: location
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    customSubDomainName: accountName
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
  tags: tags
}

module deployments 'aiModel.bicep' = [for model in models: {
  name: '${accountName}-${model.modelName}'
  params: {
    parent: account.name
    modelName: model.modelName
    modelVersion: model.modelVersion
    skuName: model.skuName
    skuCapacity: model.skuCapacity
  }
}]

output endpoint string = 'https://${accountName}.services.ai.azure.com'
output resourceId string = account.id
