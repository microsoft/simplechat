# Model Endpoint Migration Auth Fix (v0.236.016)

## Issue Description
Automatic migration to multi-endpoint settings did not preserve legacy authentication type, API key, subscription ID, or resource group, resulting in incomplete endpoint configurations.

## Root Cause Analysis
The migration logic only populated `auth.type` with the legacy `azure_openai_gpt_authentication_type` value, which uses `key` instead of the new `api_key` type. It also omitted management metadata needed for AOAI discovery.

## Version Implemented
Fixed/Implemented in version: **0.236.016**

## Technical Details
### Files Modified
- application/single_app/route_frontend_admin_settings.py
- application/single_app/config.py

### Code Changes Summary
- Mapped legacy `key` auth type to `api_key` during migration.
- Carried forward `azure_openai_gpt_key` for API key auth.
- Added `subscription_id` and `resource_group` to migrated endpoint management fields.
- Incremented the application version.

### Testing Approach
- Added a functional test to verify migration wiring preserves auth and management fields.

### Impact Analysis
- Ensures migrated multi-endpoint configurations are complete and usable.
- Prevents broken model discovery after migration.

## Validation
- Functional test: functional_tests/test_multi_endpoint_migration_auth_preserved.py

## Reference to Config Version Update
- Version updated in application/single_app/config.py to **0.236.016**.
