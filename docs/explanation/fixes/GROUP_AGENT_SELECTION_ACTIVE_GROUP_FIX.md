# Group Agent Selection Active Group Fix (Version 0.236.059)

## Header Information
- Fix Title: Enforce active group when resolving requested agents
- Issue Description: Group agent requests were resolving to the fallback researcher agent because the loader matched only personal/global agents after request overrides.
- Root Cause Analysis: Request agent overrides were stored as names only, which caused group scope to be lost; selection logic also ignored group scope when matching candidates.
- Version Implemented: 0.236.059
- Fixed/Implemented in version: **0.236.059**
- Config version updated in: application/single_app/config.py

## Technical Details
### Files Modified
- application/single_app/route_backend_chats.py
- application/single_app/semantic_kernel_loader.py
- application/single_app/config.py

### Code Changes Summary
- Persisted full request agent metadata in request context for scope-aware selection.
- Enforced group_id presence and active-group matching before loading group agents.
- Added scope-aware agent matching to prevent fallback to personal/global agents with the same name.

### Testing Approach
- Added functional test to validate scope-aware agent matching.

### Impact Analysis
- Group agent selection respects the active group and rejects mismatched group requests.
- Prevents falling back to researcher when the requested group agent is missing or out of scope.

## Validation
- Test Results: Functional test added for scope-aware selection.
- Before/After Comparison:
  - Before: Group agent request often fell back to global/personal researcher.
  - After: Group agent selection only succeeds when group_id matches the active group; otherwise kernel loads core plugins only.
- User Experience Improvements:
  - Correct agent selection for group workspaces with explicit scope enforcement.

## Related Tests
- functional_tests/test_group_agent_selection_scope.py
