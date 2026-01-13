# Video Indexer API Key Token Generation Fix

## Issue Description
When using API key authentication with Azure Video Indexer, video uploads were failing with 401 Unauthorized errors. The system was attempting to use the raw API key directly in API calls instead of generating an access token first.

**Fixed in version:** 0.229.065

## Error Symptoms
```
[VIDEO] API key authentication completed
[VIDEO] UPLOAD ERROR: 401 Client Error: Unauthorized for url: https://api.videoindexer.ai/eastus/Accounts/.../Videos?name=...
```

## Root Cause
The initial implementation of API key authentication (`get_video_indexer_api_key_token()`) was simply returning the API key directly. However, the Video Indexer API requires a two-step authentication process:

1. **Step 1**: Use API key to generate an access token via the auth endpoint
2. **Step 2**: Use the access token for all subsequent Video Indexer API operations

The code was skipping Step 1 and trying to use the API key directly, which caused authentication failures.

## Technical Details

### Before Fix
```python
def get_video_indexer_api_key_token(settings, video_id=None):
    """Returns API key directly (incorrect)"""
    api_key = settings.get("video_indexer_api_key", "")
    return api_key  # Wrong - this won't work with Video Indexer API
```

### After Fix
```python
def get_video_indexer_api_key_token(settings, video_id=None):
    """Generate access token using API key"""
    api_key = settings.get("video_indexer_api_key", "")
    account_id = settings.get("video_indexer_account_id", "")
    location = settings.get("video_indexer_location", "trial")
    
    # Generate access token via auth endpoint
    api_url = "https://api.videoindexer.ai"
    auth_url = f"{api_url}/auth/{location}/Accounts/{account_id}/AccessToken"
    
    headers = {"Ocp-Apim-Subscription-Key": api_key}
    params = {"allowEdit": "true"}
    
    if video_id:
        params["videoId"] = video_id
    
    response = requests.get(auth_url, headers=headers, params=params)
    response.raise_for_status()
    
    access_token = response.text.strip('"')
    return access_token
```

## Files Modified

### 1. functions_authentication.py
- **Function**: `get_video_indexer_api_key_token()`
- **Changes**: 
  - Added API key to access token conversion logic
  - Calls Video Indexer auth endpoint: `/auth/{location}/Accounts/{account_id}/AccessToken`
  - Uses `Ocp-Apim-Subscription-Key` header for auth endpoint call
  - Returns generated access token instead of raw API key
  - Added error handling with detailed debug logging

### 2. functions_documents.py
- **Changes**: Simplified authentication handling since both methods now return access tokens
- **Video Upload**: Both auth methods now use `accessToken` query parameter
- **Video Polling**: Both auth methods now use `accessToken` query parameter  
- **Video Deletion**: Both auth methods now use `accessToken` query parameter

#### Before Fix
```python
if auth_type == "key":
    headers = {'Ocp-Apim-Subscription-Key': token}  # Wrong
    params = {"name": original_filename}
else:
    headers = {}
    params = {"accessToken": token, "name": original_filename}
```

#### After Fix
```python
# Both methods now return access tokens
headers = {}
params = {"accessToken": token, "name": original_filename}
```

## Authentication Flow

### API Key Authentication Flow
1. User configures API key in admin settings
2. System calls `get_video_indexer_api_key_token()`
3. Function makes GET request to: `https://api.videoindexer.ai/auth/{location}/Accounts/{account_id}/AccessToken`
4. Request includes `Ocp-Apim-Subscription-Key: {api_key}` header
5. Video Indexer returns access token
6. Access token is used for all subsequent API calls via `accessToken` query parameter

### Managed Identity Authentication Flow  
1. User configures managed identity in admin settings
2. System calls `get_video_indexer_managed_identity_token()`
3. Function acquires ARM token using DefaultAzureCredential
4. Function makes POST to ARM generateAccessToken endpoint
5. ARM returns access token
6. Access token is used for all subsequent API calls via `accessToken` query parameter

## Video Indexer API Reference

### Token Generation Endpoint
```
GET https://api.videoindexer.ai/auth/{location}/Accounts/{account_id}/AccessToken
Headers:
  Ocp-Apim-Subscription-Key: {your_api_key}
Query Parameters:
  allowEdit: true
  videoId: {optional_video_id}
```

### API Operations (Upload, Poll, Delete)
```
All operations use the generated access token:
  ?accessToken={generated_token}
```

## Testing

### Functional Test Updates
Updated `test_video_indexer_dual_authentication_support.py` to verify:
- ✅ API key authentication generates access tokens via auth endpoint
- ✅ Access tokens are used consistently across all operations
- ✅ Both authentication methods use the same API call patterns
- ✅ Default settings maintain backward compatibility

### Test Patterns Verified
```python
# Verify token generation patterns
required_api_key_patterns = [
    '/auth/',
    '/AccessToken',
    'Ocp-Apim-Subscription-Key',
    'requests.get',
    'allowEdit'
]

# Verify consistent access token usage
required_patterns = [
    'auth_type = settings.get("video_indexer_authentication_type"',
    '"accessToken": token',
    'get_video_indexer_account_token'
]
```

## Benefits of Fix
- **Authentication Works Correctly**: API key method now properly authenticates with Video Indexer
- **Consistent Pattern**: Both auth methods return access tokens and use identical API call patterns
- **Proper Token Scope**: Can generate video-specific or account-level tokens as needed
- **Better Error Handling**: Detailed logging for token generation failures
- **Cleaner Code**: Simplified video processing logic since both methods work the same way

## Configuration Requirements

### API Key Method Settings
```python
video_indexer_authentication_type: "key"
video_indexer_api_key: "your-api-key"
video_indexer_account_id: "your-account-id"  
video_indexer_location: "trial" or your region
```

### Required Permissions
- API key must have permissions to generate access tokens
- Access tokens generated with `allowEdit=true` for upload/delete operations

## Known Limitations
- Access tokens have expiration times (typically 1 hour)
- Token generation requires additional API call before operations
- API key must be manually rotated (not handled automatically)

## Debug Logging
Enhanced logging helps troubleshoot token generation:
```
[VIDEO INDEXER AUTH] Using API key authentication
[VIDEO INDEXER AUTH] Requesting access token for account: {id}, location: {loc}
[VIDEO INDEXER AUTH] Calling auth endpoint: {url}
[VIDEO INDEXER AUTH] Access token acquired successfully (token length: {len})
[VIDEO] API key authentication and token generation completed
```

## Related Documentation
- Feature Documentation: `docs/features/VIDEO_INDEXER_DUAL_AUTHENTICATION.md`
- Functional Test: `functional_tests/test_video_indexer_dual_authentication_support.py`
- Azure Video Indexer API Documentation: https://api-portal.videoindexer.ai/

## Backward Compatibility
- ✅ Existing managed identity configurations continue working without changes
- ✅ Default authentication type remains "managed_identity"
- ✅ No changes required to admin UI or settings structure
