targetScope = 'resourceGroup'

param location string
param appName string
param environment string
param tags object

param logAnalyticsId string

// application insights resource
resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: toLower('${appName}-${environment}-ai')
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalyticsId
  }
  tags: tags
}

output appInsightsName string = appInsights.name
