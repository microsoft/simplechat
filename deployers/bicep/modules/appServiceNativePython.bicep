targetScope = 'resourceGroup'

param location string
param nativeWebAppName string
param tags object

param enableDiagLogging bool
param logAnalyticsId string

param appServicePlanId string
param azurePlatform string
param cosmosDbName string
param searchServiceName string
param openAiServiceName string
param openAiEndpoint string
param openAiResourceGroupName string
param documentIntelligenceServiceName string
param appInsightsName string
param enterpriseAppClientId string = ''
param authenticationType string
param startupCommand string = 'python -m gunicorn -c gunicorn.conf.py app:app'

@secure()
param enterpriseAppClientSecret string = ''
param keyVaultUri string
param enablePrivateNetworking bool
param appServiceSubnetId string = ''

// --- Custom Azure Environment Parameters (for 'custom' azureEnvironment) ---
@description('Custom blob storage URL suffix, e.g. blob.core.usgovcloudapi.net')
param customBlobStorageSuffix string?
@description('Custom Graph API URL, e.g. https://graph.microsoft.us')
param customGraphUrl string?
@description('Custom Identity URL, e.g. https://login.microsoftonline.us')
param customIdentityUrl string?
@description('Custom Resource Manager URL, e.g. https://management.usgovcloudapi.net')
param customResourceManagerUrl string?
@description('Custom Cognitive Services scope ex: https://cognitiveservices.azure.com/.default')
param customCognitiveServicesScope string?
@description('Custom search resource URL for token audience, e.g. https://search.azure.us')
param customSearchResourceUrl string?
@description('Custom Video Indexer endpoint, e.g. https://api.videoindexer.ai')
param customVideoIndexerEndpoint string?

var tenantId = tenant().tenantId
var identityLoginEndpoint = empty(customIdentityUrl) ? az.environment().authentication.loginEndpoint : customIdentityUrl!
var normalizedIdentityLoginEndpoint = endsWith(identityLoginEndpoint, '/') ? identityLoginEndpoint : '${identityLoginEndpoint}/'
var openIdIssuer = '${normalizedIdentityLoginEndpoint}${tenantId}/'
var openIdMetadataUrl = '${openIdIssuer}v2.0/.well-known/openid-configuration'

// Import diagnostic settings configurations
module diagnosticConfigs 'diagnosticSettings.bicep' = if (enableDiagLogging) {
  name: 'nativeDiagnosticConfigs'
}

resource cosmosDb 'Microsoft.DocumentDB/databaseAccounts@2023-04-15' existing = {
  name: cosmosDbName
}

resource searchService 'Microsoft.Search/searchServices@2025-05-01' existing = {
  name: searchServiceName
}

resource documentIntelligence 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: documentIntelligenceServiceName
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' existing = {
  name: appInsightsName
}

resource webApp 'Microsoft.Web/sites@2022-03-01' = {
  name: toLower(nativeWebAppName)
  location: location
  // Native Python App Service used to compare custom-hostname redirect behavior
  // against the primary containerized SimpleChat deployment.
  kind: 'app,linux'
  properties: {
    serverFarmId: appServicePlanId
    virtualNetworkSubnetId: appServiceSubnetId != '' ? appServiceSubnetId : null
    publicNetworkAccess: 'Enabled'

    siteConfig: {
      linuxFxVersion: 'PYTHON|3.12'
      appCommandLine: startupCommand
      alwaysOn: true
      ftpsState: 'Disabled'
      healthCheckPath: '/external/healthcheck'
      vnetRouteAllEnabled: enablePrivateNetworking ? true : false
      appSettings: [
        { name: 'AZURE_ENVIRONMENT', value: azurePlatform }
        { name: 'REDIS_ENTRA_TOKEN_SCOPE', value: 'https://redis.azure.com/.default' }
        { name: 'SIMPLECHAT_RUN_BACKGROUND_TASKS', value: '0' }
        { name: 'SCM_DO_BUILD_DURING_DEPLOYMENT', value: 'true' }
        { name: 'AZURE_SUBSCRIPTION_ID', value: subscription().subscriptionId }
        { name: 'AZURE_RESOURCE_GROUP', value: resourceGroup().name }
        { name: 'AZURE_COSMOS_ENDPOINT', value: cosmosDb.properties.documentEndpoint }
        { name: 'AZURE_COSMOS_ACCOUNT_NAME', value: cosmosDb.name }
        { name: 'AZURE_COSMOS_DATABASE_NAME', value: 'SimpleChat' }
        { name: 'AZURE_COSMOS_AUTHENTICATION_TYPE', value: toLower(authenticationType) }

        ...(authenticationType == 'key'
          ? [{ name: 'AZURE_COSMOS_KEY', value: cosmosDb.listKeys().primaryMasterKey }]
          : [])

        { name: 'TENANT_ID', value: tenantId }
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
        { name: 'WEBSITE_AUTH_AAD_ALLOWED_TENANTS', value: tenantId }
        { name: 'AZURE_OPENAI_RESOURCE_NAME', value: openAiServiceName }
        { name: 'AZURE_OPENAI_RESOURCE_GROUP_NAME', value: openAiResourceGroupName }
        { name: 'AZURE_OPENAI_URL', value: openAiEndpoint }
        { name: 'VIDEO_INDEXER_ARM_API_VERSION', value: azurePlatform == 'usgovernment' ? '2024-01-01' : '2025-04-01' }
        { name: 'AZURE_SEARCH_SERVICE_NAME', value: searchService.name }

        ...(authenticationType == 'key'
          ? [
              {
                name: 'AZURE_SEARCH_API_KEY'
                value: searchService.listAdminKeys().primaryKey
              }
            ]
          : [])

        { name: 'AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT', value: documentIntelligence.properties.endpoint }

        ...(authenticationType == 'key'
          ? [
              {
                name: 'AZURE_DOCUMENT_INTELLIGENCE_API_KEY'
                value: documentIntelligence.listKeys().key1
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
        ...(azurePlatform == 'custom' ? [
          { name: 'CUSTOM_GRAPH_URL_VALUE', value: customGraphUrl ?? '' }
          { name: 'CUSTOM_IDENTITY_URL_VALUE', value: customIdentityUrl ?? '' }
          { name: 'CUSTOM_RESOURCE_MANAGER_URL_VALUE', value: customResourceManagerUrl ?? '' }
          { name: 'CUSTOM_BLOB_STORAGE_URL_VALUE', value: customBlobStorageSuffix ?? '' }
          { name: 'CUSTOM_COGNITIVE_SERVICES_URL_VALUE', value: customCognitiveServicesScope ?? '' }
          { name: 'CUSTOM_SEARCH_RESOURCE_MANAGER_URL_VALUE', value: customSearchResourceUrl ?? '' }
          { name: 'CUSTOM_VIDEO_INDEXER_ENDPOINT', value: customVideoIndexerEndpoint ?? '' }
          { name: 'KEY_VAULT_DOMAIN', value: az.environment().suffixes.keyvaultDns }
          { name: 'CUSTOM_OIDC_METADATA_URL_VALUE', value: openIdMetadataUrl }
        ] : [])
      ]
    }
    clientAffinityEnabled: false
    httpsOnly: true
  }
  identity: {
    type: 'SystemAssigned'
  }
  tags: union(tags, {
    'azd-service-name': 'web-native'
    'simplechat-hosting-model': 'native-python'
  })
}

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
          openIdIssuer: openIdIssuer
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
    platform: {
      enabled: true
      runtimeVersion: '~1'
    }
  }
}

output name string = webApp.name
output principalId string = webApp.identity.principalId
