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

// cosmos db 
resource cosmosDb 'Microsoft.DocumentDB/databaseAccounts@2023-04-15' = {
  name: toLower('${appName}-${environment}-cosmos')
  location: location
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    capabilities: [
      {
        name: 'EnableServerless'
      }
    ]
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: false
      }
    ]
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
  }
  tags: tags
}

// grant the managed identity access to cosmos db as a contributor
resource cosmosContributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(cosmosDb.id, managedIdentityId, 'cosmos-contributor')
  scope: cosmosDb
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      'b24988ac-6180-42a0-ab88-20f7382dd24c'
    )
    principalId: managedIdentityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// configure diagnostic settings for cosmos db
resource cosmosDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (enableDiagLogging) {
  name: toLower('${cosmosDb.name}-diagnostics')
  scope: cosmosDb
  properties: {
    workspaceId: logAnalyticsId
    logs: diagnosticConfigs.outputs.standardLogCategories
    metrics: [] // Cosmos DB typically doesn't need metrics enabled
  }
}

output cosmosDbName string = cosmosDb.name
