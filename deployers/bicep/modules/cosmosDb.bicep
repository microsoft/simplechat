targetScope = 'resourceGroup'

param location string
param appName string
param environment string
param tags object

param enableDiagLogging bool
param logAnalyticsId string

param enablePrivateNetworking bool
param allowedIpAddresses array = []

@allowed([
  'provisioned'
  'serverless'
])
param capacityMode string = 'provisioned'

@minValue(1000)
param containerAutoscaleMaxThroughput int = 1000

var cosmosContainers = [
  {
    name: 'conversations'
    partitionKeyPath: '/id'
    defaultTtl: null
  }
  {
    name: 'messages'
    partitionKeyPath: '/conversation_id'
    defaultTtl: null
  }
  {
    name: 'tabular_export_runs'
    partitionKeyPath: '/user_id'
    defaultTtl: null
  }
  {
    name: 'data_management_jobs'
    partitionKeyPath: '/id'
    defaultTtl: null
  }
  {
    name: 'data_management_job_items'
    partitionKeyPath: '/job_id'
    defaultTtl: null
  }
  {
    name: 'personal_workflows'
    partitionKeyPath: '/user_id'
    defaultTtl: null
  }
  {
    name: 'personal_workflow_runs'
    partitionKeyPath: '/user_id'
    defaultTtl: null
  }
  {
    name: 'personal_workflow_run_items'
    partitionKeyPath: '/run_id'
    defaultTtl: null
  }
  {
    name: 'group_workflows'
    partitionKeyPath: '/group_id'
    defaultTtl: null
  }
  {
    name: 'group_workflow_runs'
    partitionKeyPath: '/group_id'
    defaultTtl: null
  }
  {
    name: 'group_workflow_run_items'
    partitionKeyPath: '/run_id'
    defaultTtl: null
  }
  {
    name: 'group_conversations'
    partitionKeyPath: '/id'
    defaultTtl: null
  }
  {
    name: 'group_messages'
    partitionKeyPath: '/conversation_id'
    defaultTtl: null
  }
  {
    name: 'collaboration_conversations'
    partitionKeyPath: '/id'
    defaultTtl: null
  }
  {
    name: 'collaboration_messages'
    partitionKeyPath: '/conversation_id'
    defaultTtl: null
  }
  {
    name: 'collaboration_user_state'
    partitionKeyPath: '/user_id'
    defaultTtl: null
  }
  {
    name: 'settings'
    partitionKeyPath: '/id'
    defaultTtl: null
  }
  {
    name: 'custom_pages'
    partitionKeyPath: '/id'
    defaultTtl: null
  }
  {
    name: 'groups'
    partitionKeyPath: '/id'
    defaultTtl: null
  }
  {
    name: 'public_workspaces'
    partitionKeyPath: '/id'
    defaultTtl: null
  }
  {
    name: 'documents'
    partitionKeyPath: '/id'
    defaultTtl: null
  }
  {
    name: 'group_documents'
    partitionKeyPath: '/id'
    defaultTtl: null
  }
  {
    name: 'public_documents'
    partitionKeyPath: '/id'
    defaultTtl: null
  }
  {
    name: 'personal_file_sync_sources'
    partitionKeyPath: '/user_id'
    defaultTtl: null
  }
  {
    name: 'group_file_sync_sources'
    partitionKeyPath: '/group_id'
    defaultTtl: null
  }
  {
    name: 'public_file_sync_sources'
    partitionKeyPath: '/public_workspace_id'
    defaultTtl: null
  }
  {
    name: 'personal_workspace_identities'
    partitionKeyPath: '/user_id'
    defaultTtl: null
  }
  {
    name: 'group_workspace_identities'
    partitionKeyPath: '/group_id'
    defaultTtl: null
  }
  {
    name: 'public_workspace_identities'
    partitionKeyPath: '/public_workspace_id'
    defaultTtl: null
  }
  {
    name: 'global_workspace_identities'
    partitionKeyPath: '/global_id'
    defaultTtl: null
  }
  {
    name: 'personal_file_sync_items'
    partitionKeyPath: '/source_id'
    defaultTtl: null
  }
  {
    name: 'group_file_sync_items'
    partitionKeyPath: '/source_id'
    defaultTtl: null
  }
  {
    name: 'public_file_sync_items'
    partitionKeyPath: '/source_id'
    defaultTtl: null
  }
  {
    name: 'personal_file_sync_runs'
    partitionKeyPath: '/source_id'
    defaultTtl: null
  }
  {
    name: 'group_file_sync_runs'
    partitionKeyPath: '/source_id'
    defaultTtl: null
  }
  {
    name: 'public_file_sync_runs'
    partitionKeyPath: '/source_id'
    defaultTtl: null
  }
  {
    name: 'user_settings'
    partitionKeyPath: '/id'
    defaultTtl: null
  }
  {
    name: 'safety'
    partitionKeyPath: '/id'
    defaultTtl: null
  }
  {
    name: 'feedback'
    partitionKeyPath: '/id'
    defaultTtl: null
  }
  {
    name: 'archived_conversations'
    partitionKeyPath: '/id'
    defaultTtl: null
  }
  {
    name: 'archived_messages'
    partitionKeyPath: '/conversation_id'
    defaultTtl: null
  }
  {
    name: 'prompts'
    partitionKeyPath: '/id'
    defaultTtl: null
  }
  {
    name: 'group_prompts'
    partitionKeyPath: '/id'
    defaultTtl: null
  }
  {
    name: 'public_prompts'
    partitionKeyPath: '/id'
    defaultTtl: null
  }
  {
    name: 'file_processing'
    partitionKeyPath: '/document_id'
    defaultTtl: null
  }
  {
    name: 'personal_agents'
    partitionKeyPath: '/user_id'
    defaultTtl: null
  }
  {
    name: 'personal_actions'
    partitionKeyPath: '/user_id'
    defaultTtl: null
  }
  {
    name: 'group_agents'
    partitionKeyPath: '/group_id'
    defaultTtl: null
  }
  {
    name: 'group_actions'
    partitionKeyPath: '/group_id'
    defaultTtl: null
  }
  {
    name: 'global_agents'
    partitionKeyPath: '/id'
    defaultTtl: null
  }
  {
    name: 'global_actions'
    partitionKeyPath: '/id'
    defaultTtl: null
  }
  {
    name: 'governance_policies'
    partitionKeyPath: '/id'
    defaultTtl: null
  }
  {
    name: 'governance_item_policies'
    partitionKeyPath: '/id'
    defaultTtl: null
  }
  {
    name: 'agent_templates'
    partitionKeyPath: '/id'
    defaultTtl: null
  }
  {
    name: 'agent_facts'
    partitionKeyPath: '/scope_id'
    defaultTtl: null
  }
  {
    name: 'search_cache'
    partitionKeyPath: '/user_id'
    defaultTtl: null
  }
  {
    name: 'activity_logs'
    partitionKeyPath: '/user_id'
    defaultTtl: null
  }
  {
    name: 'notifications'
    partitionKeyPath: '/user_id'
    defaultTtl: -1
  }
  {
    name: 'approvals'
    partitionKeyPath: '/group_id'
    defaultTtl: -1
  }
  {
    name: 'msgraph_pending_actions'
    partitionKeyPath: '/user_id'
    defaultTtl: -1
  }
  {
    name: 'thoughts'
    partitionKeyPath: '/user_id'
    defaultTtl: null
  }
  {
    name: 'archive_thoughts'
    partitionKeyPath: '/user_id'
    defaultTtl: null
  }
]

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
    publicNetworkAccess: 'Enabled'  // configuration is set in post provision step in azure.yaml with post deployment script
    databaseAccountOfferType: 'Standard'
    capabilities: capacityMode == 'serverless' ? [
      {
        name: 'EnableServerless'
      }
    ] : []
    isVirtualNetworkFilterEnabled: enablePrivateNetworking ? true : false
    ipRules: enablePrivateNetworking ? allowedIpAddresses : []

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

resource cosmosContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-04-15' = [for container in cosmosContainers: {
  parent: cosmosDatabase
  name: container.name
  properties: {
    resource: union({
      id: container.name
      partitionKey: {
        paths: [
          container.partitionKeyPath
        ]
      }
    }, container.defaultTtl == null ? {} : {
      defaultTtl: container.defaultTtl
    })
    options: capacityMode == 'serverless' ? {} : {
      autoscaleSettings: {
        maxThroughput: containerAutoscaleMaxThroughput
      }
    }
  }
}]

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

output cosmosDbName string = cosmosDb.name
output cosmosDbUri string = cosmosDb.properties.documentEndpoint
