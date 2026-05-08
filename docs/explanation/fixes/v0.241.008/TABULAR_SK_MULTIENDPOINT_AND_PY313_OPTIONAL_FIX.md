# Fixes — v0.241.009 (branch: feature/tabular-plugin-gpt51-redesign)

> Resolves [Bug] Tabular SK analysis: multi-endpoint DeploymentNotFound 404 and Python 3.13 Optional[str] type error [#891](../../../../../../issues/891)

Two related issues were identified and resolved in this release while diagnosing why tabular SK analysis was falling back to "schema context instead" when querying an Excel file (NIST SP-800-53) using a multi-endpoint model (`gpt-5.1`).

---

## Fix 1 — Tabular SK Analysis: DeploymentNotFound 404 with Multi-Endpoint Models

### Issue

When a user selected a model via the **multi-endpoint model** feature (e.g. a `gpt-5.1` deployment hosted on a different Azure OpenAI endpoint than the default), the Semantic Kernel tabular analysis would silently fail with:

```
[Tabular SK Analysis] Attempt 1 synthesis failed after tool execution setup:
NotFoundError("Error code: 404 - {'error': {'code': 'DeploymentNotFound',
'message': 'The API deployment for this resource does not exist...'}}")
```

The analysis then fell back to returning only schema/preview context, producing degraded responses with no actual data analysis.

### Root Cause

`run_tabular_sk_analysis` always built its `AzureChatCompletion` Semantic Kernel service using `settings.get('azure_openai_gpt_endpoint')` — the **default/legacy endpoint** stored in app settings.

When the main chat route resolved a multi-endpoint model, it unpacked:

```python
gpt_client, gpt_model, gpt_provider, gpt_endpoint, gpt_auth, gpt_api_version = multi_endpoint_config
```

The resolved `gpt_model` (`gpt-5.1`) was passed to the tabular analysis, but `gpt_endpoint` and `gpt_auth` were not — so SK tried to call `gpt-5.1` at the wrong (legacy) endpoint, which returned a 404.

### Fix

Added four optional parameters to both `run_tabular_sk_analysis` and `run_tabular_analysis_with_multi_file_support`:

| Parameter | Purpose |
|---|---|
| `gpt_endpoint` | Resolved endpoint URL for the active model |
| `gpt_api_version_override` | API version for the active endpoint |
| `gpt_auth` | Auth config dict (`type`, `api_key`, `tenant_id`, etc.) |
| `gpt_provider` | Provider type (`aoai`, `aifoundry`, etc.) for scope resolution |

When `gpt_auth` and `gpt_endpoint` are provided, `run_tabular_sk_analysis` now builds `AzureChatCompletion` using the resolved multi-endpoint credentials instead of the default settings. All three auth types are supported: `api_key`, `service_principal`, and `managed_identity`. Foundry-backed endpoints use `resolve_foundry_scope_for_auth` for the correct token scope.

All four call sites (two non-streaming ~line 7832 and ~8019, two streaming ~line 10298 and ~10461) were updated to pass the override parameters when `multi_endpoint_config` is active.

### Files Modified

- `application/single_app/route_backend_chats.py`

---

## Fix 2 — Tabular SK Plugin: `FunctionExecutionException` for `Optional[str]` Parameters on Python 3.13

### Issue

After the endpoint fix allowed SK to successfully reach the model, tool invocations immediately failed with:

```
semantic_kernel.exceptions.function_exceptions.FunctionExecutionException:
Parameter sheet_name is expected to be parsed to typing.Optional[str] but is not.

TypeError: Cannot instantiate typing.Union
```

The same error appeared for `sheet_index`, `source_sheet_index`, and `target_sheet_index` parameters across multiple kernel functions.

### Root Cause

Semantic Kernel's `_parse_parameter` (in `kernel_function_from_method.py`) coerces LLM-provided string arguments by calling `param_type(value)`. When `param_type` is `Optional[str]` (which is `Union[str, None]`), **Python 3.13** raises `TypeError: Cannot instantiate typing.Union` — SK cannot instantiate the Union type itself.

The affected parameters were typed as `Annotated[Optional[str], "description"]` in the `@kernel_function` decorated methods of `TabularProcessingPlugin`. SK successfully registered these functions but failed at invocation time when the LLM passed a value.

### Fix

Changed all 12 kernel function parameters using `Annotated[Optional[str], ...]` to `Annotated[str, ...]`. The default values remain `= None` and all internal helpers (`_resolve_sheet_selection`, `_match_workbook_sheet_name`, etc.) already handle `None` and `""` as "not provided", so runtime behavior is unchanged when the LLM omits the parameter.

**Affected parameters across kernel functions:**

- `sheet_name` (8 kernel functions)
- `sheet_index` (8 kernel functions)
- `source_sheet_index` (2 kernel functions)
- `target_sheet_index` (2 kernel functions)

### Files Modified

- `application/single_app/semantic_kernel_plugins/tabular_processing_plugin.py`

---

## Versions

| Version | Change |
|---|---|
| `0.241.008` | Fix 1 — Multi-endpoint endpoint/auth pass-through for tabular SK analysis |
| `0.241.009` | Fix 2 — `Optional[str]` → `str` in kernel function `Annotated` params |
