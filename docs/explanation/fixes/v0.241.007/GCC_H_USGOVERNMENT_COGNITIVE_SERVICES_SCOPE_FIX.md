# GCC-H US Government Cognitive Services Scope Fix

Fixed/Implemented in version: **0.241.007**
**GitHub Issue:** #876 — Agent invocations fail with 401 in Azure Government (GCC-H) when using managed_identity auth

## Issue Description

When running SimpleChat locally against an Azure Government Cloud (GCC-H) deployment with
`managed_identity` authentication for Azure OpenAI, agent invocations returned a **401 Unauthorized**
error. The token being acquired used the public-cloud Cognitive Services audience
(`https://cognitiveservices.azure.com/.default`) instead of the government-cloud audience
(`https://cognitiveservices.azure.us/.default`), so Azure OpenAI rejected every request.

## Root Cause Analysis

Two related gaps in `semantic_kernel_loader.py`:

1. **Wrong scope for the global GPT token provider** — `resolve_global_gpt_token_provider` built its
   `auth_settings` dict from Cosmos `app_settings` fields only. The Cosmos record did not contain a
   `management_cloud` key, so the value fell through to the hardcoded default `"public"`. The
   `build_token_provider` function then selected the public-cloud scope unconditionally.

2. **Wrong scope for `build_token_provider` itself** — Before this fix, `build_token_provider` did
   not inspect `management_cloud` at all; `scope` was hardcoded to
   `https://cognitiveservices.azure.com/.default` regardless of the cloud environment.

Neither path read the `AZURE_ENVIRONMENT` environment variable that is already used everywhere else in
the codebase (`config.py`, route handlers, Bicep-generated App Service settings) to signal the active
cloud.

## Technical Details

### Files Modified

- `application/single_app/semantic_kernel_loader.py`

### Code Changes Summary

**Change 1 — `build_token_provider`: dynamic scope selection based on `management_cloud`**

```python
# Before
scope = "https://cognitiveservices.azure.com/.default"

# After
management_cloud = (auth_settings.get("management_cloud") or "public").lower()
if management_cloud in ("government", "usgovernment", "usgov"):
    scope = "https://cognitiveservices.azure.us/.default"
else:
    scope = "https://cognitiveservices.azure.com/.default"
```

**Change 2 — `resolve_global_gpt_token_provider`: fall back to `AZURE_ENVIRONMENT` env var**

```python
# Before
"management_cloud": settings.get("management_cloud") or settings.get("azure_management_cloud") or "public",

# After
"management_cloud": settings.get("management_cloud") or settings.get("azure_management_cloud") or os.getenv("AZURE_ENVIRONMENT", "public"),
```

Together these changes mean:
- If `management_cloud` is set explicitly in the Cosmos `app_settings` record, that value wins.
- Otherwise the runtime falls back to the `AZURE_ENVIRONMENT` environment variable, which is already
  set to `usgovernment` in the App Service configuration for GCC-H deployments (and in `.env` for
  local GCC-H development).
- No Cosmos data migration or admin UI change is required.

### Scope of Impact

This fix applies to the **global GPT token provider path** — the path taken when an agent uses the
globally-configured Azure OpenAI endpoint (the common case). It does not change the behaviour of the
**multi-endpoint path** (`enable_multi_model_endpoints`); that path already reads `management_cloud`
from the per-endpoint `auth` record stored in Cosmos, so it is unaffected.

## Validation

### Before

- Agent invocations returned HTTP 401 with an audience mismatch error.
- The acquired token targeted `https://cognitiveservices.azure.com/` even when
  `AZURE_ENVIRONMENT=usgovernment`.

### After

- `build_token_provider` selects `https://cognitiveservices.azure.us/.default` when
  `management_cloud` resolves to any government-cloud alias.
- `resolve_global_gpt_token_provider` correctly inherits `usgovernment` from `AZURE_ENVIRONMENT`
  when no explicit Cosmos override is present.
- Agent invocations succeed against the GCC-H Azure OpenAI endpoint with a valid gov-cloud token.

### Local Development Setup

Set the following in `.env` (no Cosmos changes required):

```dotenv
AZURE_ENVIRONMENT=usgovernment
AZURE_AUTHORITY_HOST=https://login.microsoftonline.us
```

`DefaultAzureCredential` will use `AZURE_AUTHORITY_HOST` to target the government AAD endpoint, and
`semantic_kernel_loader.py` will now correctly select the government Cognitive Services scope.
