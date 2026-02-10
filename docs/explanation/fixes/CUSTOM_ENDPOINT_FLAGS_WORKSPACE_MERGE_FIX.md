# Custom Endpoint Flags & Workspace Merge Fix (Version 0.236.058)

## Header Information
- Fix Title: Custom endpoint flag migration and workspace merge enforcement
- Issue Description: Custom endpoint toggles only applied to agents, endpoints loaded despite being disabled, and workspace merges could include global + personal + group agents simultaneously.
- Root Cause Analysis: Legacy settings names were still in use, backend routes did not consistently enforce the custom endpoint flags, and agent selection merged multiple scopes at once.
- Version Implemented: 0.236.058
- Fixed/Implemented in version: **0.236.058**
- Config version updated in: application/single_app/config.py

## Technical Details
### Files Modified
- application/single_app/functions_settings.py
- application/single_app/route_backend_agents.py
- application/single_app/route_backend_models.py
- application/single_app/route_frontend_admin_settings.py
- application/single_app/semantic_kernel_loader.py
- application/single_app/static/js/agent_modal_stepper.js
- application/single_app/static/js/workspace/group_agents.js
- application/single_app/static/js/chat/chat-agents.js
- application/single_app/static/js/chat/chat-retry.js
- application/single_app/static/js/admin/admin_settings.js
- application/single_app/templates/admin_settings.html
- application/single_app/templates/workspace.html
- application/single_app/templates/group_workspaces.html

### Code Changes Summary
- Added new custom endpoint flags (allow_user_custom_endpoints, allow_group_custom_endpoints) with migration from legacy names.
- Enforced custom endpoint flags across user/group model endpoint routes and agent payload handling.
- Scoped agent and model merges to global + workspace (personal or group) only.
- Updated frontend toggles and visibility to respect the new settings.

### Testing Approach
- Added functional test to validate migration and legacy flag sync.

### Impact Analysis
- Prevents disabled endpoint settings from leaking into workspace UI and backend payloads.
- Ensures group workspaces and personal workspaces only merge global agents with their own scope.
- Maintains backward compatibility by migrating legacy settings.

## Validation
- Test Results: Functional test added for settings migration.
- Before/After Comparison:
  - Before: Endpoint settings could appear even when disabled; merges could include global + personal + group simultaneously.
  - After: Endpoint visibility and persistence are gated by flags; merges are limited to one workspace scope.
- User Experience Improvements:
  - Clearer, consistent enforcement of custom endpoint permissions.
  - Reduced confusion around which agents/models are available per workspace.

## Related Tests
- functional_tests/test_custom_endpoint_settings_migration.py
