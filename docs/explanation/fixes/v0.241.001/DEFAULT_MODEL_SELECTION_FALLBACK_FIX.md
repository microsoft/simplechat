# Default Model Selection Fallback Fix (Version 0.236.053)

## Overview
Adds an admin-configurable default model selection for multi-endpoint configurations and uses it as a fallback when agent requests omit model information.

## Issue Description
Agent-based requests can omit `model_id` and `model_endpoint_id`, which caused GPT initialization to fail when multiple deployments were configured. Without a default model, summarization and fallback logic could not resolve a usable GPT client.

## Root Cause Analysis
Multi-endpoint GPT resolution requires `model_id` and `model_endpoint_id`. Agent requests do not always send those fields, and there was no default model configured to bridge the gap.

## Fix Summary
- Added a default model selection to admin settings for multi-endpoint mode.
- Persisted default model selection in settings and validated it against configured endpoints/models.
- Added fallback GPT initialization using the default selection for agent requests without model info.
- Supports both Azure OpenAI and Azure AI Foundry providers.

## Files Modified
- application/single_app/functions_settings.py
- application/single_app/templates/admin_settings.html
- application/single_app/static/js/admin/admin_model_endpoints.js
- application/single_app/route_frontend_admin_settings.py
- application/single_app/route_backend_chats.py
- application/single_app/config.py
- functional_tests/test_default_model_selection_fallback.py

## Testing
- Added functional test: `test_default_model_selection_fallback.py`.

## Validation
- Verified admin UI renders the default model selector and stores the selection.
- Verified chat GPT initialization can resolve default model when agent requests omit model info.

## Version
Fixed/Implemented in version: **0.236.053**

## Config Version Reference
`config.py` updated to `VERSION = "0.236.053"`.
