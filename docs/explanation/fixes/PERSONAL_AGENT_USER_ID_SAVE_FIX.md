# Personal Agent User ID Save Fix (v0.236.050)

## Issue Description
Personal agents were saved without the `user_id` property, causing them to be missing from user-scoped queries.

## Root Cause Analysis
The save flow populated `user_id` on a sanitized copy, but persisted the unsanitized payload without `user_id`.

## Version Implemented
Fixed/Implemented in version: **0.236.050**

## Technical Details
### Files Modified
- application/single_app/functions_personal_agents.py
- application/single_app/config.py
- functional_tests/test_personal_agent_user_id_saved.py

### Code Changes Summary
- Assigned `user_id` and metadata to the payload persisted to Cosmos.
- Incremented the application version.

### Testing Approach
- Functional test validates `user_id` assignment in the save flow.

## Impact Analysis
- Personal agents now show up in user-scoped lists and queries.

## Validation
- Functional test: functional_tests/test_personal_agent_user_id_saved.py

## Reference to Config Version Update
- Version updated in application/single_app/config.py to **0.236.050**.
