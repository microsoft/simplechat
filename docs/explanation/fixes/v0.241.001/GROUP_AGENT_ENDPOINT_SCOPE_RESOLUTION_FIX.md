# Group Agent Endpoint Scope Resolution Fix

Fixed/Implemented in version: **0.239.192**

`config.py` updated to `VERSION = "0.239.192"`.

## Header Information

### Issue Description

Group agents already persisted their own `group_id`, and selected-agent payloads already carried that same group identity.

However, the runtime loader still resolved group-scoped model endpoints from the caller's current active group. If the user switched active groups after selecting a group agent, or reopened a conversation from a different group context, endpoint lookup could resolve against the wrong group.

### Root Cause Analysis

The endpoint resolution branches inside `semantic_kernel_loader.py` recomputed group scope with `require_active_group(get_current_user_id())` instead of preferring authoritative scope already available on the request.

The same loader also used the wrong legacy fallback flag when computing `allow_group_custom_endpoints`, which allowed group endpoint resolution behavior to depend on the user-scoped legacy custom-agent setting.

### Version Implemented

`0.239.192`

## Technical Details

### Files Modified

- `application/single_app/semantic_kernel_loader.py`
- `application/single_app/config.py`
- `functional_tests/test_group_agent_endpoint_scope_resolution.py`

### Code Changes Summary

- Introduced an explicit `group_scope_id` parameter to the loader path that resolves single-agent runtime configuration.
- Changed group endpoint resolution to use conversation group first, persisted group second, active group only as a legacy fallback.
- Added membership validation against the resolved group scope before loading group agents or group-scoped endpoints.
- Corrected the loader feature-flag fallback so group custom-endpoint behavior only uses the group flag pair.

### Testing Approach

- Added `functional_tests/test_group_agent_endpoint_scope_resolution.py` to verify the resolved group-scope precedence, the group-specific custom-endpoint flag mapping, and the continued preservation of `group_id` in group agent persistence and selection payloads.

### Impact Analysis

- Prevents group agents from resolving endpoints from the wrong active group after workspace changes.
- Keeps group endpoint resolution aligned with persisted agent scope and conversation scope.
- Removes unintended coupling between group endpoint routing and the user-scoped legacy custom-endpoint flag.

## Validation

### Before

- Group agent endpoint resolution could drift to the user's currently active group even when the selected agent or conversation belonged to a different group.
- Group custom-endpoint behavior could be activated by the wrong legacy user-scoped flag.

### After

- Group agents resolve model endpoints from the authoritative request scope: conversation group first, persisted group second, active group only as a legacy fallback.
- Group endpoint resolution remains blocked unless the caller is still authorized for the resolved group.
- Group custom-endpoint routing now depends only on the group-scoped flag pair.

## Related References

- Prior selection-scope hardening: `docs/explanation/fixes/GROUP_AGENT_SELECTION_ACTIVE_GROUP_FIX.md`
- Related runtime source: `application/single_app/route_backend_chats.py`