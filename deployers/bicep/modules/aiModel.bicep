param parent string
param modelName string
param modelVersion string
param skuName string
param skuCapacity int

resource openAI 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: parent
}

resource aiModel 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  name: modelName
  parent: openAI
  properties: {
    model: {
      format: 'OpenAI'
      name: modelName
      version: modelVersion
    }
  }
  sku: {
    name: skuName
    capacity: skuCapacity
  }
}
