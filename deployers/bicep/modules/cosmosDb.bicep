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

resource cosmosDatabase 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2023-04-15' = {
  parent: cosmosDb
  name: 'SimpleChat'
  properties: {
    resource: {
      id: 'SimpleChat'
    }
    options: {}
  }
}

resource cosmosContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-04-15' = {
  parent: cosmosDatabase
  name: 'settings'
  properties: {
    resource: {
      id: 'settings'
      partitionKey: {
        paths: [
          '/id'
        ]
      }
    }
    options: {}
  }
}

// configure diagnostic settings for cosmos db
resource cosmosDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (enableDiagLogging) {
  name: toLower('${cosmosDb.name}-diagnostics')
  scope: cosmosDb
  properties: {
    workspaceId: logAnalyticsId
    #disable-next-line BCP318 // expect one value to be null
    logs: diagnosticConfigs.outputs.standardLogCategories
    metrics: [] // Cosmos DB typically doesn't need metrics enabled
  }
}

//=========================================================
// store cosmos db keys in key vault if using key authentication and configure app permissions = true
//=========================================================
module storeEnterpriseAppSecret 'keyVault-Secrets.bicep' = if (authenticationType == 'key' && configureApplicationPermissions) {
  name: 'storeEnterpriseAppSecret'
  params: {
    keyVaultName: keyVault
    secretName: 'cosmos-db-key'
    secretValue: cosmosDb.listKeys().primaryMasterKey
  }
}

output cosmosDbName string = cosmosDb.name
output cosmosDbUri string = cosmosDb.properties.documentEndpoint
