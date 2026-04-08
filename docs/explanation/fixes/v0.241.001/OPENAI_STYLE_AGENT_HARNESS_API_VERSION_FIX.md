# OpenAI-Style Agent Harness API Version Fix

Fixed in version: **0.239.204**

## Issue Description

The standalone harness could reach Azure AI Foundry with the OpenAI-style client and still fail the request with:

`Error code: 400 - {'error': {'code': 'BadRequest', 'message': 'API version not supported'}}`

## Root Cause Analysis

The harness was forwarding `connection.openai_api_version` from `me.json` directly into the OpenAI client as `default_query={"api-version": ...}`.

That worked poorly for saved endpoint metadata containing legacy Azure API versions such as `2024-05-01-preview`. For OpenAI-style `/openai/v1/` requests, those legacy versions are not valid request query values. The OpenAI-style path should usually omit `api-version` entirely and let the endpoint default to `v1`, or explicitly use versionless values like `preview` or `latest` when the endpoint supports them.

## Technical Details

### Files Modified

- `scripts/openai_style_agent_harness.py`
- `functional_tests/test_openai_style_agent_harness.py`
- `functional_tests/test_new_foundry_streaming_runtime.py`
- `application/single_app/config.py`

### Code Changes Summary

- Added a normalization helper for OpenAI-style request API versions.
- Preserved only `preview` and `latest` as explicit query values for `/openai/v1/` requests.
- Ignored legacy saved Azure API versions like `2024-05-01-preview` and fell back to the endpoint default `v1` behavior.
- Added logging for both the saved API version and the effective request API version.
- Bumped `config.py` to `0.239.204` and updated dependent functional test metadata.

### Testing Approach

- `python -m py_compile scripts/openai_style_agent_harness.py`
- `python functional_tests/test_openai_style_agent_harness.py`
- `python functional_tests/test_new_foundry_streaming_runtime.py`

## Validation

### Before

- The harness forwarded a legacy Azure API version on the OpenAI-style `/openai/v1/` path and the request failed with `API version not supported`.

### After

- The harness filters saved API-version metadata to values that are valid for the OpenAI-style client and otherwise lets the endpoint use its default `v1` behavior.

## Impact

This fix is limited to the standalone OpenAI-style harness and does not change the main application runtime. It makes the harness compatible with existing saved Foundry endpoint metadata that still contains legacy Azure API-version strings.