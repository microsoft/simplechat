targetScope = 'resourceGroup'

param location string
param appName string
param environment string
param tags object

param enableDiagLogging bool
param logAnalyticsId string

param keyVault string
param authenticationType string
param configureApplicationPermissions bool

param gptModels array
param embeddingModels array

// Import diagnostic settings configurations
module diagnosticConfigs 'diagnosticSettings.bicep' = if (enableDiagLogging) {
  name: 'diagnosticConfigs'
}

// deploy new Azure OpenAI Resource
resource openAI 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: toLower('${appName}-${environment}-openai')
  location: location
  kind: 'OpenAI'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    publicNetworkAccess: 'Enabled'
    customSubDomainName: toLower('${appName}-${environment}-openai')
  }
  tags: tags
}

// configure diagnostic settings for OpenAI Resource if required
resource openAIDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (enableDiagLogging) {
  name: toLower('${openAI.name}-diagnostics')
  scope: openAI
  properties: {
    workspaceId: logAnalyticsId
    #disable-next-line BCP318 // expect one value to be null
    logs: diagnosticConfigs.outputs.standardLogCategories
    #disable-next-line BCP318 // expect one value to be null
    metrics: diagnosticConfigs.outputs.standardMetricsCategories
  }
}

// deploy AI models defined in the input arrays
@batchSize(1)
module aiModel 'aiModel.bicep' = [
  for (model, i) in concat(gptModels, embeddingModels): {
    name: 'model-${replace(model.modelName, '.', '-')}-${i}'
    params: {
      parent: openAI.name
      modelName: model.modelName
      modelVersion: model.modelVersion
      skuName: model.skuName
      skuCapacity: model.skuCapacity
    }
  }
]

//=========================================================
// store openAI keys in key vault if using key authentication and configure app permissions = true
//=========================================================
module openAISecret 'keyVault-Secrets.bicep' = if (authenticationType == 'key' && configureApplicationPermissions) {
  name: 'storeOpenAISecret'
  params: {
    keyVaultName: keyVault
    secretName: 'openAi-key'
    secretValue: openAI.listKeys().key1
  }
}

output openAIName string = openAI.name
output openAIResourceGroup string = resourceGroup().name
output openAIEndpoint string = openAI.properties.endpoint
