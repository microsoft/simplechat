# ServiceNow OAuth 2.0 Setup for Simple Chat

**Version:** 0.236.012  
**Implemented in version:** 0.236.012

## Overview
This guide shows you how to configure OAuth 2.0 bearer token authentication for ServiceNow integration with Simple Chat using the **modern "New Inbound Integration Experience"** method. This is more secure than Basic Auth and recommended for production environments.

> **Note:** This guide uses the current ServiceNow OAuth configuration method. The deprecated "Create an OAuth API endpoint for external clients" method is no longer recommended.

## Prerequisites
- ServiceNow instance (Developer or Production)
- Admin access to ServiceNow
- **ServiceNow integration user** with appropriate roles (e.g., `itil`, `incident_manager`)
  - **Best Practice**: Create a dedicated user (e.g., `simplechat_integration`) instead of using a personal account
  - This user's permissions determine what the OAuth token can access
- Existing Simple Chat ServiceNow action (or create new one)

---

## Part 1: Configure OAuth in ServiceNow

### Step 1: Create ServiceNow Integration User (Recommended)

Before creating the OAuth application, create a dedicated integration user:

1. **Navigate to User Administration:**
   - In ServiceNow, search for: **"Users"** in the left navigation filter
   - Click: **System Security > Users**

2. **Create New User:**
   - Click **"New"**
   - Fill in the form:
     ```
     User ID: simplechat_integration
     First name: Simple Chat
     Last name: Integration
     Email: your-email@example.com
     Password: [Set a strong password - save this!]
     ```

3. **Assign Roles:**
   - Click on the **Roles** tab
   - Add appropriate roles based on your Simple Chat use case:
     - `itil` - Read access to ITIL tables (incidents, problems, changes)
     - `incident_manager` - Create and update incidents
     - `knowledge` - Read knowledge base articles
   - **Security Best Practice**: Grant **only the minimum roles** needed for Simple Chat operations

4. **Activate and Save:**
   - Check the **"Active"** checkbox
   - Click **"Submit"**

5. **Save These Credentials (you'll need them in Step 3):**
   ```
   ServiceNow Integration User
   Username: simplechat_integration
   Password: [the password you set]
   ```

> **Why Create a Dedicated User?**
> - ✅ **Security**: Limit blast radius if credentials are compromised
> - ✅ **Audit Trail**: Clear visibility in ServiceNow logs (shows "simplechat_integration" performed actions)
> - ✅ **Permission Control**: Grant only the specific roles needed, not your full admin rights
> - ✅ **Lifecycle Management**: Can deactivate or rotate credentials without affecting personal accounts

---

### Step 2: Create OAuth Application

1. **Log in to your ServiceNow instance** as an admin
   - URL: `https://devnnnnnn.service-now.com`

2. **Navigate to OAuth Application Registry:**
2. **Navigate to OAuth Application Registry:**
   ```
   System OAuth > Application Registry
   ```
   Or search for "OAuth" in the navigation filter

3. **Create New OAuth Integration:**
   - Click **New**
   - Select **"New Inbound Integration Experience"** (recommended for external clients)
   - ⚠️ **Do NOT use** the deprecated "Create an OAuth API endpoint for external clients"

4. **Select OAuth Grant Type:**
   
   ServiceNow will present you with several OAuth grant type options:
   
   **For this POC, select: "OAuth - Resource owner password credential grant"**
   
   > **📋 Why This Grant Type for POC:**
   > - ✅ **Trusted application scenario**: Simple Chat is a trusted first-party application on your Azure infrastructure
   > - ✅ **User context preserved**: Actions execute with the **integration user's permissions** and audit trail
   >   - Token request requires: **OAuth app credentials** (Client ID/Secret) + **ServiceNow user credentials** (Username/Password)
   >   - ServiceNow issues token **on behalf of that specific user**
   >   - All API calls execute with that user's roles, ACLs, and permissions
   >   - Audit logs show the integration user's name, not just "OAuth app"
   > - ✅ **Simple token management**: Easy to obtain and refresh tokens programmatically
   > - ✅ **Development/testing friendly**: Works well for POC without complex OAuth flows
   > - ✅ **Server-to-server integration**: Simple Chat backend directly requests tokens using credentials
   
   > **⚠️ IMPORTANT - Review Grant Type for Production:**
   > 
   > The OAuth grant type should be **revisited based on your customer's security requirements** and deployment scenario:
   > 
   > | Grant Type | Best For | Use When |
   > |------------|----------|----------|
   > | **Resource Owner Password** | Trusted apps, POC/Dev | App is first-party, trusted infrastructure, need user context |
   > | **Client Credentials** | Machine-to-machine | No user context needed, service account only |
   > | **Authorization Code** | Third-party apps | Interactive user consent required, multi-tenant scenarios |
   > | **JWT Bearer** | Advanced scenarios | Token exchange, federated identity, microservices |
   > 
   > **Production Considerations:**
   > - If customer requires **no password storage**, use Authorization Code grant with PKCE
   > - If customer requires **service account only**, use Client Credentials grant
   > - If customer has **strict OAuth compliance**, avoid Resource Owner Password grant (considered legacy by some standards)
   > - If integrating with **external identity providers**, use JWT Bearer or Authorization Code grant
   > 
   > Always align the grant type choice with your customer's security policies and compliance requirements.

5. **Configure the Integration Form:**

   ServiceNow presents a "New record" form with several sections. Configure as follows:
   
   **Details Section:**
   ```
   Name: Simple Chat Integration
   Provider name: Azure app service (auto-filled)
   Client ID: (auto-generated - COPY THIS!)
   Client secret: (auto-generated - COPY THIS IMMEDIATELY!)
   Comments: OAuth integration for Simple Chat AI assistant
   Active: ☑ Checked
   ```
   
   **Auth Scope Section:**
   ```
   Auth scope: useraccount (default)
   Limit authorization to following APIs: (leave empty for POC)
   ```
   > ⚠️ The "useraccount" scope grants access to all resources available to the signed-in user. This is acceptable for POC with a dedicated integration user account. For production, consider creating custom scopes to limit access to only required APIs.
   
   **Advanced Options (optional):**
   ```
   Enforce token restriction: ☐ Unchecked (for POC)
   Token Format: Opaque (default)
   Access token lifespan (seconds): 3600 (1 hour - recommended for POC)
   Refresh token lifespan (seconds): 86400 (24 hours - recommended for POC)
   ```
   > **Note:** ServiceNow defaults to 1800 seconds (30 min) for access tokens, which is too short for testing. Change to longer based on your needs or the dev/testing duration.

6. **⚠️ CRITICAL - Copy Credentials BEFORE Saving:**
   
   **Before clicking "Save", you MUST copy these values:**
   
   1. **Client ID:** Visible in plain text (e.g., `565d53a80dfe4cb89b8869fd1d977308`)
      - Select and copy the entire value
   
   2. **Client Secret:** Hidden behind dots
      - Click the 👁️ (eye icon) to reveal, OR
      - Click the 📋 (copy icon) to copy directly
      - **This may only be shown once - copy it now!**
   
   **Save these values securely** - paste them into a text file or password manager immediately.
   
   Example format to save:
   ```
   ServiceNow OAuth Credentials
   Instance: https://devnnnnnn.service-now.com
   Client ID: 565d53a...
   Client Secret: [paste the revealed secret here]
   Token Endpoint: https://devnnnnnn.service-now.com/oauth_token.do
   Username: <unique name>
   ```

7. **Click "Save"**

8. **Note the token endpoint:**
   - Token endpoint: `https://devnnnnnn.service-now.com/oauth_token.do`

---

### Step 3: Obtain Access Token

You have two options to get an access token.

> **Important:** The token request requires **BOTH**:
> - **OAuth App Credentials**: `client_id` and `client_secret` (from Step 1)
> - **ServiceNow User Credentials**: `username` and `password` (integration user you created)
> 
> The resulting token will execute API calls **as that integration user** with their specific roles and permissions.

#### **Option A: Using REST Client (Postman/Curl)**

**Request:**
```bash
curl -X POST https://devnnnnnn.service-now.com/oauth_token.do \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=password" \
  -d "client_id=YOUR_CLIENT_ID" \              # OAuth app Client ID
  -d "client_secret=YOUR_CLIENT_SECRET" \      # OAuth app Client Secret
  -d "username=YOUR_USERNAME" \                # ServiceNow integration user
  -d "password=YOUR_PASSWORD"                  # Integration user's password
```

**Response:**
```json
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "refresh_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "scope": "useraccount",
  "token_type": "Bearer",
  "expires_in": 31536000
}
```

#### **Option B: Using Python Script**

Create `get_servicenow_token.py`:
```python
#!/usr/bin/env python3
"""
Get ServiceNow OAuth access token for Simple Chat integration.

Requires BOTH:
- OAuth App credentials (Client ID/Secret from ServiceNow OAuth registry)
- ServiceNow integration user credentials (Username/Password)

The token will execute API calls as the integration user with their permissions.
"""

import requests
import json

# ServiceNow OAuth App credentials (from Step 1 - OAuth registry)
SERVICENOW_INSTANCE = "https://devnnnnnn.service-now.com"
CLIENT_ID = "YOUR_CLIENT_ID"          # From OAuth Application Registry
CLIENT_SECRET = "YOUR_CLIENT_SECRET"  # From OAuth Application Registry

# ServiceNow integration user credentials (dedicated user with specific roles)
USERNAME = "YOUR_USERNAME"            # e.g., simplechat_integration
PASSWORD = "YOUR_PASSWORD"            # Integration user's password

def get_access_token():
    """Get OAuth access token from ServiceNow."""
    url = f"{SERVICENOW_INSTANCE}/oauth_token.do"
    
    data = {
        'grant_type': 'password',
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'username': USERNAME,
        'password': PASSWORD
    }
    
    response = requests.post(url, data=data)
    
    if response.status_code == 200:
        token_data = response.json()
        print("✅ Access Token obtained successfully!")
        print(f"\nAccess Token: {token_data['access_token']}")
        print(f"Expires in: {token_data['expires_in']} seconds")
        print(f"Token Type: {token_data['token_type']}")
        
        # Save to file
        with open('servicenow_token.json', 'w') as f:
            json.dump(token_data, f, indent=2)
        print("\n📁 Token saved to servicenow_token.json")
        
        return token_data['access_token']
    else:
        print(f"❌ Failed to get token: {response.status_code}")
        print(response.text)
        return None

if __name__ == "__main__":
    get_access_token()
```

Run the script:
```bash
python get_servicenow_token.py
```

---

## Part 2: Configure Action in Simple Chat

### Step 1: Navigate to Actions Configuration

1. **Navigate to Actions page:**
   - Go to **Settings** > **Actions** (Global) or **Group Settings** > **Actions** (Group-specific)

2. **Edit your ServiceNow action** or click **"Create New Action"**

### Step 2: Upload OpenAPI Specification

1. **Action Details:**
   ```
   Name: ServiceNow Query Incidents (or your preferred name)
   Display Name: ServiceNow - Query Incident
   Description: Query ServiceNow incidents with filters
   ```

2. **OpenAPI Specification:**
   - Upload your `servicenow_incident_api.yaml` file
   - Or paste the OpenAPI spec content directly
   
3. **Base URL:**
   ```
   https://devnnnnnn.service-now.com/api/now
   ```
   *(Replace devnnnnnn with your actual ServiceNow instance)*

### Step 3: Configure Bearer Token Authentication

In the **Authentication Configuration** section:

1. **Select Authentication Type:**
   - From the **"Type"** dropdown, select: **Bearer Token**

2. **Enter Token:**
   - Paste your access token in the **"Token"** field
   ```
   YOUR_ACCESS_TOKEN_FROM_PART_1_STEP_2
   ```
   *(Use the actual token obtained from Part 1, Step 2)*

3. **Save the Action**

**That's it!** Simple Chat will automatically:
- Add `Authorization: Bearer YOUR_TOKEN` header to all requests
- Handle the token properly for ServiceNow API authentication

> **Production Considerations:**
> 
> For production deployments, consider the following:
> 
> 1. **Secure Token Storage**: Store the OAuth token in Azure Key Vault rather than directly in the action configuration
>    - Enables centralized secret management and rotation
>    - Provides audit logging for secret access
>    - Allows token updates without modifying Simple Chat configuration
> 
> 2. **Token Expiration Management**: OAuth tokens have limited lifespans (typically 1-8 hours)
>    - **Monitor token expiration**: Set up alerts before tokens expire
>    - **Implement token refresh**: Use the refresh token to obtain new access tokens automatically
>    - **Automated renewal**: Consider creating an Azure Function or scheduled task to refresh tokens periodically
>    - See the "Token Refresh Strategy" section below for implementation options
> 
> 3. **Graceful Failure Handling**: Implement monitoring to detect authentication failures due to expired tokens

---

## Part 3: Testing

### Test with Simple Chat Agent

1. **Open Simple Chat** and select your ServiceNow agent
2. **Test query:**
   ```
   Show me recent incidents
   ```

3. **Check logs** for successful authentication:
   ```
   Added bearer auth: eyJ0eXAi...
   Authorization: Bearer eyJ0eXAi...
   ```

### Test with Curl

```bash
curl -X GET \
  "https://devnnnnnn.service-now.com/api/now/table/incident?sysparm_limit=5" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Accept: application/json"
```

---

## Token Refresh Strategy

OAuth tokens expire. Here are your options:

### Option 1: Manual Refresh (Simple)
- Set calendar reminder before token expires
- Run `get_servicenow_token.py` script
- Update Key Vault secret
- Simple Chat will use new token automatically

### Option 2: Automatic Refresh (Advanced)
Create a scheduled task/Azure Function to refresh tokens:

```python
# refresh_servicenow_token.py
import requests
from azure.keyvault.secrets import SecretClient
from azure.identity import DefaultAzureCredential

def refresh_token():
    # Get refresh token from Key Vault
    credential = DefaultAzureCredential()
    client = SecretClient(vault_url="https://your-vault.vault.azure.net", credential=credential)
    refresh_token = client.get_secret("servicenow-refresh-token").value
    
    # Request new access token
    response = requests.post(
        "https://devnnnnnn.service-now.com/oauth_token.do",
        data={
            'grant_type': 'refresh_token',
            'refresh_token': refresh_token,
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET
        }
    )
    
    if response.status_code == 200:
        new_token = response.json()['access_token']
        
        # Update Key Vault
        client.set_secret("servicenow-oauth-token", new_token)
        print("✅ Token refreshed successfully!")
    else:
        print(f"❌ Refresh failed: {response.text}")

if __name__ == "__main__":
    refresh_token()
```

Schedule with Azure Function (Timer Trigger):
```
Trigger: Every 50 minutes (before 1-hour expiration)
```

### Option 3: Long-Lived Tokens
Configure longer token lifespans in ServiceNow:
```
Access Token Lifespan: 28800 (8 hours)
Refresh Token Lifespan: 604800 (7 days)
```

---

## Security Best Practices

### ✅ DO:
- Store tokens in Azure Key Vault
- Use HTTPS for all requests
- Set appropriate token expiration times
- Rotate tokens regularly
- Use refresh tokens to avoid storing passwords
- Monitor token usage in ServiceNow

### ❌ DON'T:
- Hardcode tokens in code
- Share tokens between environments
- Use overly long token lifespans
- Commit tokens to source control
- Use the same credentials for dev and prod

---

## Comparison: Basic Auth vs OAuth Bearer

| Aspect | Basic Auth | OAuth Bearer Token |
|--------|------------|-------------------|
| **Security** | Lower (credentials in every request) | Higher (token-based, expirable) |
| **Setup** | Simple | Moderate complexity |
| **Token Expiration** | None | Configurable (1-8 hours) |
| **Rotation** | Manual password change | Automatic with refresh tokens |
| **Audit Trail** | Username-based | Token-based (better tracking) |
| **Revocation** | Change password (affects all) | Revoke individual tokens |
| **Best For** | Development/Testing | Production environments |

---

## Troubleshooting

### Error: "invalid_client"
- Verify Client ID and Client Secret are correct
- Check OAuth application is active in ServiceNow

### Error: "invalid_grant"
- Check username and password are correct
- Verify user has necessary roles in ServiceNow

### Error: 401 Unauthorized with Bearer Token
- Token may have expired - refresh it
- Verify token is being sent correctly: `Authorization: Bearer TOKEN`
- Check token wasn't truncated when copying

---

## Next Steps

1. **Complete OAuth setup** in ServiceNow
2. **Get initial access token** using script or Postman
3. **Store token in Key Vault** (recommended)
4. **Update action configuration** in Simple Chat
5. **Test with agent** to verify authentication works
6. **Set up token refresh** strategy (manual or automated)

## Related Documentation
- [ServiceNow OAuth Documentation](https://docs.servicenow.com/bundle/xanadu-platform-security/page/administer/security/concept/c_OAuthApplications.html)
- [Simple Chat OpenAPI Basic Auth Fix](./explanation/fixes/OPENAPI_BASIC_AUTH_FIX.md)
- [ServiceNow Integration Guide](./SERVICENOW_INTEGRATION.md)
