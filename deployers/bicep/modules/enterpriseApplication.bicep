targetScope = 'resourceGroup'

@description('The name of the application to be deployed')
param appName string

@description('The environment name (dev/test/prod)')
param environment string

@description('The redirect URI for the application')
param redirectUri string

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
      {
        id: '14dad69e-099b-42c9-810b-d002981feec1' // Profile.Read
        type: 'Scope'
      }
      {
        id: '37f7f235-527c-4136-accd-4a02d197296e' // openid
        type: 'Scope'
      }
      {
        id: '7427e0e9-2fba-42fe-b0c0-848c9e6a8182' // offline_access
        type: 'Scope'
      }
      {
        id: '64a6cdd6-aab1-4aaf-94b8-3cc8405e90d0' // email
        type: 'Scope'
      }
      {
        id: '5f8c59db-677d-491f-a6b8-5f174b11ec1d' // Group.Read.All
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
