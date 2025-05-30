using '../main.bicep'

param azurePlatform = 'AzureUSGovernment' // or 'AzureCloud'
param tenantId = '<YOUR TENANT ID HERE>' // Provide via --parameters or a secure way
param location = 'usgovvirginia' // or your preferred region
param resourceOwnerId = 'johndoe@domain.com'
param environment = 'sbx'
param baseName = 'julie1'
param acrName = 'acr8000'
param acrResourceGroupName = 'sc-emma1-sbx1-rg' // RG of your ACR
param imageName = 'simple-chat:2025-05-15_7' // Be specific with tags
param useExistingOpenAiInstance = true
param existingAzureOpenAiResourceName = 'gregazureopenai1' // if useExistingOpenAiInstance is true
param existingAzureOpenAiResourceGroupName = 'azureopenairg' // if useExistingOpenAiInstance is true
param appRegistrationClientId = 'a9acf8e2-441d-4aca-84f6-a83b3e820644' // scbingo1-ar
param appRegistrationClientSecret = '<YOUR SECRET HERE>' // Provide via --parameters or a secure way
param appRegistrationSpObjectId = '364c5131-27b3-4ac1-bf95-0bd55106a109'
// Other SKUs can be overridden if needed
