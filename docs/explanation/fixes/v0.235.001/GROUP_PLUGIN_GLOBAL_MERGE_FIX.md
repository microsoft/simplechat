# Group Plugin Global Merge Fix

Fixed/Implemented in version: **0.233.164**

## Issue Description
Group workspaces were unable to see or select globally managed actions when the
`merge_global_semantic_kernel_with_workspace` setting was enabled. The group
plugins API only returned group-scoped actions, which left the agent creation
modal without access to global plugins.

## Root Cause
The `/api/group/plugins` endpoint did not append global actions to its response
payload. Because of this, the front-end never received the global entries and
could not surface them inside the selection modal.

## Code Changes Summary
- Merge global actions into the group plugins API response while marking them as
  read-only.
- Prevent group routes from creating, updating, or deleting globally managed
  actions.
- Update the group workspace UI to badge global plugins and block edit/delete
  attempts.
- Preserve global flags in the agent modal so the selection flow displays
  accurate scope metadata.

## Testing Approach
- Added functional test `test_group_plugin_global_merge_fix.py` covering the
  merge helper and normalization logic.

## Impact Analysis
Users in group workspaces can now select and use global actions when the merge
setting is enabled, while global assets remain protected from modification at
the group level.
