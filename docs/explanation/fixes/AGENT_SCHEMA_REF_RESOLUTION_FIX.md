# Agent Schema Ref Resolution Fix (v0.236.049)

## Issue Description
Agent validation failed with `PointerToNowhere: '/definitions/OtherSettings'` when validating agents that include `other_settings`.

## Root Cause Analysis
The validator was pointed at the `Agent` sub-schema, which stripped shared `definitions` and broke `$ref` resolution.

## Version Implemented
Fixed/Implemented in version: **0.236.049**

## Technical Details
### Files Modified
- application/single_app/json_schema_validation.py
- application/single_app/config.py
- functional_tests/test_agent_schema_ref_resolution.py

### Code Changes Summary
- Validate agents using the root schema and include a schema resolver.
- Incremented the application version.

### Testing Approach
- Functional test asserts the root schema and resolver are used.

## Impact Analysis
- Agent schema `$ref` resolution works as intended.

## Validation
- Functional test: functional_tests/test_agent_schema_ref_resolution.py

## Reference to Config Version Update
- Version updated in application/single_app/config.py to **0.236.049**.
