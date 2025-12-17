targetScope = 'resourceGroup'

@description('The name of the web app to configure authentication for')
param webAppName string

@description('Client ID of the Azure AD application')
param clientId string

@description('Key Vault secret URI for client secret (recommended approach)')
#disable-next-line secure-secrets-in-params   // Doesn't contain a secret
param clientSecretKeyVaultUri string = ''

@description('Azure AD tenant ID')
param tenantId string

@description('Allowed token audiences')
param allowedAudiences array = []

@description('Enable Azure AD authentication')
param enableAuthentication bool = true

@description('Authentication action when request is not authenticated')
@allowed([
  'AllowAnonymous'
  'RedirectToLoginPage'
  'Return401'
  'Return403'
])
param unauthenticatedClientAction string = 'RedirectToLoginPage'

@description('Token store enabled')
param tokenStoreEnabled bool = true

var openIdIssuerUrl = '${az.environment().authentication.loginEndpoint}/${tenantId}'

resource webApp 'Microsoft.Web/sites@2022-03-01' existing = {
  name: webAppName
}

// Configure authentication settings for the web app
resource authSettings 'Microsoft.Web/sites/config@2022-03-01' = if (enableAuthentication && !empty(clientId)) {
  name: 'authsettingsV2'
  parent: webApp
  properties: {
    globalValidation: {
      requireAuthentication: unauthenticatedClientAction != 'AllowAnonymous'
      unauthenticatedClientAction: unauthenticatedClientAction
      redirectToProvider: 'azureActiveDirectory'
    }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          openIdIssuer: openIdIssuerUrl
          clientId: clientId
          clientSecretSettingName: !empty(clientSecretKeyVaultUri) ? 'MICROSOFT_PROVIDER_AUTHENTICATION_SECRET' : null
        }
        validation: {
          jwtClaimChecks: {}
          allowedAudiences: !empty(allowedAudiences) ? allowedAudiences : [
            'api://${clientId}'
            clientId
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
        enabled: tokenStoreEnabled
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

// Output authentication configuration details
output authenticationEnabled bool = enableAuthentication && !empty(clientId)
output loginUrl string = enableAuthentication && !empty(clientId) ? 'https://${webApp.properties.defaultHostName}/.auth/login/aad' : ''
output logoutUrl string = enableAuthentication && !empty(clientId) ? 'https://${webApp.properties.defaultHostName}/.auth/logout' : ''
