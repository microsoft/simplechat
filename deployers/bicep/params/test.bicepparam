using '../main.bicep'

param cloudEnvironment = 'AzureCloud'
param environment = 'test'
param location = 'westus2'
param appName = 'mychat01'
param enableDiagLogging = false
param useExistingAcr = true
param existingAcrResourceGroup = '<existing ACR Resource Group>' //must be specified if useExistingAcr = true
param existingAcrResourceName = '<existing ACR Resource Name>' //must be specified if useExistingAcr = true
param imageName = 'simple-chat:latest'
param deployContentSafety = false
param deployRedisCache = false
param deploySpeechService = false
param useExistingOpenAISvc = false
param existingOpenAIResourceGroupName = '<name of resource group hosting Azure OpenAI>' //must be specified if useExistingOpenAISvc = true
param existingOpenAIResourceName = '<name of existing Azure OpenAI resource>' //must be specified if useExistingOpenAISvc = true

param specialTags = {  
  owner: 'Jose Cuervo'
  deploymentDate: '2025-09-12'
}
