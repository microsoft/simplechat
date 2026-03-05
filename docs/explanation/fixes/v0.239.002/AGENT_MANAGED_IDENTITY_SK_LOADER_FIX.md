# Agent Managed Identity SK Loader Fix

**Fixed/Implemented in version:** **0.239.002**  
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

## Security Vulnerability (Identified by GitHub Copilot PR Review)

Once the silent-failure fix was submitted as a pull request, a GitHub Copilot automated review
identified a **credential-theft vulnerability** in the initial implementation.

### The Risk

The initial `use_managed_identity` expression had only four guards:

```python
use_managed_identity = (
    auth_type == 'managed_identity'
    and not apim_enabled
    and not agent_config.get("key")
    and bool(DefaultAzureCredential)
    # ← MISSING: no check on whether the endpoint is user/agent-supplied
)
```

With `allow_group_custom_agent_endpoints = True` (a legitimate admin configuration), a group
workspace admin could configure an agent with a **custom Azure OpenAI endpoint** pointing to an
attacker-controlled server. Because `use_managed_identity` had no endpoint check, the app would
obtain a real MI bearer token (scoped to Azure Cognitive Services) and send it in the
`Authorization: Bearer ...` header to that attacker-controlled endpoint — **leaking the app's
managed identity credentials** to a third party.

### How `resolve_agent_config()` Flags Endpoint Ownership

`resolve_agent_config()` already tagged every branch of its decision tree with an
`endpoint_is_user_supplied` flag indicating whether the resolved endpoint is under system control
or was provided by a user/agent config:

| Case | Condition | `endpoint_is_user_supplied` |
|------|-----------|-----------------------------|
| 1 | User APIM values set and allowed | `True` — agent-supplied |
| 2 | User APIM on but empty; fall to global APIM | `False` — system-controlled |
| 3 | Agent GPT config fully filled and allowed | `True` — agent-supplied |
| 4 | Agent GPT config partially filled, no global APIM | `True` — agent-supplied |
| 5 | Global APIM enabled | `False` — system-controlled |
| 6 | Global GPT fallback (most common MI scenario) | `False` — system-controlled |

MI tokens should only ever be sent to Cases 2, 5, and 6 (system-controlled). The missing guard
meant MI tokens could also reach Cases 1, 3, and 4.

### The Security Fix

A fifth guard was added to `use_managed_identity`:

```python
and not agent_config.get("endpoint_is_user_supplied", False)
```

This single condition closes the token-theft path: even if all other guards pass, if the
resolved endpoint is agent/user-supplied, `use_managed_identity` evaluates to `False`, the gate
condition fails (no key + no MI), and the agent fails to load rather than leaking the MI token.

**Intended behaviour for affected agents:** An agent that uses a custom endpoint must supply its
own API key. Relying on the app's managed identity to authenticate against a third-party or
operator-controlled endpoint is by design disallowed.

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
use_managed_identity = (
    auth_type == 'managed_identity'                                         # guard 1
    and not apim_enabled                                                    # guard 2
    and not agent_config.get("key")                                         # guard 3
    and bool(DefaultAzureCredential)                                        # guard 4
    and not agent_config.get("endpoint_is_user_supplied", False)            # guard 5 — security
)
```

`use_managed_identity` is `True` only when ALL five guards hold:
1. Global auth type is `managed_identity`
2. APIM is not enabled (APIM uses subscription keys, not MI)
3. No API key is present (if a key exists, use it directly)
4. `azure-identity` imported successfully (`DefaultAzureCredential` is not `None`)
5. **Endpoint is system-controlled** — `endpoint_is_user_supplied` is `False` (Cases 2, 5, 6 only)

Guard 5 was added in response to the Copilot security finding — see the **Security Vulnerability**
section above for the full explanation.

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
    → SK Loader resolves agent config (case 6: global GPT fallback, allow_user_custom_agent_endpoints=False)
    → endpoint = global endpoint, key = None (MI), deployment = 'gpt-4.1', endpoint_is_user_supplied = False
    → use_managed_identity = True  (auth_type='managed_identity', key=None, APIM=off, DefaultAzureCredential ok, endpoint_is_user_supplied=False)
    → Gate passes: (agent_config["key"] or use_managed_identity) = True
    → AzureChatCompletion created with ad_token_provider (DefaultAzureCredential)
    → Agent loads with full instructions + ServiceNow tools (OpenAPI plugin)
    → Agent calls queryAssets → OpenAPI plugin injects Bearer token → ServiceNow returns real data
    → Real results displayed (no fabrication)
```