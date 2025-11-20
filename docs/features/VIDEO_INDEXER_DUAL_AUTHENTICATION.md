# Video Indexer Dual Authentication Support

## Feature Overview
Added comprehensive support for both API key and managed identity authentication methods for Azure Video Indexer integration.

**Implemented in version:** 0.229.064

## Background
Previously, the Video Indexer integration only supported managed identity authentication despite having API key fields in the admin UI. This feature implements full dual authentication support, allowing users to choose between:
- **Managed Identity**: Uses Azure ARM token-based authentication
- **API Key**: Uses subscription key-based authentication

## Technical Implementation

### 1. Authentication Functions (`functions_authentication.py`)
- **New Function**: `get_video_indexer_account_token()` - Main entry point that branches based on authentication type
- **Enhanced Function**: `get_video_indexer_api_key()` - Returns API key from settings
- **Enhanced Function**: `get_video_indexer_managed_identity_token()` - Handles ARM token acquisition

#### Authentication Flow
```python
auth_type = settings.get("video_indexer_authentication_type", "managed_identity")

if auth_type == "key":
    return get_video_indexer_api_key()
else:
    return get_video_indexer_managed_identity_token()
```

### 2. Video Processing Updates (`functions_documents.py`)
Updated all Video Indexer API calls to use appropriate authentication headers:

#### API Key Authentication
- Uses `Ocp-Apim-Subscription-Key` header
- Direct API key in header value

#### Managed Identity Authentication  
- Uses `accessToken` query parameter
- ARM token from managed identity

#### Affected Operations
- Video upload and processing
- Processing status polling
- Video deletion
- Video validation

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