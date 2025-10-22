using '../main.bicep'

param cloudEnvironment = 'AzureCloud'
param environment = 'dev'
param location = 'northcentralus'
param appName = '<app-name>'
param enableDiagLogging = true
param useExistingAcr = true
param existingAcrResourceGroup = '<existing ACR Resource Group>' //must be specified if useExistingAcr = true
param existingAcrResourceName = '<existing ACR Resource Name>' //must be specified if useExistingAcr = true
param imageName = '<repository>:<tag>'
param deployContentSafety = true
param deployRedisCache = true
param deploySpeechService = true
param useExistingOpenAISvc = false
param existingOpenAIResourceGroupName = '<name of resource group hosting Azure OpenAI>' //must be specified if useExistingOpenAISvc = true
param existingOpenAIResourceName = '<name of existing Azure OpenAI resource>' //must be specified if useExistingOpenAISvc = true

// Enterprise Application Settings
param enableEnterpriseApp = false // Set to true to enable enterprise authentication
param enterpriseAppClientId = '<azure-ad-app-client-id>' // Required when enableEnterpriseApp = true
param enterpriseAppClientSecret = '<azure-ad-app-client-secret>' // Required when enableEnterpriseApp = true
param unauthenticatedClientAction = 'RedirectToLoginPage' // Options: RedirectToLoginPage, Return401, Return403, AllowAnonymous

param specialTags = { 
  owner: '<OwnerName>' 
  deploymentDate: '<DeploymentDate>'
}
