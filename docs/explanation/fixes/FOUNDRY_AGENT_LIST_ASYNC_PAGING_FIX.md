# Foundry Agent List Async Paging Fix (v0.236.047)

## Issue Description
Fetching Azure AI Foundry agents failed with "object AsyncItemPaged can't be used in 'await' expression".

## Root Cause Analysis
The async list operation returns an `AsyncItemPaged` sequence, but the code awaited it directly instead of iterating over the async iterator.

## Version Implemented
Fixed/Implemented in version: **0.236.047**

## Technical Details
### Files Modified
- application/single_app/foundry_agent_runtime.py
- application/single_app/config.py
- functional_tests/test_foundry_agent_list_async_paging.py

### Code Changes Summary
- Stopped awaiting the list call and added async iteration for paged results.
- Kept support for list/dict responses.
- Incremented the application version.

### Testing Approach
- Functional test checks for async iteration and non-awaited list calls.

## Impact Analysis
- Foundry agent discovery now works reliably across paged responses.

## Validation
- Functional test: functional_tests/test_foundry_agent_list_async_paging.py

## Reference to Config Version Update
- Version updated in application/single_app/config.py to **0.236.047**.
