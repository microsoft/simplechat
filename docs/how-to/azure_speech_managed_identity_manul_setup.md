# Azure Speech Service with Managed Identity Manual Setup

## Overview

This guide explains the critical difference between key-based and managed identity authentication when configuring Azure Speech Service, and the required steps to enable managed identity properly.

## Authentication Methods: Regional vs. Resource-Specific Endpoints

### Regional Endpoint (Shared Gateway)

**Endpoint format**: `https://<region>.api.cognitive.microsoft.com`
- Example: `https://eastus2.api.cognitive.microsoft.com`
- This is a **shared endpoint** for all Speech resources in that Azure region
- Acts as a gateway that routes requests to individual Speech resources

### Resource-Specific Endpoint (Custom Subdomain)

**Endpoint format**: `https://<resource-name>.cognitiveservices.azure.com`
- Example: `https://simplechat6-dev-speech.cognitiveservices.azure.com`
- This is a **unique endpoint** dedicated to your specific Speech resource
- Requires custom subdomain to be enabled on the resource

---

## Why Regional Endpoint Works with Key but NOT Managed Identity

### Key-Based Authentication ✅ Works with Regional Endpoint

When using subscription key authentication:

```http
POST https://eastus2.api.cognitive.microsoft.com/speechtotext/transcriptions:transcribe
Headers:
  Ocp-Apim-Subscription-Key: abc123def456...
```

**Why it works:**
1. The subscription key **directly identifies** your specific Speech resource
2. The regional gateway uses the key to look up which resource it belongs to
3. The request is automatically routed to your resource
4. Authorization succeeds because the key proves ownership

### Managed Identity (AAD Token) ❌ Fails with Regional Endpoint

When using managed identity authentication:

```http
POST https://eastus2.api.cognitive.microsoft.com/speechtotext/transcriptions:transcribe
Headers:
  Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGc...
```

**Why it fails (returns 400 BadRequest):**
1. The Bearer token proves your App Service identity to Azure AD
2. The token does NOT specify which Speech resource you want to access
3. The regional gateway cannot determine:
   - Which specific Speech resource you're authorized for
   - Whether your managed identity has RBAC roles on that resource
4. **Result**: The gateway rejects the request with 400 BadRequest

### Managed Identity ✅ Works with Resource-Specific Endpoint

When using managed identity with custom subdomain:

```http
POST https://simplechat6-dev-speech.cognitiveservices.azure.com/speechtotext/transcriptions:transcribe
Headers:
  Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGc...
```

**Why it works:**
1. The hostname **itself identifies** your specific Speech resource
2. Azure validates your managed identity Bearer token against that resource's RBAC
3. If your App Service MI has `Cognitive Services Speech User` role → authorized
4. The request proceeds to your dedicated Speech resource instance

---

## Required Setup for Managed Identity

### Prerequisites

1. **Azure Speech Service resource** created in your subscription
2. **System-assigned or user-assigned managed identity** on your App Service
3. **RBAC role assignments** on the Speech resource

### Step 1: Enable Custom Subdomain on Speech Resource

**Why needed**: By default, Speech resources use the regional endpoint and do NOT have custom subdomains. Managed identity requires the resource-specific endpoint.

**How to enable**:

```bash
az cognitiveservices account update \
  --name <speech-resource-name> \
  --resource-group <resource-group-name> \
  --custom-domain <speech-resource-name>
```

**Example**:

```bash
az cognitiveservices account update \
  --name simplechat6-dev-speech \
  --resource-group sc-simplechat6-dev-rg \
  --custom-domain simplechat6-dev-speech
```

**Important notes**:
- Custom subdomain name must be **globally unique** across Azure
- Usually use the same name as your resource: `<resource-name>`
- **One-way operation**: Cannot be disabled once enabled
- After enabling, the resource's endpoint property changes from regional to resource-specific

**Verify custom subdomain is enabled**:

```bash
az cognitiveservices account show \
  --name <speech-resource-name> \
  --resource-group <resource-group-name> \
  --query "{customSubDomainName:properties.customSubDomainName, endpoint:properties.endpoint}"
```

Expected output:
```json
{
  "customSubDomainName": "simplechat6-dev-speech",
  "endpoint": "https://simplechat6-dev-speech.cognitiveservices.azure.com/"
}
```

### Step 2: Assign RBAC Roles to Managed Identity

Grant your App Service managed identity the necessary roles on the Speech resource:

```bash
# Get the Speech resource ID
SPEECH_RESOURCE_ID=$(az cognitiveservices account show \
  --name <speech-resource-name> \
  --resource-group <resource-group-name> \
  --query id -o tsv)

# Get the App Service managed identity principal ID
MI_PRINCIPAL_ID=$(az webapp identity show \
  --name <app-service-name> \
  --resource-group <resource-group-name> \
  --query principalId -o tsv)

# Assign Cognitive Services Speech User role (data-plane read access)
az role assignment create \
  --assignee $MI_PRINCIPAL_ID \
  --role "Cognitive Services Speech User" \
  --scope $SPEECH_RESOURCE_ID

# Assign Cognitive Services Speech Contributor role (if needed for write operations)
az role assignment create \
  --assignee $MI_PRINCIPAL_ID \
  --role "Cognitive Services Speech Contributor" \
  --scope $SPEECH_RESOURCE_ID
```

**Verify role assignments**:

```bash
az role assignment list \
  --assignee $MI_PRINCIPAL_ID \
  --scope $SPEECH_RESOURCE_ID \
  -o table
```

### Step 3: Configure Admin Settings

In the Admin Settings → Search & Extract → Multimedia Support section:

| Setting | Value | Example |
|---------|-------|---------|
| **Enable Audio File Support** | ✅ Checked | |
| **Speech Service Endpoint** | Resource-specific endpoint (with custom subdomain) | `https://simplechat6-dev-speech.cognitiveservices.azure.com` |
| **Speech Service Location** | Azure region | `eastus2` |
| **Speech Service Locale** | Language locale for transcription | `en-US` |
| **Authentication Type** | Managed Identity | |
| **Speech Service Key** | (Leave empty when using MI) | |

**Critical**: 
- Endpoint must be the resource-specific URL (custom subdomain)
- Do NOT use the regional endpoint for managed identity
- Remove trailing slash from endpoint: ✅ `https://..azure.com` ❌ `https://..azure.com/`

### Step 4: Test Audio Upload

1. Upload a short WAV or MP3 file
2. Monitor application logs for transcription progress
3. Expected log output:
   ```
   File size: 1677804 bytes
   Produced 1 WAV chunks: ['/tmp/tmp_chunk_000.wav']
   [Debug] Transcribing WAV chunk: /tmp/tmp_chunk_000.wav
   [Debug] Speech config obtained successfully
   [Debug] Received 5 phrases
   Creating 3 transcript pages
   ```

---

## Troubleshooting

### Error: NameResolutionError - Failed to resolve hostname

**Symptom**: `Failed to resolve 'simplechat6-dev-speech.cognitiveservices.azure.com'`

**Cause**: Custom subdomain not enabled on Speech resource

**Solution**: Enable custom subdomain using Step 1 above

### Error: 400 BadRequest when using MI with regional endpoint

**Symptom**: `400 Client Error: BadRequest for url: https://eastus2.api.cognitive.microsoft.com/speechtotext/transcriptions:transcribe`

**Cause**: Managed identity requires resource-specific endpoint, not regional

**Solution**: Update Admin Settings endpoint to use `https://<resource-name>.cognitiveservices.azure.com`

### Error: 401 Authentication error with MI

**Symptom**: `WebSocket upgrade failed: Authentication error (401)`

**Cause**: Missing RBAC role assignments

**Solution**: Assign required roles using Step 2 above

### Key auth works but MI fails

**Diagnosis checklist**:
- [ ] Custom subdomain enabled on Speech resource?
- [ ] Admin Settings endpoint is resource-specific (not regional)?
- [ ] Managed identity has RBAC roles on Speech resource?
- [ ] Authentication Type set to "Managed Identity" in Admin Settings?

---

## Summary

| Authentication Method | Endpoint Type | Example | Works? |
|----------------------|---------------|---------|--------|
| **Key** | Regional | `https://eastus2.api.cognitive.microsoft.com` | ✅ Yes |
| **Key** | Resource-specific | `https://simplechat6-dev-speech.cognitiveservices.azure.com` | ✅ Yes |
| **Managed Identity** | Regional | `https://eastus2.api.cognitive.microsoft.com` | ❌ No (400 BadRequest) |
| **Managed Identity** | Resource-specific | `https://simplechat6-dev-speech.cognitiveservices.azure.com` | ✅ Yes (with custom subdomain) |

**Key takeaway**: Managed identity for Azure Cognitive Services data-plane operations requires:
1. Custom subdomain enabled on the resource
2. Resource-specific endpoint configured in your application
3. RBAC roles assigned to the managed identity at the resource scope

---

## References

- [Azure Cognitive Services custom subdomain documentation](https://learn.microsoft.com/azure/cognitive-services/cognitive-services-custom-subdomains)
- [Authenticate with Azure AD using managed identity](https://learn.microsoft.com/azure/cognitive-services/authentication?tabs=powershell#authenticate-with-azure-active-directory)
- [Azure Speech Service authentication](https://learn.microsoft.com/azure/ai-services/speech-service/rest-speech-to-text-short)
