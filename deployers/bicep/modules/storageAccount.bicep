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

// Import diagnostic settings configurations
module diagnosticConfigs 'diagnosticSettings.bicep' = if (enableDiagLogging) {
  name: 'diagnosticConfigs'
}

// storage account resource
resource storageAccount 'Microsoft.Storage/storageAccounts@2022-09-01' = {
  #disable-next-line BCP334 //Name length managed by Bicep parameters.
  name: toLower('${appName}${environment}sa')
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: true
    isHnsEnabled: true
  }
  tags: tags
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-01-01' = {
  name: 'default'
  parent: storageAccount
}

// create user-documents container
resource userDocumentsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  name: 'user-documents'
  parent: blobService
  properties: {
    publicAccess: 'None'
  }
}

// create group-documents container
resource groupDocumentsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  name: 'group-documents'
  parent: blobService
  properties: {
    publicAccess: 'None'
  }
}

// configure diagnostic settings for storage account
resource storageDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (enableDiagLogging) {
  name: toLower('${storageAccount.name}-diagnostics')
  scope: storageAccount
  properties: {
    workspaceId: logAnalyticsId
    logs: [] // Storage account main resource doesn't have logs
    #disable-next-line BCP318 // expect one value to be null
    metrics: diagnosticConfigs.outputs.transactionMetricsCategories
  }
}

resource storageDiagnosticsBlob 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (enableDiagLogging) {
  name: toLower('${storageAccount.name}-blob-diagnostics')
  scope: blobService
  properties: {
    workspaceId: logAnalyticsId
    #disable-next-line BCP318 // expect one value to be null
    logs: diagnosticConfigs.outputs.standardLogCategories
    #disable-next-line BCP318 // expect one value to be null
    metrics: diagnosticConfigs.outputs.transactionMetricsCategories
  }
}

//=========================================================
// store storage keys in key vault if using key authentication and configure app permissions = true
//=========================================================
module storageAccountSecret 'keyVault-Secrets.bicep' = if (authenticationType == 'key' && configureApplicationPermissions) {
  name: 'storeStorageAccountSecret'
  params: {
    keyVaultName: keyVault
    secretName: 'storage-account-key'
    secretValue: storageAccount.listKeys().keys[0].value
  }
}

output name string = storageAccount.name
output endpoint string = storageAccount.properties.primaryEndpoints.blob
