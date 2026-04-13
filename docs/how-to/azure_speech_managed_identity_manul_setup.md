---
layout: showcase-page
title: "Azure Speech Managed Identity Setup"
permalink: /how-to/azure_speech_managed_identity_manul_setup/
menubar: docs_menu
accent: blue
eyebrow: "How-To Guide"
description: "Configure Azure Speech for managed identity correctly by using the resource-specific endpoint, the right RBAC roles, and the matching Admin Settings fields."
hero_icons:
  - bi-mic
  - bi-person-badge
  - bi-globe2
hero_pills:
  - Custom subdomain required
  - Regional endpoint fails with MI
  - Speech User role first
hero_links:
  - label: "Managed identity guide"
    url: /how-to/use_managed_identity/
    style: primary
  - label: "Admin configuration"
    url: /reference/admin_configuration/
    style: secondary
---

Speech is the place where managed identity setup becomes very specific. The most important rule is simple: the regional endpoint that works with keys is not enough for managed identity. You need the resource-specific custom-subdomain endpoint so Azure can evaluate RBAC against the correct Speech resource.

<section class="latest-release-card-grid">
    <article class="latest-release-card">
        <div class="latest-release-card-icon"><i class="bi bi-globe2"></i></div>
        <h2>Use the resource-specific endpoint</h2>
        <p>Managed identity needs the custom-subdomain Speech endpoint, not the shared regional gateway endpoint used by key-based authentication.</p>
    </article>
    <article class="latest-release-card">
        <div class="latest-release-card-icon"><i class="bi bi-shield-check"></i></div>
        <h2>Grant RBAC on the Speech resource</h2>
        <p>Start with <code>Cognitive Services Speech User</code> and add <code>Cognitive Services Speech Contributor</code> only if the specific transcription flow still needs it.</p>
    </article>
    <article class="latest-release-card">
        <div class="latest-release-card-icon"><i class="bi bi-sliders"></i></div>
        <h2>Fill the matching admin fields</h2>
        <p>Endpoint, region, locale, authentication type, and resource ID all need to align with the Speech resource you are actually authorizing.</p>
    </article>
    <article class="latest-release-card">
        <div class="latest-release-card-icon"><i class="bi bi-check2-square"></i></div>
        <h2>Test with a real audio workflow</h2>
        <p>Validate with upload, transcription, and optional text-to-speech scenarios rather than stopping at a configuration save.</p>
    </article>
</section>

<div class="latest-release-note-panel">
    <h2>The endpoint format is the root-cause difference</h2>
    <p>With key authentication, the regional endpoint can infer the target resource from the key. With managed identity, Azure needs the hostname itself to identify the specific Speech resource so it can evaluate RBAC. That is why the custom subdomain is mandatory here.</p>
</div>

## Authentication Methods: Regional vs. Resource-Specific Endpoints

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

For some transcription operations, you may also need `Cognitive Services Speech Contributor`. Start with `Speech User`, then add `Speech Contributor` if transcription still fails after endpoint and identity configuration are correct.

---

## Required Setup for Managed Identity

### Prerequisites

1. **Azure Speech Service resource** created in your subscription
2. **System-assigned or user-assigned managed identity** on your App Service
3. **RBAC role assignments** on the Speech resource

### Step 1: Turn On the Custom Domain on the Speech Resource

**Why needed**: By default, Speech resources use the regional endpoint and do NOT have custom subdomains. Managed identity requires the resource-specific endpoint.

#### Azure portal walkthrough

1. Go to the Azure portal and open your **Azure AI Speech** resource.
2. In the left pane under **Resource Management**, select **Networking**.
3. Open the **Firewalls and virtual networks** tab.
4. Select **Generate Custom Domain Name**.
5. Enter a globally unique custom domain name. The final endpoint will look like `https://<custom-name>.cognitiveservices.azure.com`.
6. Select **Save**.
7. After the update finishes, open **Keys and Endpoint** and confirm the resource endpoint now starts with `https://<custom-name>.cognitiveservices.azure.com`.

**Important notes**:
- Custom subdomain name must be **globally unique** across Azure
- Usually use the same name as your resource: `<resource-name>`
- **One-way operation**: Cannot be disabled once enabled
- Microsoft Learn recommends trying the change on a test resource first if the production Speech resource already has many Speech Studio models or projects

#### Azure CLI alternative

If you prefer CLI instead of the portal:

```bash
az account set --subscription <subscription-id>
az cognitiveservices account update \
  --name <speech-resource-name> \
  --resource-group <resource-group-name> \
  --custom-domain <speech-resource-name>
```

**Example**:

```bash
az account set --subscription <subscription-id>
az cognitiveservices account update \
  --name simplechat6-dev-speech \
  --resource-group sc-simplechat6-dev-rg \
  --custom-domain simplechat6-dev-speech
```

#### Verify the custom domain is enabled

Portal verification:

1. Open the Speech resource.
2. Go to **Keys and Endpoint**.
3. Confirm the endpoint now starts with `https://<custom-name>.cognitiveservices.azure.com` instead of `https://<region>.api.cognitive.microsoft.com`.

CLI verification:

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

# Assign Cognitive Services Speech User role (baseline data-plane access)
az role assignment create \
  --assignee $MI_PRINCIPAL_ID \
  --role "Cognitive Services Speech User" \
  --scope $SPEECH_RESOURCE_ID

# Assign Cognitive Services Speech Contributor role (if transcription operations still require it)
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

- Use the **Setup Guide** button on the **AI Voice Conversations** card if you want an in-app walkthrough while filling the Speech fields.

| Setting | Value | Example |
|---------|-------|---------|
| **Enable Audio File Support** | ✅ Checked | |
| **Enable Speech-to-Text Input** | Optional | |
| **Enable Text-to-Speech** | Optional | |
| **Speech Service Endpoint** | Resource-specific endpoint (with custom subdomain) | `https://simplechat6-dev-speech.cognitiveservices.azure.com` |
| **Speech Service Location** | Azure region | `eastus2` |
| **Speech Service Locale** | Language locale for transcription | `en-US` |
| **Authentication Type** | Managed Identity | |
| **Speech Subscription ID** | Optional helper for building the ARM resource ID in the Admin UI | `12345678-1234-1234-1234-123456789abc` |
| **Speech Resource Group** | Optional helper for building the ARM resource ID in the Admin UI | `rg-speech-prod` |
| **Speech Resource Name** | Optional helper for building the ARM resource ID in the Admin UI | `my-speech-resource` |
| **Speech Service Key** | (Leave empty when using MI) | |
| **Speech Resource ID** | Required when using managed identity for text-to-speech | `/subscriptions/.../providers/Microsoft.CognitiveServices/accounts/<speech-resource-name>` |

**Critical**: 
- Endpoint must be the resource-specific URL (custom subdomain)
- Do NOT use the regional endpoint for managed identity
- If you have not created the custom domain yet, use the Azure portal walkthrough in Step 1 before saving the Speech endpoint in Admin Settings
- Remove trailing slash from endpoint: ✅ `https://..azure.com` ❌ `https://..azure.com/`
- If text-to-speech is enabled with managed identity, set the full Speech Resource ID in Admin Settings
- If you do not know the full resource ID, the Admin Settings page can build it from Subscription ID, Resource Group, and Speech Resource Name

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

### Error: Text-to-speech fails with MI but transcription works

**Symptom**: Audio uploads or speech-to-text input succeed, but `/api/chat/tts` fails when authentication type is Managed Identity.

**Cause**: Text-to-speech managed identity also requires the Speech Resource ID in addition to the custom-domain endpoint and region.

**Solution**: Populate **Speech Resource ID** in Admin Settings and verify the App Service managed identity has the required RBAC role(s).

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
