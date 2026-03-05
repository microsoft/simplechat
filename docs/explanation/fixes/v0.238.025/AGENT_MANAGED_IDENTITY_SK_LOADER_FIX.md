# Agent Managed Identity SK Loader Fix

**Fixed/Implemented in version:** **0.238.025** (matches `config.py` `app.config['VERSION']`)  
**GitHub Issue:** [#769 — Agents fail silently when using Managed Identity authentication](https://github.com/microsoft/simplechat/issues/769)

## Issue Description

When using **Azure Managed Identity (MI)** for Azure OpenAI authentication, agents configured through
the **Model & Connection** page (Step 2 of the agent wizard) failed silently — the agent never loaded,
fell back to plain GPT-4.1 with no tools or instructions, and fabricated responses instead of calling
real APIs (e.g., ServiceNow).

## Root Cause Analysis

### How Agent Config Is Resolved

`resolve_agent_config()` in `semantic_kernel_loader.py` (~line 107) figures out which endpoint/key/
deployment to use for an agent by running through a **decision tree** (~line 291):

```
# 1. User APIM enabled and any user APIM values set → use user APIM
# 2. User APIM enabled but empty, global APIM enabled → use global APIM
# 3. Agent GPT config is FULLY filled → use agent GPT config
# 4. Agent GPT config is PARTIALLY filled, global APIM off → merge agent GPT with global GPT
# 5. Global APIM enabled → use global APIM
# 6. Fallback → use global GPT config entirely
```

### The Failure

When an agent is configured with only the deployment name set (endpoint and key left blank), the
decision tree hits **case 4** — it merges the agent's partial config with global settings:

```
Agent-level:  endpoint='',  key='',  deployment='gpt-4.1',  api_version=''
```

After merge with global settings:
- `endpoint` = global endpoint ✓
- `deployment` = `'gpt-4.1'` ✓
- `key` = global key = **`None`** ✗ (MI auth — no API key is stored in settings)

The gate condition at ~line 768 then fails:

```python
if AzureChatCompletion and agent_config["endpoint"] and agent_config["key"] and agent_config["deployment"]:
```

`agent_config["key"]` is `None` → **condition is False** → falls into the `else` block:

```
[SK Loader] Azure config INVALID for servicenow_support_agent:
  - AzureChatCompletion available: True
  - endpoint: True
  - key: False          ← THIS IS THE FAILURE
  - deployment: True
```

Returns `None, None` → no agent loaded → chat uses plain GPT-4.1 with no tools/instructions
→ GPT fabricates responses instead of calling the actual API.

## Files Modified

| File | Lines Changed |
|------|--------------|
| `application/single_app/semantic_kernel_loader.py` | ~43-47, ~767-768, ~810-829, ~1530-1532, ~1548-1558, ~1636-1638, ~1655-1665 |
| `application/single_app/config.py` | VERSION bump |

## Fix

### 1. Added Azure Identity imports (~line 43)

```python
try:
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider
except ImportError:
    DefaultAzureCredential = None
    get_bearer_token_provider = None
```

### 2. Added MI detection before each gate (~line 767)

At each of the 3 `AzureChatCompletion` creation sites (single agent, multi-agent specialist,
multi-agent orchestrator):

```python
auth_type = settings.get('azure_openai_gpt_authentication_type', '')
use_managed_identity = (auth_type == 'managed_identity') and not apim_enabled and not agent_config.get("key")
```

`use_managed_identity` is `True` when ALL of:
- Global auth type is `managed_identity`
- APIM is not enabled (APIM uses subscription keys, not MI)
- No API key is present (if a key exists, use it directly)

### 3. Updated gate condition to accept MI (~line 768)

Before:
```python
if AzureChatCompletion and agent_config["endpoint"] and agent_config["key"] and agent_config["deployment"]:
```

After:
```python
if AzureChatCompletion and agent_config["endpoint"] and (agent_config["key"] or use_managed_identity) and agent_config["deployment"]:
```

### 4. Added MI branch for AzureChatCompletion creation (~line 789)

Between the existing APIM branch and direct-key branch, a new `elif use_managed_identity:` block:

```python
elif use_managed_identity:
    # Detect gov vs commercial cloud from endpoint URL
    _scope = "https://cognitiveservices.azure.us/.default" if ".azure.us" in (agent_config.get("endpoint") or "") else "https://cognitiveservices.azure.com/.default"
    _token_provider = get_bearer_token_provider(DefaultAzureCredential(), _scope)
    chat_service = AzureChatCompletion(
        service_id=service_id,
        deployment_name=agent_config["deployment"],
        endpoint=agent_config["endpoint"],
        ad_token_provider=_token_provider,   # ← MI token, not api_key
        api_version=agent_config["api_version"],
    )
```

The scope is auto-detected: endpoints containing `.azure.us` use the Azure Government scope;
all others use the commercial Azure scope.

## Auth Flow After Fix

```
User sends message
    → SK Loader resolves agent config (case 4: merge agent partial + global GPT)
    → endpoint = global endpoint, key = None (MI), deployment = 'gpt-4.1'
    → use_managed_identity = True  (auth_type='managed_identity', key=None, APIM=off)
    → Gate passes: (agent_config["key"] or use_managed_identity) = True
    → AzureChatCompletion created with ad_token_provider (DefaultAzureCredential)
    → Agent loads with full instructions + ServiceNow tools (OpenAPI plugin)
    → Agent calls queryAssets → OpenAPI plugin injects Bearer token → ServiceNow returns real data
    → Real results displayed (no fabrication)
```