# Agent Modal Model Endpoint Filtering Fix (Version 0.236.056)

## Issue Description
Local agent modals did not show non-Azure OpenAI endpoints when selecting a model. This made Azure AI Foundry models unavailable in the modal even when multi-endpoint settings returned them.

## Root Cause Analysis
The agent modal dropdown filtered model endpoints by provider, allowing only Azure OpenAI providers for local agents. Foundry endpoints were excluded even when provided by the settings API.

## Fix Summary
- Allow local agents to include non-AOAI providers in the modal dropdown.
- Normalize model identifiers and display labels so entries without explicit IDs still render.

## Technical Details
- Files modified:
  - application/single_app/static/js/agents_common.js
  - application/single_app/config.py
- Updated provider filtering logic to only restrict when the agent type is explicitly `aifoundry`.
- Added model ID and display name normalization to improve dropdown resilience.

## Testing
- Functional test: functional_tests/test_agent_modal_model_endpoint_filtering.py

## Impact Analysis
- Local agent modals now list Foundry endpoints wherever the modal is used (admin, user, group).
- Existing AOAI behavior is unchanged.

## Fixed/Implemented in version: **0.236.056**

## Config Version Update
- Updated VERSION in application/single_app/config.py to 0.236.056.
