# Default Model Dropdown Foundry Models Fix (Version 0.236.057)

## Issue Description
The admin multi-endpoint default model dropdown did not list Azure AI Foundry models when model IDs or enabled flags were missing in stored endpoint data. This caused the dropdown to only show Azure OpenAI entries.

## Root Cause Analysis
Endpoint data could be missing model IDs and enabled flags, and those values were not normalized at the data layer. Missing identifiers made Foundry models appear unavailable in the dropdown.

## Fix Summary
- Normalize model endpoints on the backend so IDs and enabled flags are consistently present.
- Use stable fallback identifiers derived from deployment names when IDs are missing.

## Technical Details
- Files modified:
  - application/single_app/functions_settings.py
  - application/single_app/route_frontend_admin_settings.py
  - application/single_app/route_backend_models.py
  - application/single_app/route_backend_chats.py
  - application/single_app/config.py
- Added backend normalization so endpoints/models always include stable IDs and enabled flags.
- Updated multi-endpoint resolution to match by deployment/model names when IDs are missing.

## Testing
- Functional test: functional_tests/test_model_endpoint_normalization_backend.py

## Impact Analysis
- Admins can now see Foundry deployments in the default model dropdown even when IDs were previously missing.
- Existing endpoint data remains compatible and is normalized in-memory before rendering.

## Fixed/Implemented in version: **0.236.057**

## Config Version Update
- Updated VERSION in application/single_app/config.py to 0.236.057.
