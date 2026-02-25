# Microsoft Teams App Configuration

This guide covers how to configure SimpleChat as a Microsoft Teams application with Single Sign-On (SSO) support.

## Overview

SimpleChat supports Teams SSO using the On-Behalf-Of (OBO) flow. When embedded in Teams, users are automatically authenticated without needing to log in separately.

## Prerequisites

- Azure AD App Registration (same one used for web app authentication)
- Access to Azure Portal with appropriate permissions
- Teams Admin access to upload custom apps

## Azure AD App Registration Configuration

### 1. Expose an API

Configure your app to expose an API for Teams SSO:

1. Navigate to **Azure Portal** → **Azure Active Directory** → **App registrations**
2. Select your application
3. Go to **Expose an API**

#### Set Application ID URI

1. Click **Set** next to "Application ID URI"
2. Set it to: `api://{your-app-domain}/{CLIENT_ID}`
   - Example: `api://myapp.azurewebsites.net/12345678-1234-1234-1234-123456789abc`
   - For Teams: `api://teams.myapp.com/12345678-1234-1234-1234-123456789abc`
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

### 3. API Permissions

Ensure your app has the necessary Microsoft Graph permissions:

1. Go to **API permissions**
2. Verify/Add these **Delegated permissions** for Microsoft Graph:
   - `User.Read` (Sign in and read user profile)
   - `User.ReadBasic.All` (Read all users' basic profiles)
   - `People.Read.All` (Read all users' relevant people lists)
   - `Group.Read.All` (Read all groups)

3. Click **Grant admin consent for {your tenant}** if you have admin rights

### 4. Authentication Configuration

1. Go to **Authentication**
2. Verify your redirect URIs include:
   - Web: `https://{your-app-domain}/getAToken`
   - Web: `https://{your-app-domain}/login`

3. Under **Implicit grant and hybrid flows**, ensure:
   - ✅ Access tokens (used for implicit flows)
   - ✅ ID tokens (used for implicit and hybrid flows)

4. Under **Supported account types**, ensure it's set to:
   - **Accounts in this organizational directory only** (Single tenant)
   - Or **Accounts in any organizational directory** (Multi-tenant)

## Environment Variables

Ensure these environment variables are set:

```bash
# Required
CLIENT_ID=your-azure-ad-client-id
TENANT_ID=your-azure-ad-tenant-id
MICROSOFT_PROVIDER_AUTHENTICATION_SECRET=your-client-secret

# Teams SSO Configuration
TEAMS_APP_ID=your-azure-ad-client-id  # Usually same as CLIENT_ID
ENABLE_TEAMS_SSO=true
```

## Teams App Manifest Configuration

Create or update your Teams app manifest (`manifest.json`):

```json
{
  "$schema": "https://developer.microsoft.com/json-schemas/teams/v1.16/MicrosoftTeams.schema.json",
  "manifestVersion": "1.16",
  "version": "1.0.0",
  "id": "{TEAMS_APP_ID}",
  "packageName": "com.yourcompany.simplechat",
  "developer": {
    "name": "Your Company Name",
    "websiteUrl": "https://your-website.com",
    "privacyUrl": "https://your-website.com/privacy",
    "termsOfUseUrl": "https://your-website.com/terms"
  },
  "icons": {
    "color": "color.png",
    "outline": "outline.png"
  },
  "name": {
    "short": "SimpleChat",
    "full": "SimpleChat AI Assistant"
  },
  "description": {
    "short": "AI-powered chat assistant",
    "full": "SimpleChat brings AI-powered conversations to Microsoft Teams"
  },
  "accentColor": "#6264A7",
  "configurableTabs": [
    {
      "configurationUrl": "https://{your-app-domain}/teams/config",
      "canUpdateConfiguration": true,
      "scopes": ["team", "groupchat"]
    }
  ],
  "staticTabs": [
    {
      "entityId": "simplechat-tab",
      "name": "SimpleChat",
      "contentUrl": "https://{your-app-domain}/login?teams=true",
      "websiteUrl": "https://{your-app-domain}",
      "scopes": ["personal"]
    }
  ],
  "permissions": [
    "identity",
    "messageTeamMembers"
  ],
  "validDomains": [
    "{your-app-domain}",
    "login.microsoftonline.com",
    "login.microsoftonline.us",
    "login.microsoftonline.com"
  ],
  "webApplicationInfo": {
    "id": "{CLIENT_ID}",
    "resource": "api://{your-app-domain}/{CLIENT_ID}"
  }
}
```

### Key Manifest Fields for SSO

- **webApplicationInfo.id**: Your Azure AD Client ID
- **webApplicationInfo.resource**: The Application ID URI from Azure AD (must match exactly)
- **validDomains**: Include your app domain and Azure AD login domains
- **staticTabs.contentUrl**: Point to `/login?teams=true` for automatic Teams detection

## Content Security Policy

Ensure your `config.py` includes Teams domains in the Content Security Policy:

```python
'Content-Security-Policy': (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https: blob:; "
    "font-src 'self'; "
    "connect-src 'self' https: wss: ws:; "
    "media-src 'self' blob:; "
    "object-src 'none'; "
    "frame-ancestors 'self' https://teams.microsoft.com https://*.teams.microsoft.com https://*.cloud.microsoft; "
    "base-uri 'self';"
)
```

## Testing Teams SSO

### 1. Upload to Teams

1. Package your Teams app:
   - Create a `.zip` file containing:
     - `manifest.json`
     - `color.png` (192x192)
     - `outline.png` (32x32 transparent)

2. Upload to Teams:
   - Go to Teams → Apps → **Manage your apps**
   - Click **Upload an app** → **Upload a custom app**
   - Select your `.zip` file

### 2. Test Authentication Flow

1. Open your app in Teams
2. The app should:
   - Detect it's running in Teams
   - Show "Teams detected" status
   - Automatically obtain SSO token
   - Exchange token for access token
   - Redirect to `/chats` on success

3. Check browser console (F12) for logs:
   ```
   Login page loaded, starting authentication...
   Teams SDK initialized
   Teams context detected: {contextObject}
   Attempting Teams SSO authentication...
   Teams token acquired, exchanging for access token...
   Teams authentication successful
   ```

### 3. Troubleshooting

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
- Verify Teams manifest `contentUrl` includes `?teams=true`

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

