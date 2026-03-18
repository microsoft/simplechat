# Microsoft Teams App Configuration

This guide covers how to configure SimpleChat as a Microsoft Teams application with Single Sign-On (SSO) support.

## Overview

SimpleChat supports Teams SSO using the On-Behalf-Of (OBO) flow. When embedded in Teams, users are automatically authenticated without needing to log in separately.

## Prerequisites

- Azure AD App Registration (same one used for web app authentication)
- Access to Azure Portal with appropriate permissions
- Teams Admin access to upload custom apps

## Azure AD App Registration Configuration for Teams SSO

### 1. Expose an API

Configure your app to expose an API for Teams SSO:

1. Navigate to **Azure Portal** → **Azure Active Directory** → **App registrations**
2. Select your application
3. Go to **Expose an API**

#### Set Application ID URI

1. Click **Set** next to "Application ID URI"
2. Set it to: `api://{your-app-domain}/{CLIENT_ID}`
   - Example: `api://myapp.azurewebsites.net/12345678-1234-1234-1234-123456789abc`
3. Click **Save**

#### Add a Scope

1. Click **Add a scope**
2. Configure the scope:
   - **Scope name**: `access_as_user`
   - **Who can consent**: Admins and users
   - **Admin consent display name**: `Access SimpleChat as the signed-in user`
   - **Admin consent description**: `Allow Teams to call the app's web APIs as the current user`
   - **User consent display name**: `Access SimpleChat on your behalf`
   - **User consent description**: `Allow Teams to access SimpleChat on your behalf`
   - **State**: Enabled
3. Click **Add scope**

### 2. Pre-authorize Microsoft Teams Applications

To enable SSO without additional consent prompts, pre-authorize Teams clients:

1. In **Expose an API**, scroll to **Authorized client applications**
2. Click **Add a client application**
3. Add the following client IDs (one at a time):

   **Teams Web Client:**
   ```
   5e3ce6c0-2b1f-4285-8d4b-75ee78787346
   ```

   **Teams Desktop Client:**
   ```
   1fec8e78-bce4-4aaf-ab1b-5451cc387264
   ```

   **Teams Web Client (Alternative):**
   ```
   4345a7b9-9a63-4910-a426-35363201d503
   ```

4. For each client ID:
   - Paste the client ID
   - Check the `access_as_user` scope
   - Click **Add application**

## Environment Variables

Ensure these environment variables are set:

```bash
# Required
ENABLE_TEAMS_SSO=true
CLIENT_ID=your-azure-ad-client-id
TENANT_ID=your-azure-ad-tenant-id
MICROSOFT_PROVIDER_AUTHENTICATION_SECRET=your-client-secret

# Teams Frame Ancestors (adjust domains), needed only if not commercial or AzureUSGovernment
TEAMS_FRAME_ANCESTORS=https://teams.microsoft.com https://*.teams.microsoft.com

# Teams Frame Origins (adjust domains), needed only if not commercial or AzureUSGovernment
CUSTOM_TEAMS_ORIGINS=["https://teams.microsoft.com", "https://*.teams.microsoft.com"]
```

## Disable App Service Authentication

App Service Authentication (EasyAuth) must be disabled for Teams SSO to work in the thick client due to login.microsoftonline.com frame restrictions.

## Teams App Manifest Configuration

Create or update your Teams app manifest (`manifest.json`), see [teams_app](../../application/teams_app) folder for template.

### Key Manifest Fields for SSO

- **id**: Teams app ID, can be AD Client ID
- **staticTabs.contentUrl**: URL to open in Teams
- **staticTabs.websiteUrl**: URL to use when *Open Website* selected
- **webApplicationInfo.id**: Your Azure AD Client ID
- **webApplicationInfo.resource**: The Application ID URI from App Registration Expore API page
- **validDomains**: Include your app domain and Azure AD login domains
- **contentUrl**: Include path /login?teams=true to trigger Teams SSO

## Testing Teams SSO

### 1. Upload to Teams

1. Package your Teams app, see [teams_app](../../application/teams_app):
   - Create a `.zip` file containing:
     - `manifest.json`
     - `color.png` (192x192)
     - `outline.png` (32x32 transparent)

2. Upload to Teams:
   - Go to Teams → Apps → **Manage your apps**
   - Click **Upload an app** → **Upload a custom app**
   - Select your `.zip` file

### 2. Troubleshooting

#### "Failed to get authentication token"
- Verify pre-authorized client applications are configured correctly
- Check Application ID URI matches Teams manifest exactly
- Ensure `access_as_user` scope exists and is authorized

#### "Token exchange failed: AADSTS65001"
- The Application ID URI in Azure AD must match the `resource` in Teams manifest
- Format: `api://{domain}/{client-id}`

#### "Consent Required"
- Grant admin consent for API permissions in Azure AD
- Or have users consent individually on first login

#### "Not in Teams context"
- App falls back to standard Azure AD login (expected behavior)
- Verify ENABLE_TEAMS_SSO env var is set to 'true'

#### "Debugging Teams Thick Client with Dev Tools"
Enable thick client dev tools by creating file *%LOCALAPPDATA%\Packages\MSTeams_8wekyb3d8bbwe\LocalCache\Microsoft\MSTeams\configuration.json* with content below and restarting Teams

```json
{
  "core/devMenuEnabled": true
}
```

Access thick client dev tools
- Right click Teams in system tray
- Select *Engineering Tools* -> *Open Dev Tools (Main Window)*

## Architecture Flow

### Teams SSO Flow

```
1. User opens app in Teams
   ↓
2. login.html loads with ?teams=true
   ↓
3. JavaScript detects Teams context (microsoftTeams.app.initialize)
   ↓
4. Request Teams SSO token (microsoftTeams.authentication.getAuthToken)
   ↓
5. Send token to backend (/auth/teams/token-exchange)
   ↓
6. Backend exchanges token using OBO flow (MSAL acquire_token_on_behalf_of)
   ↓
7. Backend stores session and returns success
   ↓
8. Frontend redirects to /chats
```

### Web Browser Flow (Fallback)

```
1. User opens app in browser
   ↓
2. login.html loads
   ↓
3. JavaScript attempts Teams detection (fails)
   ↓
4. Redirects to standard Azure AD login
   ↓
5. User authenticates via Azure AD
   ↓
6. Redirected back to app with authorization code
   ↓
7. Backend exchanges code for tokens
   ↓
8. Redirects to /chats
```

## Security Considerations

1. **Token Validation**: All tokens are validated by MSAL library
2. **Session Management**: Flask sessions store encrypted token cache
3. **Scope Limitation**: Only request minimal required scopes
4. **HTTPS Required**: Teams SSO only works over HTTPS
5. **Domain Validation**: Teams validates domains against validDomains list

## Additional Resources

- [Microsoft Teams SSO Documentation](https://learn.microsoft.com/en-us/microsoftteams/platform/tabs/how-to/authentication/tab-sso-overview)
- [Teams JavaScript SDK](https://learn.microsoft.com/en-us/javascript/api/overview/msteams-client)
- [On-Behalf-Of Flow](https://learn.microsoft.com/en-us/azure/active-directory/develop/v2-oauth2-on-behalf-of-flow)
- [Teams App Manifest Schema](https://learn.microsoft.com/en-us/microsoftteams/platform/resources/schema/manifest-schema)

