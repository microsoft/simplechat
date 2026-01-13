targetScope = 'resourceGroup'

param location string
param appName string
param environment string
param tags object

// log analytics workspace 
resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: toLower('${appName}-${environment}-la')
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
  }
  tags: tags
}

output logAnalyticsId string = logAnalytics.id
