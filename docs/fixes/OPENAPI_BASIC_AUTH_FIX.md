# OpenAPI Basic Authentication Fix

**Version:** 0.235.026  
**Issue:** OpenAPI actions with Basic Authentication fail with "session not authenticated" error  
**Root Cause:** Mismatch between authentication format stored by UI and format expected by OpenAPI plugin  
**Status:** ✅ Fixed

---

## Problem Description

When configuring an OpenAPI action with Basic Authentication in the Simple Chat admin interface:

1. User uploads OpenAPI spec with `securitySchemes.basicAuth` defined
2. User selects "Basic Auth" authentication type
3. User enters username and password in the configuration wizard
4. Action is saved successfully
5. **BUT**: When agent attempts to use the action, authentication fails with error:
   ```
   "I'm unable to access your ServiceNow incidents because your session 
   is not authenticated. Please log in to your ServiceNow instance or 
   check your authentication credentials."
   ```

### Symptoms
- ❌ OpenAPI actions with Basic Auth fail despite correct credentials
- ✅ Direct API calls with same credentials work correctly
- ✅ Other Simple Chat features authenticate successfully
- ❌ Error occurs even when Base URL is correctly configured

---

## Root Cause Analysis

### Authentication Storage Format (Frontend)

The Simple Chat admin UI (`plugin_modal_stepper.js`, lines 1539-1543) stores Basic Auth credentials as:

```javascript
auth.type = 'key';  // Basic auth is also 'key' type in the schema
const username = document.getElementById('plugin-auth-basic-username').value.trim();
const password = document.getElementById('plugin-auth-basic-password').value.trim();
auth.key = `${username}:${password}`;  // Store as combined string
additionalFields.auth_method = 'basic';
```

**Stored format:**
```json
{
  "auth": {
    "type": "key",
    "key": "username:password"
  },
  "additionalFields": {
    "auth_method": "basic"
  }
}
```

### Authentication Expected Format (Backend)

The OpenAPI plugin (`openapi_plugin.py`, lines 952-955) expects Basic Auth as:

```python
elif auth_type == "basic":
    import base64
    username = self.auth.get("username", "")
    password = self.auth.get("password", "")
    credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
    headers["Authorization"] = f"Basic {credentials}"
```

**Expected format:**
```json
{
  "auth": {
    "type": "basic",
    "username": "actual_username",
    "password": "actual_password"
  }
}
```

### The Mismatch

❌ **Frontend stores:** `auth.type='key'`, `auth.key='username:password'`  
❌ **Backend expects:** `auth.type='basic'`, `auth.username`, `auth.password`  
❌ **Result:** Plugin code path for Basic Auth (`elif auth_type == "basic"`) never executes  
❌ **Consequence:** No `Authorization` header added, API returns authentication error  

---

## Solution Implementation

### Fix Location
**File:** `application/single_app/semantic_kernel_plugins/openapi_plugin_factory.py`  
**Function:** `_extract_auth_config()`  
**Lines:** 129-166

### Code Changes

Added authentication format transformation logic to detect and convert Simple Chat's storage format into OpenAPI plugin's expected format:

```python
@classmethod
def _extract_auth_config(cls, config: Dict[str, Any]) -> Dict[str, Any]:
    """Extract authentication configuration from plugin config."""
    auth_config = config.get('auth', {})
    if not auth_config:
        return {}
    
    auth_type = auth_config.get('type', 'none')
    
    if auth_type == 'none':
        return {}
    
    # Check if this is basic auth stored in the 'key' field format
    # Simple Chat stores basic auth as: auth.type='key', auth.key='username:password', 
    # additionalFields.auth_method='basic'
    additional_fields = config.get('additionalFields', {})
    auth_method = additional_fields.get('auth_method', '')
    
    if auth_type == 'key' and auth_method == 'basic':
        # Extract username and password from the combined key
        key = auth_config.get('key', '')
        if ':' in key:
            username, password = key.split(':', 1)
            return {
                'type': 'basic',
                'username': username,
                'password': password
            }
        else:
            # Malformed basic auth key
            return {}
    
    # For bearer tokens stored as 'key' type
    if auth_type == 'key' and auth_method == 'bearer':
        return {
            'type': 'bearer',
            'token': auth_config.get('key', '')
        }
    
    # For OAuth2 stored as 'key' type
    if auth_type == 'key' and auth_method == 'oauth2':
        return {
            'type': 'bearer',  # OAuth2 tokens are typically bearer tokens
            'token': auth_config.get('key', '')
        }
    
    # Return the auth config as-is for other auth types
    return auth_config
```

### How It Works

1. **Detection:** Check if `auth.type == 'key'` AND `additionalFields.auth_method == 'basic'`
2. **Extraction:** Split `auth.key` on first `:` to get username and password
3. **Transformation:** Return new dict with `type='basic'`, `username`, and `password`
4. **Pass-through:** OpenAPI plugin receives correct format and adds Authorization header

### Additional Auth Method Support

The fix also handles other authentication methods stored in the same format:
- **Bearer tokens:** `auth_method='bearer'` → transforms to `{type: 'bearer', token: ...}`
- **OAuth2:** `auth_method='oauth2'` → transforms to `{type: 'bearer', token: ...}`

---

## Testing

### Before Fix
```bash
# Test action: servicenow_query_incidents
User: "Show me all incidents in ServiceNow"
Agent: "I'm unable to access your ServiceNow incidents because your 
        session is not authenticated..."
        
# HTTP request (no Authorization header sent):
GET https://dev222288.service-now.com/api/now/table/incident
# Response: 401 Unauthorized or session expired error
```

### After Fix
```bash
# Test action: servicenow_query_incidents  
User: "Show me all incidents in ServiceNow"
Agent: "Here are your ServiceNow incidents: ..."

# HTTP request (Authorization header correctly added):
GET https://dev222288.service-now.com/api/now/table/incident
Authorization: Basic <token>

# Response: 200 OK with incident data
```

### Validation Steps
1. ✅ Create OpenAPI action with Basic Auth
2. ✅ Enter username and password in admin wizard
3. ✅ Save action successfully
4. ✅ Attach action to agent
5. ✅ Test agent with prompt requiring action
6. ✅ Verify Authorization header is sent
7. ✅ Verify API returns 200 OK with data
8. ✅ Verify agent processes response correctly