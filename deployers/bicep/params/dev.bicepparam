using '../main.bicep'

param cloudEnvironment = 'AzureCloud'
param environment = 'dev'
param location = 'northcentralus'
param appName = 'simplechat'
param enableDiagLogging = false
param useExistingAcr = true
param existingAcrResourceGroup = 'simplechat-shared-rg'
param existingAcrResourceName = 'stecarrschatacr01'
param imageName = 'simple-chat:latest'
param deployContentSafety = false
param deployRedisCache = false
param deploySpeechService = false
param useExistingOpenAISvc = false
param existingOpenAIResourceGroupName = 'simplechat-shared-rg'
param existingOpenAIResourceName = 'stecarr-openai-02'

// Enterprise Application Settings (disabled by default for dev environment)
param enableEnterpriseApp = true
param enterpriseAppClientId = 'e2af9387-1f7b-4066-8362-fd9a8883e48c'
//param enterpriseAppClientSecret = ''
param unauthenticatedClientAction = 'RedirectToLoginPage'

param specialTags = { 
  owner: 'Ricky Bobby' 
}
