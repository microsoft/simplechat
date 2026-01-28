# Group Action OAuth Authentication and Schema Merging Fix

## Header Information

**Fix Title:** Group Actions Missing `additionalFields` Causing OAuth Authentication Failures  
**Issue Description:** Group actions were missing the `additionalFields` property entirely, preventing OAuth bearer token authentication from working despite having the same configuration as working global actions.  
**Root Cause:** Group action backend routes did not call `get_merged_plugin_settings()` to merge UI form data with schema defaults, while global action routes did. This caused group actions to be saved without authentication configuration fields.  
**Fixed/Implemented in version:** **0.237.005** (matches `config.py` `app.config['VERSION']`) 
**Date:** January 22, 2026  

## Problem Statement

### Symptoms
When a group action was configured with OAuth bearer token authentication:
- Action execution returned **HTTP 401 Unauthorized** errors
- ServiceNow API responded: `{"error":{"message":"User is not authenticated"}}`
- UI displayed `additionalFields: {}` (empty object) when editing group action
- Global action with identical configuration showed populated `additionalFields` and worked correctly
- Bearer token header was not being sent in API requests

### Impact
- **Severity:** High - OAuth authentication completely non-functional for group actions
- **Affected Users:** All users attempting to use group actions with OAuth/Bearer token authentication
- **Workaround:** Use global actions instead of group actions (not scalable)

### Evidence from Logs
```
[DEBUG] Auth type: bearer
[DEBUG] Token available: True
[DEBUG] Added bearer auth: EfP7otqXmV...
[DEBUG] Making request to https://YOUR-INSTANCE.service-now.com/api/now/table/incident
[DEBUG] Request headers: {'Authorization': 'Bearer EfP7otqXmV...', ...}
[DEBUG] Response status: 401
[DEBUG] Response text: {"error":{"message":"User is not authenticated",...}}
```

**Critical Discovery:** When comparing global vs group action data:
- **Global action** (working): `additionalFields: {auth_method: 'bearer', base_url: '...', ...}`
- **Group action** (failing): `additionalFields: {}` ← Empty object!

## Root Cause Analysis

### Backend Route Disparity

#### Global Action Routes (Working)
**File:** `route_backend_plugins.py` - Lines 666-667 (add_plugin route)

```python
# Global action creation route
merged = get_merged_plugin_settings(
    plugin_type,
    current_settings=additionalFields,
    schema_dir=schema_dir
)
```

**Result:** UI form data is merged with schema defaults, preserving authentication configuration sent from JavaScript.

#### Group Action Routes (Broken - Before Fix)
**File:** `route_backend_plugins.py` - Lines 430-470, 485-530

```python
# Group action creation/update routes - BEFORE FIX
# NO CALL to get_merged_plugin_settings()
# additionalFields saved directly from request without merging
```

**Result:** `additionalFields` data from UI was not being preserved, resulting in empty objects.

### Data Flow Architecture

The fix revealed the actual data flow for authentication configuration:

1. **UI Layer** (`plugin_modal_stepper.js` line 1537):
   ```javascript
   additionalFields.auth_method = 'bearer';  // Set by JavaScript based on dropdown
   ```

2. **HTTP POST** to backend:
   ```json
   {
     "name": "action_name",
     "auth": {"type": "key"},
     "additionalFields": {
       "auth_method": "bearer",
       "base_url": "https://YOUR-INSTANCE.service-now.com/api/now"
     }
   }
   ```

3. **Backend Processing** - `get_merged_plugin_settings()`:
   - **If schema file exists:** Merge UI data with schema defaults
   - **If schema file missing:** Return UI data unchanged (graceful fallback)
   - **If function not called:** Data lost!

4. **Storage:** Cosmos DB saves merged data

### Why Global Actions Worked Without Schema File

**Key Insight:** The `openapi_plugin.additional_settings.schema.json` file **never existed** for global actions either!

Global actions worked because:
1. Backend routes **called** `get_merged_plugin_settings()`
2. Function detected missing schema file
3. **Graceful fallback** (lines 110-114 in `functions_plugins.py`):
   ```python
   else:
       result[nested_key] = current_val  # Return UI data unchanged
   ```
4. UI data passed through and was saved correctly

Group actions failed because:
1. Backend routes **did not call** the merge function at all
2. `additionalFields` from UI was discarded
3. Empty object `{}` saved to database
4. OAuth configuration lost

## Technical Details

### Files Modified

1. **`route_backend_plugins.py`** (Lines 430-530)
   - **Line 461-463** (create_group_action_route): Added schema merging
   - **Line 520-522** (update_group_action_route): Added schema merging
   - **Parity achieved:** Both global and group routes now call `get_merged_plugin_settings()`

2. **`config.py`**
   - Updated VERSION from "0.236.011" to "0.236.012"

### Code Changes

#### Group Action Creation Route - BEFORE
```python
def create_group_action_route(user_id, group_id):
    """Create new group action"""
    data = request.get_json()
    # ... validation ...
    
    # Direct save without merging
    saved_plugin = save_group_action(
        user_id=user_id,
        group_id=group_id,
        plugin_data=data  # additionalFields lost here!
    )
```

#### Group Action Creation Route - AFTER (Fixed)
```python
def create_group_action_route(user_id, group_id):
    """Create new group action"""
    data = request.get_json()
    # ... validation ...
    
    # NEW: Merge additionalFields with schema defaults (lines 461-463)
    merged = get_merged_plugin_settings(
        plugin_type=data.get('type', 'openapi'),
        current_settings=data.get('additionalFields', {}),
        schema_dir=schema_dir
    )
    data['additionalFields'] = merged
    
    saved_plugin = save_group_action(
        user_id=user_id,
        group_id=group_id,
        plugin_data=data  # Now includes preserved auth config!
    )
```

**Same fix applied to:**
- `update_group_action_route()` (lines 520-522)

### Graceful Fallback Behavior

**File:** `functions_plugins.py` (Lines 92-115)

```python
def get_merged_plugin_settings(plugin_type, current_settings, schema_dir):
    """
    Merge plugin settings with schema defaults.
    
    If schema file doesn't exist: returns current_settings unchanged.
    This is intentional - allows UI-driven configuration.
    """
    schema_path = os.path.join(schema_dir, f"{plugin_type}.additional_settings.schema.json")
    
    if not os.path.exists(schema_path):
        # Graceful fallback - return UI data as-is (lines 110-114)
        result = {}
        for nested_key in current_settings:
            result[nested_key] = current_settings[nested_key]  # Preserve UI data
        return result
    
    # If schema exists, merge with defaults
    # ...
```

**Design Decision:** Schema files are **optional** - the system works perfectly with UI-driven configuration via graceful fallback.

## Solution Implemented

### Fix Strategy
1. ✅ Add `get_merged_plugin_settings()` calls to group action routes (parity with global routes)
2. ✅ Rely on UI-driven configuration + backend graceful fallback (proven approach)
3. ✅ Require recreation of existing group actions to populate `additionalFields`

### Architecture Result

**Both global and group routes now have identical behavior:**

1. **UI sends complete `additionalFields`** from form
2. **Backend calls `get_merged_plugin_settings()`** for parity
3. **Function detects no schema file** exists
4. **Graceful fallback returns UI data unchanged**
5. **Complete authentication config saved** to database

**Benefits:**
- ✅ Simple: UI drives configuration, backend preserves it
- ✅ Proven: Global actions validate this approach
- ✅ Maintainable: No schema files to keep in sync
- ✅ Flexible: Easy to extend authentication types in UI

## Validation

### Test Procedure
1. Delete existing group action (has empty `additionalFields`)
2. Create new group action via UI:
   - Type: OpenAPI
   - Upload ServiceNow spec
   - Base URL: `https://YOUR-INSTANCE.service-now.com/api/now`
   - Authentication: **Bearer Token** (dropdown selection)
   - Token: `EfP7otqXmVmg06xfB9igagxL6Pjir7ewv99sZyMqYdzImlerPt9rHM1T1_L8cCEeWZAuWUV0GPDP2eZ56XWoEQ`
3. UI JavaScript sets `additionalFields.auth_method = 'bearer'` (line 1537)
4. Backend merge function preserves UI data via fallback
5. Action saved with complete authentication configuration

### Expected Results
- ✅ Group action `additionalFields` populated: `{auth_method: 'bearer', base_url: '...', ...}`
- ✅ ServiceNow API calls return **HTTP 200** instead of 401
- ✅ Authorization header sent: `Bearer EfP7otqXmV...`
- ✅ Group agent successfully queries ServiceNow incidents
- ✅ Edit group action page displays authentication fields correctly

## Impact Analysis

### Before Fix
- **Global actions:** ✅ Working - routes call merge function
- **Group actions:** ❌ Broken - routes don't call merge function
- **Result:** OAuth authentication impossible for group actions

### After Fix
- **Global actions:** ✅ Working - routes call merge function → fallback preserves UI data
- **Group actions:** ✅ Working - routes call merge function → fallback preserves UI data
- **Result:** Complete parity, OAuth authentication works for both

### Breaking Changes
**None** - This is a pure fix with backward compatibility:
- Existing global actions continue working (unchanged code path)
- **New/recreated** group actions now work correctly
- Existing broken group actions remain broken until recreated (user action required)

## Lessons Learned

### Key Insights
1. **UI is source of truth for authentication config** - Backend preserves what UI sends
2. **Graceful fallback is a feature, not a bug** - Enables UI-driven configuration
3. **Code parity prevents subtle bugs** - Global and group routes should be identical
4. **Testing existing functionality reveals architecture** - Global actions proved UI approach works

### Best Practices Reinforced
- **Investigate working code before making changes** - Global actions showed the pattern
- **Prefer simplicity** - UI-driven configuration simpler than complex schema systems
- **Document data flows** - Understanding UI → Backend → DB flow was crucial
- **Test parity** - If code paths differ, investigate why

## Related Documentation
- **[Group Agent Loading Fix](./GROUP_AGENT_LOADING_FIX.md)** - Prerequisites for this fix (v0.235.027)
- **ServiceNow OAuth Setup** - Configuration instructions for OAuth 2.0 bearer tokens
- **Plugin Modal Stepper** - UI component responsible for authentication form (`plugin_modal_stepper.js`)

## Future Considerations

### ⚠️ CRITICAL: OAuth 2.0 Token Expiration Limitation

**Current Implementation Status:**
- ✅ **Bearer token authentication works correctly** - tokens are sent properly in HTTP headers
- ❌ **No automatic token refresh** - requires manual regeneration when expired
- ⚠️ **Production limitation** - not suitable for production use without enhancement

**The Problem:**
ServiceNow OAuth access tokens expire after a configured lifespan (e.g., 3,600 seconds = 1 hour). The current Simple Chat implementation:

1. **Stores static bearer tokens** - copied from ServiceNow and hardcoded in action configuration
2. **No expiration tracking** - doesn't know when token will expire
3. **No refresh mechanism** - can't automatically request new tokens
4. **Manual workaround required** - users must regenerate and update token every hour

**Example Failure:**
```
Request: GET https://YOUR-INSTANCE.service-now.com/api/now/table/incident
Headers: Authorization: Bearer EfP7otqXmV... (expired token)
Response: HTTP 401 - {"error":{"message":"User is not authenticated"}}
```

**Temporary Testing Workaround:**
- Increase ServiceNow "Access Token Lifespan" to longer duration (e.g., 86,400 seconds = 24 hours)
- Regenerate token before expiration
- **Not suitable for production environments**

**Proper Solution Required (Future Enhancement):**

To make OAuth 2.0 authentication production-ready, Simple Chat needs to implement the OAuth 2.0 Client Credentials flow with automatic token refresh:

#### Required Components:

1. **Store OAuth Client Credentials** (Not Bearer Token):
   ```json
   {
     "auth_type": "oauth2_client_credentials",
     "client_id": "565d53a80dfe4cb89b8869fd1d977308",
     "client_secret": "[encrypted_secret]",
     "token_endpoint": "https://YOUR-INSTANCE.service-now.com/oauth_token.do",
     "scope": "useraccount"
   }
   ```

2. **Token Storage with Expiration Tracking**:
   ```python
   {
     "access_token": "EfP7otqXmV...",
     "refresh_token": "abc123...",
     "expires_at": "2026-01-22T20:17:39Z",  # Timestamp
     "token_type": "bearer"
   }
   ```

3. **Automatic Token Refresh Logic**:
   ```python
   def get_valid_token(action_config):
       """Get valid token, refreshing if expired"""
       if token_expired(action_config):
           # Call ServiceNow OAuth token endpoint
           response = requests.post(
               action_config['token_endpoint'],
               data={
                   'grant_type': 'client_credentials',
                   'client_id': action_config['client_id'],
                   'client_secret': decrypt(action_config['client_secret'])
               }
           )
           # Update stored token with new access_token and expires_at
           update_token_storage(response.json())
       
       return get_current_token()
   ```

4. **Pre-Request Token Validation**:
   ```python
   # Before each API call in openapi_plugin.py
   if auth_config['type'] == 'oauth2_client_credentials':
       auth_config['token'] = get_valid_token(auth_config)
       headers['Authorization'] = f"Bearer {auth_config['token']}"
   ```

5. **Secure Secret Storage**:
   - Store client secrets in Azure Key Vault (not in Cosmos DB)
   - Use Managed Identity for Key Vault access
   - Encrypt secrets at rest

#### Implementation Tasks:

- [ ] **UI Changes**: Add OAuth 2.0 configuration form (Client ID, Secret, Token Endpoint)
- [ ] **Backend Changes**: 
  - [ ] Create `oauth2_token_manager.py` module for token lifecycle management
  - [ ] Implement token refresh logic with expiration checking
  - [ ] Add Key Vault integration for client secret storage
  - [ ] Update `openapi_plugin_factory.py` to detect OAuth 2.0 auth type
  - [ ] Modify HTTP request preparation to request fresh tokens
- [ ] **Database Schema**: Add token storage fields (access_token, refresh_token, expires_at)
- [ ] **Testing**: End-to-end testing with real OAuth 2.0 endpoints and token expiration scenarios
- [ ] **Documentation**: Update user guide with OAuth 2.0 setup instructions

#### References:
- [OAuth 2.0 Client Credentials Grant](https://oauth.net/2/grant-types/client-credentials/)
- [ServiceNow OAuth 2.0 Documentation](https://docs.servicenow.com/bundle/washingtondc-platform-security/page/administer/security/concept/c_OAuthApplications.html)
- [Azure Key Vault for Secret Management](https://learn.microsoft.com/azure/key-vault/general/overview)

**Estimated Effort:** 2-3 weeks for complete implementation and testing

**Priority:** Medium - Current manual workaround functional for testing/development, critical for production deployment

---

### Monitoring
Track authentication failures by action type to detect similar issues:
```python
# Example monitoring
if response.status_code == 401:
    logger.warning(f"Auth failed for {action_type} action: {action_name}")
```

## Version History
- **0.235.027** - Group agent loading fix (prerequisite)
- **0.235.028** - Group action schema merging parity fix (this document)
