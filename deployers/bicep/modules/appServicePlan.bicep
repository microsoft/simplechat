targetScope = 'resourceGroup'

param location string
param appName string
param environment string
param tags object

param enableDiagLogging bool
param logAnalyticsId string

// Import diagnostic settings configurations
module diagnosticConfigs 'diagnosticSettings.bicep' = if (enableDiagLogging) {
  name: 'diagnosticConfigs'
}

// add app service plan
resource appServicePlan 'Microsoft.Web/serverfarms@2022-03-01' = {
  name: toLower('${appName}-${environment}-asp')
  location: location
  sku: {
    name: 'P1v3'
    tier: 'PremiumV3'
    size: 'P1v3'
    capacity: 1
  }
  kind: 'app,linux,container'
  properties: {
    reserved: true
    perSiteScaling: false
    maximumElasticWorkerCount: 1
    hyperV: false
    targetWorkerCount: 0
    targetWorkerSizeId: 0
  }
  tags: tags
}

// configure diagnostic settings for app service plan
resource appServicePlanDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (enableDiagLogging) {
  name: toLower('${appServicePlan.name}-diagnostics')
  scope: appServicePlan
  properties: {
    workspaceId: logAnalyticsId
    logs: [] // App Service Plans typically don't have logs
    #disable-next-line BCP318 // expect one value to be null
    metrics: diagnosticConfigs.outputs.standardMetricsCategories
  }
}

output appServicePlanId string = appServicePlan.id
