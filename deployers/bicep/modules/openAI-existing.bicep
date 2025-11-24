targetScope = 'resourceGroup'

param openAIName string

resource existingOpenAI 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: openAIName
}

// deploy GPT-4o model to the new OpenAI resource
module aiModel_gpt4o 'aiModel.bicep' = {
  name: 'gpt-4o'
  params: {
    parent: existingOpenAI.name
    modelName: 'gpt-4o'
    modelVersion: '2024-11-20'
    skuName: 'GlobalStandard'
    skuCapacity: 100
  }
}

// deploy Text Embedding model to the new OpenAI resource
module aiModel_textEmbedding 'aiModel.bicep' = {
  name: 'text-embedding'
  params: {
    parent: existingOpenAI.name
    modelName: 'text-embedding-3-small'
    modelVersion: '1'
    skuName: 'GlobalStandard'
    skuCapacity: 150
  }
dependsOn: [
    aiModel_gpt4o
  ]
}

output openAIName string = existingOpenAI.name
output openAIResourceGroup string = resourceGroup().name

output openAIEndpoint string = existingOpenAI.properties.endpoint



