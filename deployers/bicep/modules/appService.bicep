targetScope = 'resourceGroup'

param location string
param appName string
param environment string
param tags object

param enableDiagLogging bool
param logAnalyticsId string

param acrName string
param appServicePlanId string
param containerImageName string
param azurePlatform string
param cosmosDbName string
param searchServiceName string
param openAiServiceName string
param openAiResourceGroupName string
param documentIntelligenceServiceName string
param appInsightsName string
param enterpriseAppClientId string = ''
param authenticationType string

@secure()
param enterpriseAppClientSecret string = ''
param keyVaultUri string

// Import diagnostic settings configurations
module diagnosticConfigs 'diagnosticSettings.bicep' = if (enableDiagLogging) {
  name: 'diagnosticConfigs'
}

resource acrService 'Microsoft.ContainerRegistry/registries@2025-04-01' existing = {
  name: acrName
}

resource cosmosDb 'Microsoft.DocumentDB/databaseAccounts@2023-04-15' existing = {
  name: cosmosDbName
}

resource searchService 'Microsoft.Search/searchServices@2025-05-01' existing = {
  name: searchServiceName
}

resource openAiService 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: openAiServiceName
}

resource documentIntelligence 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: documentIntelligenceServiceName
}
resource appInsights 'Microsoft.Insights/components@2020-02-02' existing = {
  name: appInsightsName
}

var acrDomain = azurePlatform == 'AzureUSGovernment' ? '.azurecr.us' : '.azurecr.io'

// add web app
resource webApp 'Microsoft.Web/sites@2022-03-01' = {
  name: toLower('${appName}-${environment}-app')
  location: location
  kind: 'app,linux,container'
  properties: {
    serverFarmId: appServicePlanId
    siteConfig: {
      linuxFxVersion: 'DOCKER|${containerImageName}'
      acrUseManagedIdentityCreds: true
      acrUserManagedIdentityID: '' // managedIdentityId
      alwaysOn: true
      ftpsState: 'Disabled'
      healthCheckPath: '/external/healthcheck'
      appSettings: [
        { name: 'AZURE_ENDPOINT', value: azurePlatform == 'AzureUSGovernment' ? 'usgovernment' : 'public' }
        { name: 'SCM_DO_BUILD_DURING_DEPLOYMENT', value: 'false' }
        { name: 'AZURE_COSMOS_ENDPOINT', value: cosmosDb.properties.documentEndpoint }
        { name: 'AZURE_COSMOS_AUTHENTICATION_TYPE', value: toLower(authenticationType) }

        // Only add this setting if authenticationType is 'key'
        ...(authenticationType == 'key'
          ? [{ name: 'AZURE_COSMOS_KEY', value: '@Microsoft.KeyVault(SecretUri=${keyVaultUri}secrets/cosmos-db-key)' }]
          : [])

        { name: 'TENANT_ID', value: tenant().tenantId }
        { name: 'CLIENT_ID', value: enterpriseAppClientId }
        {
          name: 'SECRET_KEY'
          value: !empty(enterpriseAppClientSecret)
            ? enterpriseAppClientSecret
            : '@Microsoft.KeyVault(SecretUri=${keyVaultUri}secrets/enterprise-app-client-secret)'
        }
        {
          name: 'MICROSOFT_PROVIDER_AUTHENTICATION_SECRET'
          value: '@Microsoft.KeyVault(SecretUri=${keyVaultUri}secrets/enterprise-app-client-secret)'
        }
        { name: 'DOCKER_REGISTRY_SERVER_URL', value: 'https://${acrService.name}${acrDomain}' }

        // Only add this setting if authenticationType is 'key'
        ...(authenticationType == 'key'
          ? [{ name: 'DOCKER_REGISTRY_SERVER_USERNAME', value: acrService.listCredentials().username }]
          : [])

        // Only add this setting if authenticationType is 'key'
        ...(authenticationType == 'key'
          ? [
              {
                name: 'DOCKER_REGISTRY_SERVER_PASSWORD'
                value: '@Microsoft.KeyVault(SecretUri=${keyVaultUri}secrets/container-registry-key)'
              }
            ]
          : [])

        { name: 'WEBSITE_AUTH_AAD_ALLOWED_TENANTS', value: tenant().tenantId }
        { name: 'AZURE_OPENAI_RESOURCE_NAME', value: openAiService.name }
        { name: 'AZURE_OPENAI_RESOURCE_GROUP_NAME', value: openAiResourceGroupName }
        { name: 'AZURE_OPENAI_URL', value: openAiService.properties.endpoint }
        { name: 'AZURE_SEARCH_SERVICE_NAME', value: searchService.name }
        // Only add this setting if authenticationType is 'key'
        ...(authenticationType == 'key'
          ? [
              {
                name: 'AZURE_SEARCH_API_KEY'
                value: '@Microsoft.KeyVault(SecretUri=${keyVaultUri}secrets/search-service-key)'
              }
            ]
          : [])
        { name: 'AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT', value: documentIntelligence.properties.endpoint }
        // Only add this setting if authenticationType is 'key'
        ...(authenticationType == 'key'
          ? [
              {
                name: 'AZURE_DOCUMENT_INTELLIGENCE_API_KEY'
                value: '@Microsoft.KeyVault(SecretUri=${keyVaultUri}secrets/document-intelligence-key)'
              }
            ]
          : [])
        { name: 'APPINSIGHTS_INSTRUMENTATIONKEY', value: appInsights.properties.InstrumentationKey }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
        { name: 'APPINSIGHTS_PROFILERFEATURE_VERSION', value: '1.0.0' }
        { name: 'APPINSIGHTS_SNAPSHOTFEATURE_VERSION', value: '1.0.0' }
        { name: 'APPLICATIONINSIGHTS_CONFIGURATION_CONTENT', value: '' }
        { name: 'ApplicationInsightsAgent_EXTENSION_VERSION', value: '~3' }
        { name: 'DiagnosticServices_EXTENSION_VERSION', value: '~3' }
        { name: 'InstrumentationEngine_EXTENSION_VERSION', value: 'disabled' }
        { name: 'SnapshotDebugger_EXTENSION_VERSION', value: 'disabled' }
        { name: 'XDT_MicrosoftApplicationInsights_BaseExtensions', value: 'disabled' }
        { name: 'XDT_MicrosoftApplicationInsights_Mode', value: 'recommended' }
        { name: 'XDT_MicrosoftApplicationInsights_PreemptSdk', value: 'disabled' }
      ]
    }
    clientAffinityEnabled: false
    httpsOnly: true
  }
  identity: {
    type: 'SystemAssigned'
  }
  tags: union(tags, { 'azd-service-name': 'web' })
}

// configure application logging retention
resource webAppLogging 'Microsoft.Web/sites/config@2022-03-01' = {
  name: 'logs'
  parent: webApp
  properties: {
    httpLogs: {
      fileSystem: {
        enabled: true
        retentionInDays: 7
        retentionInMb: 35
      }
    }
  }
}

// configure diagnostic settings for web app
resource webAppDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (enableDiagLogging) {
  name: toLower('${webApp.name}-diagnostics')
  scope: webApp
  properties: {
    workspaceId: logAnalyticsId
    #disable-next-line BCP318 // expect one value to be null
    logs: diagnosticConfigs.outputs.webAppLogCategories
    #disable-next-line BCP318 // expect one value to be null
    metrics: diagnosticConfigs.outputs.standardMetricsCategories
  }
}

// Configure authentication settings for the web app
resource authSettings 'Microsoft.Web/sites/config@2022-03-01' = {
  name: 'authsettingsV2'
  parent: webApp
  properties: {
    globalValidation: {
      requireAuthentication: true
      unauthenticatedClientAction: 'RedirectToLoginPage'
      redirectToProvider: 'azureActiveDirectory'
    }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          openIdIssuer: 'https://sts.windows.net/${tenant().tenantId}/'
          clientId: enterpriseAppClientId
          clientSecretSettingName: 'MICROSOFT_PROVIDER_AUTHENTICATION_SECRET'
        }
        validation: {
          jwtClaimChecks: {}
          allowedAudiences: [
            'api://${enterpriseAppClientId}'
            enterpriseAppClientId
          ]
        }
        isAutoProvisioned: false
      }
    }
    login: {
      routes: {
        logoutEndpoint: '/.auth/logout'
      }
      tokenStore: {
        enabled: true
        tokenRefreshExtensionHours: 72
        fileSystem: {
          directory: '/home/data/.auth'
        }
      }
      preserveUrlFragmentsForLogins: false
      allowedExternalRedirectUrls: []
      cookieExpiration: {
        convention: 'FixedTime'
        timeToExpiration: '08:00:00'
      }
      nonce: {
        validateNonce: true
        nonceExpirationInterval: '00:05:00'
      }
    }
    httpSettings: {
      requireHttps: true
      routes: {
        apiPrefix: '/.auth'
      }
      forwardProxy: {
        convention: 'NoProxy'
      }
    }
  }
}

// Outputs
output name string = webApp.name
output defaultHostName string = webApp.properties.defaultHostName
output resourceId string = webApp.id
