using '../main.bicep'

param cloudEnvironment = 'AzureCloud'
param environment = 'prod'
param location = 'eastus2'
param appName = 'mychat02'
param enableDiagLogging = true
param useExistingAcr = true
param existingAcrResourceGroup = '<existing ACR Resource Group>' //must be specified if useExistingAcr = true
param existingAcrResourceName = '<existing ACR Resource Name>' //must be specified if useExistingAcr = true
param imageName = 'simple-chat:latest'
param deployContentSafety = true
param deployRedisCache = true
param deploySpeechService = true
param useExistingOpenAISvc = false
param existingOpenAIResourceGroupName = '<name of resource group hosting Azure OpenAI>' //must be specified if useExistingOpenAISvc = true
param existingOpenAIResourceName = '<name of existing Azure OpenAI resource>' //must be specified if useExistingOpenAISvc = true

// Enterprise Application Settings (enabled for production)
param enableEnterpriseApp = true
param enterpriseAppClientId = '<azure-ad-app-client-id>' // Set this to your registered Azure AD app client ID
param enterpriseAppClientSecret = '<azure-ad-app-client-secret>' // Set this to your registered Azure AD app client secret
param unauthenticatedClientAction = 'RedirectToLoginPage' // Redirect to login for production security

param specialTags = {  
  owner: 'Johnny Walker'
  deploymentDate: '2025-09-12'
}
