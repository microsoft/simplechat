# Endpoints Tab Order & Visibility Fix (v0.236.046)

## Issue Description
Endpoints tabs appeared before Actions and were still visible even when admin settings disallowed custom endpoints.

## Root Cause Analysis
The tab ordering placed endpoints ahead of actions, and the endpoints UI was only gated by general agent settings instead of the custom endpoint permission flags.

## Version Implemented
Fixed/Implemented in version: **0.236.046**

## Technical Details
### Files Modified
- application/single_app/templates/workspace.html
- application/single_app/templates/group_workspaces.html
- application/single_app/config.py
- functional_tests/test_endpoints_tab_order_visibility.py

### Code Changes Summary
- Reordered tabs to follow Documents → Prompts → Agents → Actions → Endpoints.
- Gated endpoints tabs and panes behind admin custom endpoint settings.
- Added a functional test to verify tab ordering and gating.
- Incremented the application version.

### Testing Approach
- Functional test validates the tab order and permission gating in both templates.

## Impact Analysis
- Endpoints UI is fully hidden unless admins allow custom endpoints.
- Tab order matches the requested workflow order.

## Validation
- Functional test: functional_tests/test_endpoints_tab_order_visibility.py

## Reference to Config Version Update
- Version updated in application/single_app/config.py to **0.236.046**.
