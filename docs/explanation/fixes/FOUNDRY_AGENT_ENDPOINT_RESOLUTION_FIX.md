# Foundry Agent Endpoint Resolution Fix (Version 0.236.051)

## Overview
Ensures Azure AI Foundry agents resolve project-scoped endpoints reliably by enriching agent configuration with the Foundry project name and endpoint ID during kernel load.

## Issue Description
Foundry agent chat invocation failed for agents configured with a Foundry endpoint that required a project name. The runtime endpoint resolution did not receive the project name, so `/api/projects/<project>` was not appended, resulting in invalid requests.

## Root Cause Analysis
`resolve_agent_config` enriched Foundry settings with the endpoint URL and API version, but did not propagate `project_name` or `endpoint_id` from the selected Foundry endpoint configuration. Agents created earlier could also lack `model_endpoint_id`, leaving only `other_settings.azure_ai_foundry.endpoint_id` for resolution.

## Fix Summary
- Enrich Foundry settings with `project_name` and `endpoint_id` from the selected endpoint configuration.
- Add endpoint ID fallback to resolve Foundry endpoint config when `model_endpoint_id` is missing.

## Files Modified
- application/single_app/semantic_kernel_loader.py
- application/single_app/config.py
- functional_tests/test_foundry_agent_endpoint_resolution.py

## Testing
- Added functional test: `test_foundry_agent_endpoint_resolution.py`.

## Validation
- Verified Foundry settings enrichment includes `project_name` and endpoint ID fallback logic.

## Version
Fixed/Implemented in version: **0.236.051**

## Config Version Reference
`config.py` updated to `VERSION = "0.236.051"`.
