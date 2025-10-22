// ===============================================
// Example: Using the Diagnostic Settings Module
// ===============================================

param workspaceId string
param enableDiagLogging bool = true

// Import diagnostic settings configurations
module diagnosticConfigs 'diagnosticSettings.bicep' = {
  name: 'diagnosticConfigs'
}

// Example: Key Vault with standard configuration
resource exampleKeyVault 'Microsoft.KeyVault/vaults@2024-11-01' = {
  name: 'example-kv'
  location: resourceGroup().location
  properties: {
    tenantId: subscription().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    accessPolicies: []
    enableRbacAuthorization: true
  }
}

// Apply standard diagnostic settings to Key Vault
resource kvDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (enableDiagLogging) {
  name: '${exampleKeyVault.name}-diagnostics'
  scope: exampleKeyVault
  properties: {
    workspaceId: workspaceId
    logs: diagnosticConfigs.outputs.standardLogCategories
    metrics: diagnosticConfigs.outputs.standardMetricsCategories
  }
}

// Example: Storage Account with transaction metrics only
resource exampleStorage 'Microsoft.Storage/storageAccounts@2022-09-01' = {
  name: 'examplestorageacct'
  location: resourceGroup().location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    accessTier: 'Hot'
  }
}

// Apply metrics-only diagnostic settings to Storage Account
resource storageDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (enableDiagLogging) {
  name: '${exampleStorage.name}-diagnostics'
  scope: exampleStorage
  properties: {
    workspaceId: workspaceId
    logs: [] // Storage account main resource doesn't have logs
    metrics: diagnosticConfigs.outputs.transactionMetricsCategories
  }
}

// Example: Web App with specialized log categories
resource exampleAppServicePlan 'Microsoft.Web/serverfarms@2022-03-01' = {
  name: 'example-asp'
  location: resourceGroup().location
  sku: {
    name: 'B1'
    tier: 'Basic'
  }
  kind: 'app'
}

resource exampleWebApp 'Microsoft.Web/sites@2022-03-01' = {
  name: 'example-webapp'
  location: resourceGroup().location
  kind: 'app'
  properties: {
    serverFarmId: exampleAppServicePlan.id
    httpsOnly: true
  }
}

// Apply specialized diagnostic settings to Web App
resource webAppDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (enableDiagLogging) {
  name: '${exampleWebApp.name}-diagnostics'
  scope: exampleWebApp
  properties: {
    workspaceId: workspaceId
    logs: diagnosticConfigs.outputs.webAppLogCategories
    metrics: diagnosticConfigs.outputs.standardMetricsCategories
  }
}