# Governance Scope Toggle Visibility Fix

Fixed in version: **0.242.062**

## Issue Description

The Admin Settings Governance tab could appear to be missing personal and group governance capabilities. The source template included the full personal, group, and global scope controls, but the runtime governance script hid controls when the matching primary feature switch was disabled.

This made personal actions, personal endpoints, group endpoints, group agents, and group actions look unavailable even though the backend governance policy keys and enforcement hooks still existed.

## Root Cause Analysis

`application/single_app/static/js/admin/admin_governance.js` used `d-none` to remove governance scope toggle wrappers whenever `isGovernanceFeatureApplicable()` returned false. That applicability check is based on primary feature switches such as `allow_user_plugins`, `allow_group_agents`, and `allow_group_custom_endpoints`.

Because the Governance tab removed unavailable controls entirely, admins could not see the complete governance surface or understand that those controls depended on primary feature enablement.

## Technical Details

Files modified:

- `application/single_app/static/js/admin/admin_governance.js`
- `application/single_app/config.py`
- `functional_tests/test_governance_admin_scope_toggle_visibility.py`
- `docs/explanation/fixes/GOVERNANCE_SCOPE_TOGGLE_VISIBILITY_FIX.md`

Code changes summary:

- Scope toggle wrappers are always kept visible in the Governance tab.
- Scope toggles whose matching primary feature is disabled are marked disabled instead of hidden.
- Disabled controls receive an explanatory title so the dependency is discoverable.
- The existing Feature Policies table filtering remains focused on features that are both enabled and governed.
- The app version was updated to `0.242.062` in `application/single_app/config.py`.

## Validation

Functional coverage was added in `functional_tests/test_governance_admin_scope_toggle_visibility.py` to verify that:

- all nine governance scope controls are present in the admin template
- runtime JavaScript no longer hides unavailable scope controls with `d-none`
- unavailable controls are disabled instead of removed from the Governance tab

Before the fix, admins could interpret hidden controls as missing feature support. After the fix, the Governance tab shows the full personal, group, and global governance surface while still preventing inactive feature scopes from being saved as active governance checks.
