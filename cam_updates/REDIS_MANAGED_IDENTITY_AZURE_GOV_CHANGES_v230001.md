# Redis Managed Identity Azure Government Support Changes

## Summary
Updated the ManagedIdentity code path to work correctly with Azure Government deployments and support custom Redis endpoints for token acquisition.

## Changes Made

### 1. Added Environment Variable Support (`config.py`)
- Added `CUSTOM_REDIS_CACHE_INFRASTRUCTURE_URL_VALUE` environment variable for custom Azure environments
- This allows overriding the Redis cache infrastructure endpoint when needed

### 2. Created Helper Function (`config.py`)
- Added `get_redis_cache_infrastructure_endpoint(redis_hostname: str)` function
- Returns appropriate Redis cache infrastructure endpoints based on `AZURE_ENVIRONMENT`:
  - **Public Cloud**: `https://{hostname}.cacheinfra.windows.net:10225/appid`
  - **US Government**: `https://{hostname}.cacheinfra.azure.us:10225/appid`
  - **Custom**: Uses `CUSTOM_REDIS_CACHE_INFRASTRUCTURE_URL_VALUE` with `{hostname}` placeholder

### 3. Updated Session Configuration (`app.py`)
- Modified `configure_sessions()` function to use the new helper function
- Replaces hardcoded `.cacheinfra.windows.net` endpoint with environment-aware logic
- Properly handles Azure Government deployments with managed identity

### 4. Updated Redis Testing (`route_backend_settings.py`)
- Modified `_test_redis_connection()` function to use the new helper function
- Ensures Redis connection testing works across all Azure environments
- Fixed token acquisition to use proper `.token` attribute

## Example Usage

### For Azure Government:
```bash
export AZURE_ENVIRONMENT="usgovernment"
```
Token will be acquired from: `https://{redis_hostname}.cacheinfra.azure.us:10225/appid`

### For Custom Environment:
```bash
export AZURE_ENVIRONMENT="custom"
export CUSTOM_REDIS_CACHE_INFRASTRUCTURE_URL_VALUE="https://{hostname}.cacheinfra.windows.net:10225/appid"
```

### User's Example:
The hardcoded suffix example you provided:
```python
token = credential.get_token(f"https://{redis_hostname}.cacheinfra.windows.net:10225/appid")
```

Is now handled dynamically based on environment, supporting:
- Azure Public Cloud: `.cacheinfra.windows.net`
- Azure Government: `.cacheinfra.azure.us`
- Custom environments: Configurable via environment variable

## Files Modified
1. `/workspaces/simplechat/application/single_app/config.py`
2. `/workspaces/simplechat/application/single_app/app.py`
3. `/workspaces/simplechat/application/single_app/route_backend_settings.py`

## Testing
All modified files pass syntax validation. The solution maintains backward compatibility while adding support for Azure Government and custom environments.