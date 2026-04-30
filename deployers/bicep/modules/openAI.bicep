targetScope = 'resourceGroup'

param location string
param appName string
param environment string
param tags object

param enableDiagLogging bool
param logAnalyticsId string

param existingOpenAIEndpoint string = ''
param existingOpenAIResourceName string = ''
param existingOpenAIResourceGroup string = ''
param existingOpenAISubscriptionId string = ''

param gptModels array
param embeddingModels array

param enablePrivateNetworking bool

var useExistingOpenAIEndpoint = !empty(existingOpenAIEndpoint)
var resolvedOpenAIResourceGroup = useExistingOpenAIEndpoint ? existingOpenAIResourceGroup : resourceGroup().name
var resolvedOpenAISubscriptionId = useExistingOpenAIEndpoint ? existingOpenAISubscriptionId : subscription().subscriptionId

// Import diagnostic settings configurations
module diagnosticConfigs 'diagnosticSettings.bicep' = if (enableDiagLogging) {
  name: 'diagnosticConfigs'
}

// deploy new Azure OpenAI Resource
resource openAI 'Microsoft.CognitiveServices/accounts@2024-10-01' = if (!useExistingOpenAIEndpoint) {
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
    publicNetworkAccess: enablePrivateNetworking ? 'Disabled' : 'Enabled'
    customSubDomainName: toLower('${appName}-${environment}-openai')
  }
  tags: tags
}

// configure diagnostic settings for OpenAI Resource if required
resource openAIDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (enableDiagLogging && !useExistingOpenAIEndpoint) {
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
  for (model, i) in !useExistingOpenAIEndpoint ? concat(gptModels, embeddingModels) : []: {
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

output openAIName string = useExistingOpenAIEndpoint ? existingOpenAIResourceName : openAI.name
output openAIResourceGroup string = resolvedOpenAIResourceGroup
output openAISubscriptionId string = resolvedOpenAISubscriptionId
#disable-next-line BCP318 // guarded by useExistingOpenAIEndpoint condition above
output openAIEndpoint string = useExistingOpenAIEndpoint ? existingOpenAIEndpoint : openAI.properties.endpoint
