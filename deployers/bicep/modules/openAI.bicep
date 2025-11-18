targetScope = 'resourceGroup'

param location string
param appName string
param environment string
param tags object

//param managedIdentityPrincipalId string
param managedIdentityId string
param enableDiagLogging bool
param logAnalyticsId string

// Import diagnostic settings configurations
module diagnosticConfigs 'diagnosticSettings.bicep' = if (enableDiagLogging) {
  name: 'diagnosticConfigs'
}

// deploy new Azure OpenAI Resource
resource newOpenAI 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: toLower('${appName}-${environment}-openai')
  location: location
  kind: 'OpenAI'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned, UserAssigned'
    userAssignedIdentities: {
      '${managedIdentityId}': {}
    }
  }
  properties: {
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: false
  }
  tags: tags
}

// todo: add role assignment as required

// configure diagnostic settings for OpenAI Resource if required
resource openAIDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (enableDiagLogging)  {
  name: toLower('${newOpenAI.name}-diagnostics')
  scope: newOpenAI
  properties: {
    workspaceId: logAnalyticsId
    #disable-next-line BCP318 // expect one value to be null
    logs: diagnosticConfigs.outputs.standardLogCategories
    #disable-next-line BCP318 // expect one value to be null
    metrics: diagnosticConfigs.outputs.standardMetricsCategories
  }
}

// deploy GPT-4o model to the new OpenAI resource
module aiModel_gpt4o 'aiModel.bicep' = {
  name: 'gpt-4o'
  params: {
    parent: newOpenAI.name
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
    parent: newOpenAI.name
    modelName: 'text-embedding-3-small'
    modelVersion: '1'
    skuName: 'GlobalStandard'
    skuCapacity: 150
  }
dependsOn: [
    aiModel_gpt4o
  ]
}

output openAIName string = newOpenAI.name
output openAIResourceGroup string = resourceGroup().name



