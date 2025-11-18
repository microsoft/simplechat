targetScope = 'resourceGroup'

param location string
param appName string
param environment string
param tags object

param managedIdentityPrincipalId string
param managedIdentityId string
param enableDiagLogging bool
param logAnalyticsId string

@description('Enable enterprise app authentication')
param enableEnterpriseApp bool 

@description('Enterprise app client ID - used for documentation')
param enterpriseAppClientId string 

@description('Enterprise app client secret to store in Key Vault')
@secure()
param enterpriseAppClientSecret string 

// Import diagnostic settings configurations
module diagnosticConfigs 'diagnosticSettings.bicep' = if (enableDiagLogging) {
  name: 'diagnosticConfigs'
}

// key vault resource 
resource kv 'Microsoft.KeyVault/vaults@2024-11-01' = {
  name: toLower('${appName}-${environment}-kv')
  location: location
  properties: {
    tenantId: subscription().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    accessPolicies: []
    enabledForDeployment: false
    enabledForDiskEncryption: false
    enabledForTemplateDeployment: false
    publicNetworkAccess: 'Enabled'
    enableRbacAuthorization: true
  }
  tags: tags
}

// grant the managed identity access to the key vault
resource kvSecretsUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(kv.id, managedIdentityId, 'kv-secrets-user')
  scope: kv
  properties: {
    // Built-in role definition id for "Key Vault Secrets User"
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '4633458b-17de-408a-b874-0445c86b69e6'
    )
    principalId: managedIdentityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// configure diagnostic settings for key vault
resource kvDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (enableDiagLogging) {
  name: toLower('${kv.name}-diagnostics')
  scope: kv
  properties: {
    workspaceId: logAnalyticsId
    #disable-next-line BCP318 // expect one value to be null
    logs: diagnosticConfigs.outputs.standardLogCategories
    #disable-next-line BCP318 // expect one value to be null
    metrics: diagnosticConfigs.outputs.standardMetricsCategories
  }
}

// Store the enterprise app client secret in Key Vault if provided
resource enterpriseAppSecret 'Microsoft.KeyVault/vaults/secrets@2024-11-01' = if (enableEnterpriseApp && !empty(enterpriseAppClientSecret)) {
  name: 'enterprise-app-client-secret'
  parent: kv
  properties: {
    value: enterpriseAppClientSecret
    contentType: 'Client secret for Azure AD enterprise app ${enterpriseAppClientId}'
  }
}

output keyVaultId string = kv.id
output keyVaultName string = kv.name
output keyVaultUri string = kv.properties.vaultUri
output enterpriseAppClientSecretUri string = enableEnterpriseApp ? '${kv.properties.vaultUri}secrets/enterprise-app-client-secret' : ''
