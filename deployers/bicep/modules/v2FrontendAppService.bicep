targetScope = 'resourceGroup'

/*
  Optional App Service that hosts the V2 React UI as a standalone static site.

  This is NOT the default deployment. By default the Flask App Service serves the compiled
  V2 bundle itself at /v2, which keeps the browser on a single origin so the Entra session
  cookie, the same-origin CSRF check and the default-src 'self' CSP all work unchanged.

  Deploying this module splits the SPA onto its own origin. That buys independent deploy
  and scale for the front end, at the cost of requiring cross-origin configuration on the
  API app service:

    - V2_UI_ALLOWED_ORIGIN must be set on the Flask app to this app's https URL. That one
      setting turns on CORS for the origin, adds it to CSRF_TRUSTED_ORIGINS, and switches
      the session cookie to SameSite=None; Secure.
    - The SPA bundle must be built with VITE_API_BASE pointing at the Flask app's origin,
      via the V2_UI_API_BASE Docker build argument.
    - The Entra app registration needs this app's URL added as a redirect URI.

  Because the session cookie becomes a third-party cookie in this topology, browsers that
  block third-party cookies will break the split deployment. Prefer the default
  same-origin layout unless independent front-end deployment is specifically required.
*/

@description('Azure region for the V2 UI app service.')
param location string

@minLength(2)
@maxLength(60)
@description('Name of the App Service hosting the V2 React UI.')
param v2WebAppName string

@description('Resource tags applied to the app service.')
param tags object

@description('Resource id of the App Service Plan to host this app on.')
param appServicePlanId string

@description('Enable diagnostic logging to Log Analytics.')
param enableDiagLogging bool = false

@description('Log Analytics workspace resource id. Required when enableDiagLogging is true.')
param logAnalyticsId string = ''

@description('Application Insights resource name, used for browser telemetry. Optional.')
param appInsightsName string = ''

@description('Restrict the app to a VNet-integrated subnet when private networking is enabled.')
param enablePrivateNetworking bool = false

@description('Subnet id used for VNet integration. Required when enablePrivateNetworking is true.')
param appServiceSubnetId string = ''

module diagnosticConfigs 'diagnosticSettings.bicep' = if (enableDiagLogging) {
  name: 'v2UiDiagnosticConfigs'
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' existing = if (!empty(appInsightsName)) {
  name: appInsightsName
}

resource v2WebApp 'Microsoft.Web/sites@2023-12-01' = {
  name: v2WebAppName
  location: location
  // azd uses this tag to work out which service in azure.yaml maps to this resource.
  tags: union(tags, { 'azd-service-name': 'v2ui' })
  kind: 'app,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: appServicePlanId
    httpsOnly: true
    virtualNetworkSubnetId: enablePrivateNetworking && !empty(appServiceSubnetId)
      ? appServiceSubnetId
      : null
    siteConfig: {
      linuxFxVersion: 'NODE|20-lts'
      alwaysOn: true
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      http20Enabled: true
      // pm2's --spa mode rewrites unknown paths to index.html, which is what makes
      // client-side routes survive a refresh or a deep link. Without it, /v2/admin would
      // 404 on the static host.
      appCommandLine: 'pm2 serve /home/site/wwwroot --no-daemon --spa'
      healthCheckPath: '/'
      appSettings: concat(
        [
          {
            name: 'SCM_DO_BUILD_DURING_DEPLOYMENT'
            value: 'false'
          }
          {
            name: 'WEBSITE_RUN_FROM_PACKAGE'
            value: '1'
          }
        ],
        empty(appInsightsName)
          ? []
          : [
              {
                name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
                #disable-next-line BCP318 // resource exists when appInsightsName is set
                value: appInsights.properties.ConnectionString
              }
            ]
      )
    }
  }
}

resource v2WebAppDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (enableDiagLogging && !empty(logAnalyticsId)) {
  scope: v2WebApp
  name: '${v2WebAppName}-diagnostics'
  properties: {
    workspaceId: logAnalyticsId
    #disable-next-line BCP318 // module exists when enableDiagLogging is true
    logs: diagnosticConfigs.outputs.webAppLogCategories
    #disable-next-line BCP318 // module exists when enableDiagLogging is true
    metrics: diagnosticConfigs.outputs.standardMetricsCategories
  }
}

@description('Name of the V2 UI app service.')
output name string = v2WebApp.name

@description('Default hostname of the V2 UI app service.')
output defaultHostName string = v2WebApp.properties.defaultHostName

@description('HTTPS origin of the V2 UI. Set this as V2_UI_ALLOWED_ORIGIN on the API app.')
output origin string = 'https://${v2WebApp.properties.defaultHostName}'

@description('System-assigned managed identity principal id.')
output principalId string = v2WebApp.identity.principalId
