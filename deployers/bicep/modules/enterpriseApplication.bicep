targetScope = 'resourceGroup'

@description('The name of the application to be deployed')
param appName string

@description('The environment name (dev/test/prod)')
param environment string

@description('Resource tags')
param tags object

@description('The redirect URI for the application')
param redirectUri string

@description('Enable enterprise application deployment')
param enableEnterpriseApp bool = true

@description('Application description')
param appDescription string = 'Enterprise application for ${appName} ${environment} environment'

@description('Application display name')
param displayName string = '${appName}-${environment}-app'

@description('Required application permissions/scopes')
param requiredResourceAccess array = [
  {
    resourceAppId: '00000003-0000-0000-c000-000000000000' // Microsoft Graph
    resourceAccess: [
      {
        id: 'e1fe6dd8-ba31-4d61-89e7-88639da4683d' // User.Read
        type: 'Scope'
      }
    ]
  }
]

@description('Supported account types for the application')
@allowed([
  'AzureADMyOrg'
  'AzureADMultipleOrgs' 
  'AzureADandPersonalMicrosoftAccount'
])
param signInAudience string = 'AzureADMyOrg'

// Note: Azure AD App Registration requires Microsoft Graph API which is not directly supported in Bicep
// This module creates the configuration that can be used by Azure CLI or PowerShell scripts
// The actual app registration will need to be created using az ad app create or equivalent

var appRegistrationConfig = {
  displayName: displayName
  description: appDescription
  signInAudience: signInAudience
  web: {
    redirectUris: [
      redirectUri
      '${redirectUri}/.auth/login/aad/callback'
    ]
    implicitGrantSettings: {
      enableAccessTokenIssuance: false
      enableIdTokenIssuance: true
    }
  }
  requiredResourceAccess: requiredResourceAccess
  api: {
    requestedAccessTokenVersion: 2
  }
}

// Output the configuration that can be used for app registration
output appRegistrationConfig object = appRegistrationConfig
output displayName string = displayName
output redirectUri string = redirectUri
output callbackUri string = '${redirectUri}/.auth/login/aad/callback'

// Output placeholder values that would be populated after app registration
output clientId string = '' // Will be populated after app registration
output tenantId string = tenant().tenantId