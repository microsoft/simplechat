# OpenAI-Style Agent Harness Deployment Name Fix

Fixed in version: **0.239.205**

## Issue Description

After the harness API-version issue was fixed, requests could still fail with:

`404 - {'error': {'code': 'DeploymentNotFound', 'message': 'The API deployment for this resource does not exist'}}`

## Root Cause Analysis

The harness was selecting the correct model entry from `me.json`, but it then reused that entry's internal `id` as the OpenAI request `model` value.

For OpenAI-style Azure AI Foundry and Azure OpenAI chat requests, the `model` field must be the deployment name, not the internal catalog identifier.

## Technical Details

### Files Modified

- `scripts/openai_style_agent_harness.py`
- `functional_tests/test_openai_style_agent_harness.py`
- `functional_tests/test_new_foundry_streaming_runtime.py`
- `docs/explanation/features/OPENAI_STYLE_AGENT_HARNESS.md`
- `application/single_app/config.py`

### Code Changes Summary

- Preserved the saved model `id` for local selection and diagnostics.
- Switched the OpenAI client request model to the resolved deployment name.
- Improved logging to show both the catalog model id and the request deployment/model.
- Updated the harness feature documentation to clarify the distinction.
- Bumped `config.py` to `0.239.205` and updated dependent functional test metadata.

### Testing Approach

- `python -m py_compile scripts/openai_style_agent_harness.py`
- `python functional_tests/test_openai_style_agent_harness.py`
- live harness execution against the configured endpoint

## Validation

### Before

- The harness could select the intended model entry and still fail with `DeploymentNotFound` because it sent the internal model id as the OpenAI `model` value.

### After

- The harness sends the deployment name on the wire, which aligns the OpenAI-style request with the configured Azure AI Foundry deployment.

## Impact

This fix is limited to the standalone OpenAI-style harness and does not change the main application runtime. It makes the local harness request shape match how Azure OpenAI-compatible endpoints expect deployments to be addressed.