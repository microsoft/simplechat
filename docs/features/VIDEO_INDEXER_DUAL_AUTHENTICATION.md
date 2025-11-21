# Video Indexer Dual Authentication Support

## Feature Overview
Added comprehensive support for both API key and managed identity authentication methods for Azure Video Indexer integration.

**Implemented in version:** 0.229.064  
**Fixed in version:** 0.229.065

## Background
Previously, the Video Indexer integration only supported managed identity authentication despite having API key fields in the admin UI. This feature implements full dual authentication support, allowing users to choose between:
- **Managed Identity**: Uses Azure ARM token-based authentication, generates access token via ARM API
- **API Key**: Uses subscription key to generate access token via Video Indexer auth endpoint

## Technical Implementation

### 1. Authentication Functions (`functions_authentication.py`)
- **New Function**: `get_video_indexer_account_token()` - Main entry point that branches based on authentication type
- **Enhanced Function**: `get_video_indexer_api_key_token()` - Uses API key to generate access token via Video Indexer auth endpoint
- **Enhanced Function**: `get_video_indexer_managed_identity_token()` - Handles ARM token acquisition and generates access token via ARM API

#### Authentication Flow
```python
auth_type = settings.get("video_indexer_authentication_type", "managed_identity")

if auth_type == "key":
    return get_video_indexer_api_key_token(settings, video_id)
else:
    return get_video_indexer_managed_identity_token(settings, video_id)
```

#### API Key Token Generation
```python
# Generate access token using API key
api_url = "https://api.videoindexer.ai"
auth_url = f"{api_url}/auth/{location}/Accounts/{account_id}/AccessToken"
headers = {"Ocp-Apim-Subscription-Key": api_key}
params = {"allowEdit": "true"}
response = requests.get(auth_url, headers=headers, params=params)
access_token = response.text.strip('"')
```

### 2. Video Processing Updates (`functions_documents.py`)
Updated all Video Indexer API calls to use access tokens for authentication:

#### Authentication Pattern (Both Methods)
Both API key and managed identity authentication now return an access token that is used consistently across all Video Indexer API calls:
- Uses `accessToken` query parameter in all API requests
- No headers required for authentication after token is generated
- Token is generated once per operation and reused for upload, polling, and deletion

#### API Key Flow
1. API key → Video Indexer auth endpoint → Access token
2. Access token → Video Indexer API calls (upload, poll, delete)

#### Managed Identity Flow
1. Managed identity → ARM API → Access token  
2. Access token → Video Indexer API calls (upload, poll, delete)

#### Affected Operations
- Video upload and processing: `?accessToken={token}`
- Processing status polling: `?accessToken={token}`
- Video deletion: `?accessToken={token}`
- Video validation: Uses same access token pattern

### 3. Admin UI Controls (`admin_settings.html`)
Added authentication type selector with conditional field visibility:

#### New Controls
- **Authentication Type Dropdown**: Select between "Managed Identity" and "API Key"
- **Conditional Field Visibility**: 
  - API key field shown only when "API Key" selected
  - ARM fields shown only when "Managed Identity" selected

#### JavaScript Behavior
- Dynamic show/hide of relevant fields based on selection
- Seamless user experience with real-time form updates

### 4. Backend Form Handling (`route_frontend_admin_settings.py`)
Updated form processing to capture and save the authentication type setting.

### 5. Default Settings (`functions_settings.py`)
Added `video_indexer_authentication_type` with default value `"managed_identity"` to maintain backward compatibility.

## Usage Instructions

### Configuring API Key Authentication
1. Navigate to Admin Settings → Video Indexer
2. Select "API Key" from Authentication Type dropdown
3. Enter your Video Indexer subscription key
4. API key fields will be automatically shown
5. Save settings

### Configuring Managed Identity Authentication  
1. Navigate to Admin Settings → Video Indexer
2. Select "Managed Identity" from Authentication Type dropdown
3. Configure ARM resource management settings
4. Managed identity fields will be automatically shown
5. Save settings

## Configuration Options

### API Key Method
- **video_indexer_authentication_type**: `"key"`
- **video_indexer_key**: Your subscription key
- **video_indexer_account_id**: Your account ID
- **video_indexer_location**: Your region

### Managed Identity Method
- **video_indexer_authentication_type**: `"managed_identity"`
- **video_indexer_arm_access_token**: Auto-acquired
- **video_indexer_account_id**: Your account ID
- **video_indexer_location**: Your region

## Benefits
- **Flexibility**: Choose authentication method based on security requirements
- **Backward Compatibility**: Existing managed identity setups continue working
- **Security**: Support for both enterprise (managed identity) and development (API key) scenarios
- **User Experience**: Intuitive admin interface with contextual field visibility

## Testing Coverage
Comprehensive functional testing validates:
- ✅ Settings configuration and defaults
- ✅ Authentication function branching logic
- ✅ Video processing API call adaptations
- ✅ Admin UI control behavior and visibility
- ✅ Backend form processing integration

## Integration Points
- **Azure Video Indexer API**: Dual authentication support
- **Azure ARM API**: Managed identity token acquisition
- **Admin Settings UI**: Authentication method selection
- **Cosmos DB**: Settings persistence
- **Application Logging**: Authentication method tracking

## Dependencies
- Azure Video Indexer service
- Azure ARM API (for managed identity)
- DefaultAzureCredential (for managed identity)
- Bootstrap CSS framework (for UI)

## Known Limitations
- Authentication type cannot be changed during video processing
- API key method requires manual key management and rotation
- Managed identity requires proper Azure RBAC permissions

## Future Enhancements
- Authentication method validation and testing within admin UI
- Automatic fallback between authentication methods
- Enhanced logging for authentication troubleshooting