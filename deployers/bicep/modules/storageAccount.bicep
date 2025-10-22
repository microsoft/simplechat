targetScope = 'resourceGroup'

param location string
param appName string
param environment string
param tags object

param managedIdentityPrincipalId string
param managedIdentityId string
param enableDiagLogging bool
param logAnalyticsId string

// Import diagnostic settings configurations
module diagnosticConfigs 'diagnosticSettings.bicep' = {
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
  }
  tags: tags
}

// grant the managed identity access to the storage account as a blob data contributor
resource storageBlobDataContributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, managedIdentityId, 'storage-blob-data-contributor')
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
    )
    principalId: managedIdentityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// configure diagnostic settings for storage account
resource storageDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (enableDiagLogging) {
  name: toLower('${storageAccount.name}-diagnostics')
  scope: storageAccount
  properties: {
    workspaceId: logAnalyticsId
    logs: [] // Storage account main resource doesn't have logs
    metrics: diagnosticConfigs.outputs.transactionMetricsCategories
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-01-01' = {
  name: 'default'
  parent: storageAccount
}

resource storageDiagnosticsBlob 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (enableDiagLogging) {
  name: toLower('${storageAccount.name}-blob-diagnostics')
  scope: blobService
  properties: {
    workspaceId: logAnalyticsId
    logs: diagnosticConfigs.outputs.standardLogCategories
    metrics: diagnosticConfigs.outputs.transactionMetricsCategories
  }
}

