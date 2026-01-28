# Sovereign Cloud Cognitive Services Scope Fix

## Overview

Fixed hardcoded commercial Azure cognitive services scope references in chat streaming and Smart HTTP Plugin that prevented proper authentication in Azure Government (MAG) and custom cloud environments.

**Version Implemented:** v0.237.001

**Related Issue:** [#616](https://github.com/microsoft/simplechat/issues/616#issue-3835164022)

## Problem

The `chat_stream_api` and `smart_http_plugin` contained hardcoded references to commercial Azure cognitive services scope URLs. This caused authentication failures when running SimpleChat in:
- Azure Government (MAG) environments
- Custom/sovereign cloud deployments

### Error Symptoms

Users in MAG environments encountered authentication errors when:
- Using chat with streaming enabled
- Making Smart HTTP Plugin calls

The error occurred because the code attempted to authenticate against commercial Azure endpoints instead of the appropriate government or custom cloud endpoints.

## Root Cause

The authentication scope was hardcoded as the commercial cognitive services URL rather than using the configurable value from `config.py`. This meant:
- Commercial: `https://cognitiveservices.azure.com/.default`
- Government: Should be `https://cognitiveservices.azure.us/.default`
- Custom: Should use environment-specific scope

## Solution

Replaced all hardcoded cognitive services scope references with the configurable variable from `config.py`:
- `AZURE_OPENAI_TOKEN_SCOPE` environment variable
- Dynamically resolved based on cloud environment

### Files Modified

1. **chat_stream_api** (streaming chat implementation)
   - Replaced hardcoded scope with `config.AZURE_OPENAI_TOKEN_SCOPE`

2. **smart_http_plugin** (Smart HTTP Plugin)
   - Replaced hardcoded scope with configurable variable

## Cloud Environment Support

| Cloud Environment | Cognitive Services Scope |
|-------------------|-------------------------|
| Commercial | `https://cognitiveservices.azure.com/.default` |
| Government (MAG) | `https://cognitiveservices.azure.us/.default` |
| China | `https://cognitiveservices.azure.cn/.default` |
| Custom | Configurable via environment variable |

## Testing

### Azure Government Validation

1. Deploy SimpleChat to Azure Government environment
2. Configure appropriate Azure OpenAI resources
3. Enable streaming in chat settings
4. Send a chat message with streaming enabled
5. Verify response streams correctly without authentication errors

### Commercial Cloud Validation

1. Verify existing commercial deployments continue to function
2. Test streaming chat functionality
3. Test Smart HTTP Plugin calls

## Impact

- **Azure Government**: Full streaming and plugin functionality now works correctly
- **Custom Clouds**: Deployments can configure appropriate scope for their environment
- **Commercial**: No change to existing behavior

## Configuration

The cognitive services scope is configured via:

```python
# config.py
AZURE_OPENAI_TOKEN_SCOPE = os.getenv('AZURE_OPENAI_TOKEN_SCOPE', 'https://cognitiveservices.azure.com/.default')
```

For Azure Government, set:
```
AZURE_OPENAI_TOKEN_SCOPE=https://cognitiveservices.azure.us/.default
```

## Related

- Sovereign Cloud Managed Identity Authentication Fix (v0.229.001)
- Azure Government Support documentation
