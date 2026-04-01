# OpenAI Endpoint-Only Postconfig Fix

Fixed/Implemented in version: **0.240.005**

## Issue Description

Deployments that reused an external Azure OpenAI-compatible endpoint with `authenticationType == key`
could fail during `postconfig.py` even when the endpoint was intentionally configured without Azure
resource metadata.

This was most visible for endpoint-only reuse scenarios such as Azure AI Foundry project endpoints,
where the deployment can configure the application endpoint but cannot safely derive a Cognitive
Services resource for Azure CLI key lookup.

## Root Cause Analysis

`deployers/bicep/postconfig.py` always attempted to retrieve an Azure OpenAI key through Azure CLI
whenever key authentication was enabled.

That behavior assumed all configured OpenAI-compatible endpoints mapped cleanly to a standard
`Microsoft.CognitiveServices/accounts` Azure OpenAI resource and that the deployment always had the
resource group and subscription metadata needed to resolve it.

For endpoint-only reuse, those assumptions are false, so Azure CLI key retrieval failed and aborted
postconfig instead of allowing manual key configuration.

## Technical Details

### Files Modified

- `deployers/bicep/postconfig.py`
- `functional_tests/test_core_service_key_deployment_path.py`
- `application/single_app/config.py`

### Code Changes Summary

- Added guarded Azure OpenAI key retrieval so postconfig only uses Azure CLI when the endpoint is a
  recognized standard Azure OpenAI resource endpoint and the required resource metadata is present.
- Added a manual-configuration fallback that preserves any existing OpenAI key values on redeploys
  and defaults fresh deployments to a blank key when automatic retrieval is unavailable.
- Added regression coverage for the endpoint-only reuse path.
- Bumped the application version to `0.240.005`.

### Testing Approach

- Updated `functional_tests/test_core_service_key_deployment_path.py`.
- Added assertions that verify:
  - postconfig recognizes standard Azure OpenAI endpoints before attempting Azure CLI key retrieval
  - endpoint-only reuse paths keep the deployment from failing hard
  - manual OpenAI key configuration is preserved when automatic retrieval is skipped

## Validation

### Before

- key-auth postconfig always attempted Azure CLI key lookup for the configured OpenAI endpoint
- endpoint-only reuse scenarios could fail even though manual key entry was the intended fallback
- redeployments risked overwriting manual OpenAI key configuration with deployment-time failures

### After

- postconfig only attempts automatic Azure OpenAI key retrieval when the endpoint and resource
  metadata clearly identify a standard Azure OpenAI resource
- endpoint-only reuse scenarios now complete postconfig successfully and leave OpenAI keys available
  for manual configuration
- existing manual OpenAI key values are preserved on redeploy when automatic retrieval is skipped

### Impact Analysis

This fix is intentionally limited to deployment-time OpenAI key population.

- standard Azure OpenAI deployments with valid metadata continue to retrieve keys automatically
- Azure AI Foundry and other endpoint-only reuse scenarios no longer hard-fail postconfig
- no changes were made to the authentication behavior of search, document intelligence, Redis,
  Content Safety, or Speech services