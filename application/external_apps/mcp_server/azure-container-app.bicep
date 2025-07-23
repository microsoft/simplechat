param containerAppName string = 'simplechat-mcp-server'
param location string = resourceGroup().location
param containerAppEnvironmentName string = 'simplechat-mcp-env'
param containerImage string
param simpleChatBaseUrl string
@secure()
param simpleChatBearerToken string
param logLevel string = 'INFO'

var logAnalyticsWorkspaceName = '${containerAppName}-logs'

resource logAnalyticsWorkspace 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: logAnalyticsWorkspaceName
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

resource containerAppEnvironment 'Microsoft.App/managedEnvironments@2023-05-01' = {
  name: containerAppEnvironmentName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalyticsWorkspace.properties.customerId
        sharedKey: logAnalyticsWorkspace.listKeys().primarySharedKey
      }
    }
  }
}

resource containerApp 'Microsoft.App/containerApps@2023-05-01' = {
  name: containerAppName
  location: location
  properties: {
    managedEnvironmentId: containerAppEnvironment.id
    configuration: {
      secrets: [
        {
          name: 'bearer-token'
          value: simpleChatBearerToken
        }
      ]
      ingress: {
        external: false
        targetPort: 8080
        transport: 'http'
      }
    }
    template: {
      containers: [
        {
          name: 'simplechat-mcp-server'
          image: containerImage
          env: [
            {
              name: 'SIMPLECHAT_MCP_SIMPLECHAT_BASE_URL'
              value: simpleChatBaseUrl
            }
            {
              name: 'SIMPLECHAT_MCP_SIMPLECHAT_BEARER_TOKEN'
              secretRef: 'bearer-token'
            }
            {
              name: 'SIMPLECHAT_MCP_LOG_LEVEL'
              value: logLevel
            }
          ]
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
          probes: [
            {
              type: 'liveness'
              httpGet: {
                path: '/health'
                port: 8080
              }
              initialDelaySeconds: 30
              periodSeconds: 30
            }
            {
              type: 'readiness'
              httpGet: {
                path: '/ready'
                port: 8080
              }
              initialDelaySeconds: 10
              periodSeconds: 10
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 3
        rules: [
          {
            name: 'cpu-scaling'
            custom: {
              type: 'cpu'
              metadata: {
                type: 'Utilization'
                value: '70'
              }
            }
          }
        ]
      }
    }
  }
}

output containerAppFQDN string = containerApp.properties.latestRevisionFqdn