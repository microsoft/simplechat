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
    disableLocalAuth: true
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

// Container definitions
resource conversationsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-04-15' = {
  parent: cosmosDatabase
  name: 'conversations'
  properties: {
    resource: {
      id: 'conversations'
      partitionKey: {
        paths: ['/id']
      }
    }
    options: {}
  }
}

resource messagesContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-04-15' = {
  parent: cosmosDatabase
  name: 'messages'
  properties: {
    resource: {
      id: 'messages'
      partitionKey: {
        paths: ['/conversation_id']
      }
    }
    options: {}
  }
}

resource settingsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-04-15' = {
  parent: cosmosDatabase
  name: 'settings'
  properties: {
    resource: {
      id: 'settings'
      partitionKey: {
        paths: ['/id']
      }
    }
    options: {}
  }
}

resource groupsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-04-15' = {
  parent: cosmosDatabase
  name: 'groups'
  properties: {
    resource: {
      id: 'groups'
      partitionKey: {
        paths: ['/id']
      }
    }
    options: {}
  }
}

resource publicWorkspacesContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-04-15' = {
  parent: cosmosDatabase
  name: 'public_workspaces'
  properties: {
    resource: {
      id: 'public_workspaces'
      partitionKey: {
        paths: ['/id']
      }
    }
    options: {}
  }
}

resource documentsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-04-15' = {
  parent: cosmosDatabase
  name: 'documents'
  properties: {
    resource: {
      id: 'documents'
      partitionKey: {
        paths: ['/id']
      }
    }
    options: {}
  }
}

resource groupDocumentsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-04-15' = {
  parent: cosmosDatabase
  name: 'group_documents'
  properties: {
    resource: {
      id: 'group_documents'
      partitionKey: {
        paths: ['/id']
      }
    }
    options: {}
  }
}

resource publicDocumentsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-04-15' = {
  parent: cosmosDatabase
  name: 'public_documents'
  properties: {
    resource: {
      id: 'public_documents'
      partitionKey: {
        paths: ['/id']
      }
    }
    options: {}
  }
}

resource userSettingsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-04-15' = {
  parent: cosmosDatabase
  name: 'user_settings'
  properties: {
    resource: {
      id: 'user_settings'
      partitionKey: {
        paths: ['/id']
      }
    }
    options: {}
  }
}

resource safetyContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-04-15' = {
  parent: cosmosDatabase
  name: 'safety'
  properties: {
    resource: {
      id: 'safety'
      partitionKey: {
        paths: ['/id']
      }
    }
    options: {}
  }
}

resource feedbackContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-04-15' = {
  parent: cosmosDatabase
  name: 'feedback'
  properties: {
    resource: {
      id: 'feedback'
      partitionKey: {
        paths: ['/id']
      }
    }
    options: {}
  }
}

resource archivedConversationsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-04-15' = {
  parent: cosmosDatabase
  name: 'archived_conversations'
  properties: {
    resource: {
      id: 'archived_conversations'
      partitionKey: {
        paths: ['/id']
      }
    }
    options: {}
  }
}

resource archivedMessagesContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-04-15' = {
  parent: cosmosDatabase
  name: 'archived_messages'
  properties: {
    resource: {
      id: 'archived_messages'
      partitionKey: {
        paths: ['/conversation_id']
      }
    }
    options: {}
  }
}

resource promptsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-04-15' = {
  parent: cosmosDatabase
  name: 'prompts'
  properties: {
    resource: {
      id: 'prompts'
      partitionKey: {
        paths: ['/id']
      }
    }
    options: {}
  }
}

resource groupPromptsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-04-15' = {
  parent: cosmosDatabase
  name: 'group_prompts'
  properties: {
    resource: {
      id: 'group_prompts'
      partitionKey: {
        paths: ['/id']
      }
    }
    options: {}
  }
}

resource publicPromptsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-04-15' = {
  parent: cosmosDatabase
  name: 'public_prompts'
  properties: {
    resource: {
      id: 'public_prompts'
      partitionKey: {
        paths: ['/id']
      }
    }
    options: {}
  }
}

resource fileProcessingContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-04-15' = {
  parent: cosmosDatabase
  name: 'file_processing'
  properties: {
    resource: {
      id: 'file_processing'
      partitionKey: {
        paths: ['/document_id']
      }
    }
    options: {}
  }
}

resource personalAgentsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-04-15' = {
  parent: cosmosDatabase
  name: 'personal_agents'
  properties: {
    resource: {
      id: 'personal_agents'
      partitionKey: {
        paths: ['/user_id']
      }
    }
    options: {}
  }
}

resource personalActionsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-04-15' = {
  parent: cosmosDatabase
  name: 'personal_actions'
  properties: {
    resource: {
      id: 'personal_actions'
      partitionKey: {
        paths: ['/user_id']
      }
    }
    options: {}
  }
}

resource groupMessagesContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-04-15' = {
  parent: cosmosDatabase
  name: 'group_messages'
  properties: {
    resource: {
      id: 'group_messages'
      partitionKey: {
        paths: ['/conversation_id']
      }
    }
    options: {}
  }
}

resource groupConversationsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-04-15' = {
  parent: cosmosDatabase
  name: 'group_conversations'
  properties: {
    resource: {
      id: 'group_conversations'
      partitionKey: {
        paths: ['/id']
      }
    }
    options: {}
  }
}

resource groupAgentsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-04-15' = {
  parent: cosmosDatabase
  name: 'group_agents'
  properties: {
    resource: {
      id: 'group_agents'
      partitionKey: {
        paths: ['/group_id']
      }
    }
    options: {}
  }
}

resource groupActionsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-04-15' = {
  parent: cosmosDatabase
  name: 'group_actions'
  properties: {
    resource: {
      id: 'group_actions'
      partitionKey: {
        paths: ['/group_id']
      }
    }
    options: {}
  }
}

resource globalAgentsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-04-15' = {
  parent: cosmosDatabase
  name: 'global_agents'
  properties: {
    resource: {
      id: 'global_agents'
      partitionKey: {
        paths: ['/id']
      }
    }
    options: {}
  }
}

resource globalActionsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-04-15' = {
  parent: cosmosDatabase
  name: 'global_actions'
  properties: {
    resource: {
      id: 'global_actions'
      partitionKey: {
        paths: ['/id']
      }
    }
    options: {}
  }
}

resource agentFactsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-04-15' = {
  parent: cosmosDatabase
  name: 'agent_facts'
  properties: {
    resource: {
      id: 'agent_facts'
      partitionKey: {
        paths: ['/scope_id']
      }
    }
    options: {}
  }
}

resource searchCacheContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-04-15' = {
  parent: cosmosDatabase
  name: 'search_cache'
  properties: {
    resource: {
      id: 'search_cache'
      partitionKey: {
        paths: ['/user_id']
      }
    }
    options: {}
  }
}

resource activityLogsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-04-15' = {
  parent: cosmosDatabase
  name: 'activity_logs'
  properties: {
    resource: {
      id: 'activity_logs'
      partitionKey: {
        paths: ['/user_id']
      }
    }
    options: {}
  }
}

// Grant the managed identity access to cosmos db as a contributor
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

// Grant the managed identity Cosmos DB Built-in Data Contributor role
resource cosmosDataContributorRole 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2023-04-15' = {
  name: guid(cosmosDb.id, managedIdentityPrincipalId, 'cosmos-data-contributor')
  parent: cosmosDb
  properties: {
    // Cosmos DB Built-in Data Contributor role definition ID
    roleDefinitionId: '${cosmosDb.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002'
    principalId: managedIdentityPrincipalId
    scope: cosmosDb.id
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

output cosmosDbName string = cosmosDb.name
