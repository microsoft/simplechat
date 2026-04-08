# Model Endpoint Scope Gate Enforcement Fix

Fixed/Implemented in version: **0.239.187**

## Issue Description

The non-admin model discovery and model test routes accepted caller-supplied endpoint payloads when no saved endpoint ID was provided.

That allowed authenticated user and group requests to reach arbitrary Azure OpenAI or Foundry endpoints even when custom endpoints were disabled for that scope.

## Root Cause Analysis

The user and group fetch/test routes were missing the same `enabled_required(...)` feature gates already used by the corresponding list and save routes.

In addition, `resolve_request_endpoint_payload(...)` merged raw request payload data for every scope, so the user and group handlers could execute with ad hoc endpoint, auth, and management settings instead of resolving an authorized persisted endpoint when one was referenced.

## Technical Details

### Files Modified

- `application/single_app/route_backend_models.py`
- `application/single_app/config.py`
- `functional_tests/test_model_endpoint_scope_gate_enforcement.py`

### Code Changes Summary

- Added `allow_user_custom_endpoints` guards to the user model fetch and test routes.
- Added `allow_group_custom_endpoints` guards to the group model fetch and test routes.
- Updated request payload resolution so `user` and `group` scopes reject unknown persisted `endpoint_id` values.
- Restored the intended pre-save modal workflow so feature-gated user and group routes can still fetch and test models from ad hoc payloads before an endpoint is saved.
- Restricted non-admin requests that reference a saved endpoint to persisted endpoint configuration, preventing overrides of stored endpoint, auth, or management settings.
- Moved payload resolution into the route handler `try` blocks so validation failures return controlled JSON errors instead of uncaught exceptions.
- Bumped the application version to `0.239.187`.

### Testing Approach

- Added a functional regression test that verifies the missing feature-gate decorators are present on the user and group model fetch/test routes.
- Added assertions that feature-gated user and group routes still support pre-save fetch/test payloads.
- Added assertions that requests referencing saved endpoints reject unknown IDs and resolve from saved endpoint configuration only.

## Validation

### Before

- User and group model fetch/test routes could be called with ad hoc endpoint payloads even when scope feature gates were not enforced.
- Disabling user or group custom endpoints did not fully block backend model discovery and test calls for those scopes.

### After

- User and group model fetch/test routes enforce the same scope feature flags as the endpoint-management routes.
- Feature-gated users can still fetch and test models before saving a new endpoint.
- Requests that reference a saved endpoint must reference an authorized endpoint and no longer allow stored configuration to be bypassed with raw overrides.