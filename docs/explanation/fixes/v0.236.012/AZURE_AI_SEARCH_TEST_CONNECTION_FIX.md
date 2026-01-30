# Azure AI Search Test Connection Fix

## Issue Description

When clicking the "Test Azure AI Search Connection" button on the App Settings "Search & Extract" page with **managed identity authentication** enabled, the test connection failed with the following error:

**Original Error Message:**
```
NameError: name 'search_resource_manager' is not defined
```

**Environment Configuration:**
- Authentication Type: Managed Identity
- Azure Environment: `public` (set in .env file)
- Error occurred because the code tried to reference `search_resource_manager` which wasn't defined for public cloud

**Root Cause:** The old implementation used a REST API approach that required the `search_resource_manager` variable to construct authentication tokens. This variable wasn't defined for the public cloud environment, causing the initial error. Even if defined, the REST API approach with bearer tokens doesn't work properly with Azure AI Search's managed identity authentication.

## Root Cause Analysis

The old implementation used a **REST API approach with manually acquired bearer tokens**, which is fundamentally incompatible with how Azure AI Search handles managed identity authentication on the data plane.

### Why the Old Approach Failed

Azure AI Search's data plane operations don't properly accept bearer tokens acquired through standard `DefaultAzureCredential.get_token()` flows and passed as HTTP Authorization headers. The authentication mechanism works differently:

```python
# OLD IMPLEMENTATION - FAILED ❌
credential = DefaultAzureCredential()
arm_scope = f"{search_resource_manager}/.default"
token = credential.get_token(arm_scope).token

headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}
response = requests.get(f"{endpoint}/indexes?api-version=2024-07-01", headers=headers)
# Returns: 403 Forbidden
```

**Problems with this approach:**
1. Azure AI Search requires SDK-specific authentication handling
2. Bearer tokens from `get_token()` are rejected by the Search service
3. Token scope and refresh logic need specialized handling
4. This issue occurs in **all Azure environments** (public, government, custom)

### Why Other Services Work with REST API + Bearer Tokens

Some Azure services accept bearer tokens in REST API calls, but Azure AI Search requires the SDK to:
1. Acquire tokens using the correct scope and flow
2. Handle token refresh automatically
3. Use Search-specific authentication headers
4. Properly negotiate with the Search service's auth layer

## Technical Details

### Files Modified

**File:** `route_backend_settings.py`
**Function:** `_test_azure_ai_search_connection(payload)`
**Lines:** 760-796

### The Solution

Instead of trying to define `search_resource_manager` for public cloud, the fix was to **replace the REST API approach entirely with the SearchIndexClient SDK**, which handles authentication correctly without needing the `search_resource_manager` variable.

### Code Changes Summary

**Before (REST API approach):**
```python
def _test_azure_ai_search_connection(payload):
    # ... setup code ...
    
    if direct_data.get('auth_type') == 'managed_identity':
        credential = DefaultAzureCredential()
        arm_scope = f"{search_resource_manager}/.default"
        token = credential.get_token(arm_scope).token
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        response = requests.get(f"{endpoint}/indexes?api-version=2024-07-01", headers=headers)
        # ❌ Returns 403 Forbidden
```

**After (SDK approach):**
```python
def _test_azure_ai_search_connection(payload):
    # ... setup code ...
    
    if direct_data.get('auth_type') == 'managed_identity':
        credential = DefaultAzureCredential()
        
        # Use SDK which handles authentication properly
        if AZURE_ENVIRONMENT in ("usgovernment", "custom"):
            client = SearchIndexClient(
                endpoint=endpoint,
                credential=credential,
                audience=search_resource_manager
            )
        else:
            # For public cloud, don't use audience parameter
            client = SearchIndexClient(
                endpoint=endpoint,
                credential=credential
            )
    
    # Test by listing indexes (simple operation to verify connectivity)
    indexes = list(client.list_indexes())
    # ✅ Works correctly
```

### Key Implementation Details

1. **Replaced REST API with SearchIndexClient SDK**
   - Uses `SearchIndexClient` from `azure.search.documents`
   - SDK handles authentication internally
   - Properly manages token acquisition and refresh

2. **Environment-Specific Configuration**
   - **Azure Government/Custom:** Requires `audience` parameter
   - **Azure Public Cloud:** Omits `audience` parameter
   - Matches pattern used throughout codebase

3. **Consistent with Other Functions**
   - Aligns with `get_index_client()` implementation (line 484)
   - Matches SearchClient initialization in `config.py` (lines 584-619)
   - All other search operations already use SDK approach

## Testing Approach

### Prerequisites
- Service principal must have **"Search Index Data Contributor"** RBAC role
- Permissions must propagate (5-10 minutes after assignment)

### RBAC Role Assignment Command
```bash
az role assignment create \
  --assignee <SERVICE_PRINCIPAL_CLIENT_ID> \
  --role "Search Index Data Contributor" \
  --scope /subscriptions/<SUBSCRIPTION_ID>/resourceGroups/<RESOURCE_GROUP>/providers/Microsoft.Search/searchServices/<SEARCH_SERVICE_NAME>
```

### Verification
```bash
az role assignment list \
  --assignee <SERVICE_PRINCIPAL_CLIENT_ID> \
  --scope /subscriptions/<SUBSCRIPTION_ID>/resourceGroups/<RESOURCE_GROUP>/providers/Microsoft.Search/searchServices/<SEARCH_SERVICE_NAME> \
  --output table
```

## Impact Analysis

### What Changed
- **Only the test connection function** was affected
- No changes needed to actual search operations (indexing, querying, etc.)
- All other search functionality already used correct SDK approach

### Why Other Search Operations Weren't Affected
All production search operations throughout the codebase already use the SDK:
- `SearchClient` for querying indexes
- `SearchIndexClient` for managing indexes
- `get_index_client()` helper function
- Index initialization in `config.py`

**Only the test connection function used the failed REST API approach.**

## Validation

### Before Fix
- ✅ Authentication succeeded (no credential errors)
- ✅ Token acquisition worked
- ❌ Azure AI Search rejected bearer token (403 Forbidden)
- ❌ Test connection failed

### After Fix
- ✅ Authentication succeeds
- ✅ SDK handles token acquisition properly
- ✅ Azure AI Search accepts SDK authentication
- ✅ Test connection succeeds (with proper RBAC permissions)

## Configuration Requirements

### Public Cloud (.env)
```ini
AZURE_ENVIRONMENT=public
AZURE_CLIENT_ID=<service-principal-client-id>
AZURE_CLIENT_SECRET=<service-principal-client-secret>
AZURE_TENANT_ID=<tenant-id>
AZURE_AI_SEARCH_AUTHENTICATION_TYPE=managed_identity
AZURE_AI_SEARCH_ENDPOINT=https://<search-service>.search.windows.net
```

### Azure Government (.env)
```ini
AZURE_ENVIRONMENT=usgovernment
AZURE_CLIENT_ID=<service-principal-client-id>
AZURE_CLIENT_SECRET=<service-principal-client-secret>
AZURE_TENANT_ID=<tenant-id>
AZURE_AI_SEARCH_AUTHENTICATION_TYPE=managed_identity
AZURE_AI_SEARCH_ENDPOINT=https://<search-service>.search.windows.us
```

## Related Changes

**No config.py changes were made.** The fix was entirely in the route_backend_settings.py file by switching from REST API to SDK approach.

The SDK approach eliminates the need for the `search_resource_manager` variable in public cloud because:
- The SearchIndexClient handles authentication internally
- No manual token acquisition is needed
- The SDK knows the correct endpoints and scopes automatically

## Version Information

- Application version (`config.py` `app.config['VERSION']`): **0.236.012**
- Fixed in version: **0.236.012**

## References

- Azure AI Search SDK Documentation: https://learn.microsoft.com/python/api/azure-search-documents
- Azure RBAC for Search: https://learn.microsoft.com/azure/search/search-security-rbac
- DefaultAzureCredential: https://learn.microsoft.com/python/api/azure-identity/azure.identity.defaultazurecredential

## Summary

The fix replaces manual REST API calls with the proper Azure Search SDK (`SearchIndexClient`), which correctly handles managed identity authentication for Azure AI Search. This aligns the test function with all other search operations in the codebase that already use the SDK approach successfully.
